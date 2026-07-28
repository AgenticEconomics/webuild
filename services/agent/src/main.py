"""Lightweight WeBuild Agent — connects to Relay, calls DashScope API.

Bridges the Web IDE (browser) to an LLM without requiring the full
Rust webuild CLI. Runs as a persistent service, auto-joining sessions.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import structlog
import websockets

logger = structlog.get_logger()

RELAY_URL = os.environ.get("RELAY_URL", "ws://relay-server:8002/ws")
RELAY_TOKEN = os.environ.get(
    "RELAY_INTERNAL_TOKEN",
    os.environ.get("RELAY_TOKEN", "internal-agent"),
)
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
MODEL = os.environ.get("MODEL", "qwen-max")
POLL_INTERVAL = 2


class WeBuildAgent:
    """Handles one session: receives prompts, calls DashScope, sends responses."""

    def __init__(self, ws, session_id: str):
        self.ws = ws
        self.session_id = session_id
        self.conversation_history: list[dict] = [
            {
                "role": "system",
                "content": (
                    "You are WeBuild, an AI programming assistant. Help users with "
                    "coding tasks, debugging, and software development. Be concise and practical."
                ),
            }
        ]

    async def handle_message(self, raw: str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        method = msg.get("method")
        if method in ("__ping", "ping"):
            return

        if method == "session/prompt":
            params = msg.get("params", {})
            request_id = msg.get("id")
            prompt_blocks = params.get("prompt", [])

            user_text = ""
            for block in prompt_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    user_text += block.get("text", "")

            if not user_text:
                if request_id is not None:
                    await self.ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": {"stopReason": "end_turn"},
                            }
                        )
                    )
                return

            logger.info(
                "agent.prompt_received",
                session_id=self.session_id,
                length=len(user_text),
            )

            self.conversation_history.append({"role": "user", "content": user_text})

            await self.send_notification(
                "session/update",
                {
                    "sessionId": self.session_id,
                    "update": {
                        "sessionUpdate": "user_message_chunk",
                        "content": {"type": "text", "text": user_text},
                    },
                },
            )

            await self.call_dashscope(request_id)

        elif method == "session/cancel":
            logger.info("agent.cancel", session_id=self.session_id)

    async def call_dashscope(self, request_id):
        """Call DashScope API and stream the response as ACP notifications."""
        if not DASHSCOPE_API_KEY:
            err = "Error: DASHSCOPE_API_KEY is not configured on the agent service"
            await self.send_notification(
                "session/update",
                {
                    "sessionId": self.session_id,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": err},
                    },
                },
            )
            if request_id is not None:
                await self.ws.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"stopReason": "end_turn"},
                        }
                    )
                )
            return

        headers = {
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": MODEL,
            "messages": self.conversation_history,
            "stream": True,
        }

        full_response = ""
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{DASHSCOPE_BASE_URL}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        logger.error(
                            "dashscope.error",
                            status=response.status_code,
                            body=body.decode()[:200],
                        )
                        full_response = (
                            f"Error: DashScope returned {response.status_code}: "
                            f"{body.decode()[:200]}"
                        )
                        await self.send_notification(
                            "session/update",
                            {
                                "sessionId": self.session_id,
                                "update": {
                                    "sessionUpdate": "agent_message_chunk",
                                    "content": {"type": "text", "text": full_response},
                                },
                            },
                        )
                    else:
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                text = delta.get("content", "")
                                if text:
                                    full_response += text
                                    await self.send_notification(
                                        "session/update",
                                        {
                                            "sessionId": self.session_id,
                                            "update": {
                                                "sessionUpdate": "agent_message_chunk",
                                                "content": {"type": "text", "text": text},
                                            },
                                        },
                                    )
                            except (json.JSONDecodeError, IndexError, KeyError):
                                continue

        except Exception as e:
            logger.error("dashscope.exception", error=str(e))
            full_response = f"Error calling DashScope: {e}"
            await self.send_notification(
                "session/update",
                {
                    "sessionId": self.session_id,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": full_response},
                    },
                },
            )

        self.conversation_history.append(
            {"role": "assistant", "content": full_response}
        )

        if request_id is not None:
            await self.ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"stopReason": "end_turn"},
                    }
                )
            )

        logger.info(
            "agent.turn_complete",
            session_id=self.session_id,
            response_length=len(full_response),
        )

    async def send_notification(self, method: str, params: dict):
        await self.ws.send(
            json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        )


async def run_session(ws_url: str, session_id: str) -> None:
    """Connect to relay as agent for one session.

    Single-shot: when the relay closes (browser left / pair timeout), return
    so /discover can re-queue the session if a browser is still waiting.
    Do NOT reconnect forever — that creates zombie agents on dead sessions.
    """
    url = f"{ws_url}?session_id={session_id}&role=agent&token={RELAY_TOKEN}"
    try:
        async with websockets.connect(url, open_timeout=10, ping_interval=20) as ws:
            logger.info("agent.connected", session_id=session_id)
            agent = WeBuildAgent(ws, session_id)
            async for raw in ws:
                await agent.handle_message(raw)
    except websockets.ConnectionClosed as e:
        logger.warning(
            "agent.disconnected",
            session_id=session_id,
            code=getattr(e, "code", None),
            reason=getattr(e, "reason", "") or "",
        )
    except Exception as e:
        logger.error("agent.error", session_id=session_id, error=str(e))
    finally:
        logger.info("agent.session_done", session_id=session_id)


async def main():
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
    )

    logger.info("agent.starting", relay=RELAY_URL, model=MODEL)

    if not DASHSCOPE_API_KEY:
        logger.error("agent.no_api_key")
        return

    relay_rest = RELAY_URL.replace("ws://", "http://").replace("wss://", "https://")
    if relay_rest.endswith("/ws"):
        relay_rest = relay_rest[: -len("/ws")]
    discover_url = f"{relay_rest}/discover"
    logger.info("agent.discover_url", url=discover_url)

    async with httpx.AsyncClient(timeout=10) as client:
        known_sessions: set[str] = set()
        tasks: dict[str, asyncio.Task] = {}

        while True:
            try:
                # Reap finished tasks so discover can re-join if needed
                done = [sid for sid, t in tasks.items() if t.done()]
                for sid in done:
                    tasks.pop(sid, None)
                    known_sessions.discard(sid)

                resp = await client.get(discover_url)
                if resp.status_code == 200:
                    waiting = resp.json()
                    for s in waiting:
                        sid = s.get("session_id")
                        if sid and sid not in known_sessions:
                            known_sessions.add(sid)
                            logger.info("agent.joining_session", session_id=sid)
                            tasks[sid] = asyncio.create_task(
                                run_session(RELAY_URL, sid)
                            )

            except Exception as e:
                logger.debug("agent.poll_error", error=str(e))

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
