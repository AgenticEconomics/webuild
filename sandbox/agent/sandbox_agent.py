"""Sandbox Agent — connects outbound to Relay as an agent.

On startup, connects to the Relay server as role=agent for the given session.
The browser connects to the same session as role=browser.
The Relay bridges messages between them.
Handles session/prompt by calling DashScope API and streaming responses.
"""

import asyncio
import json
import os
import signal
import sys

import httpx
import structlog
import websockets

logger = structlog.get_logger()

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
MODEL = os.environ.get("MODEL", "qwen-max")
RELAY_URL = os.environ.get("RELAY_URL", "ws://relay-server:8002/ws")
SESSION_ID = os.environ.get("SANDBOX_ID", os.environ.get("SESSION_ID", "sandbox-default"))
RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "internal-sandbox-agent")
WEBUILD_USER_ID = os.environ.get("WEBUILD_USER_ID", "")
RECONNECT_DELAY = 3


class SandboxSession:
    """Handles ACP messages for one sandbox session."""

    def __init__(self, ws, session_id: str):
        self.ws = ws
        self.session_id = session_id
        self.history: list[dict] = [
            {
                "role": "system",
                "content": (
                    "You are WeBuild, an AI programming assistant running inside a cloud sandbox. "
                    "You have access to a Linux filesystem at /workspace, shell commands, and development tools. "
                    "Help users with coding tasks, debugging, and software development. Be concise and practical."
                ),
            }
        ]

    async def handle_message(self, raw: str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        method = msg.get("method")
        request_id = msg.get("id")

        if method == "initialize":
            await self.ws.send(json.dumps({
                "jsonrpc": "2.0", "id": request_id,
                "result": {
                    "protocolVersion": {"major": 0, "minor": 1, "patch": 0},
                    "agentCapabilities": {"tools": True},
                    "authMethods": [],
                    "agentInfo": {"name": "webuild-sandbox-agent", "version": "0.1.0"},
                },
            }))

        elif method == "session/new":
            await self.ws.send(json.dumps({
                "jsonrpc": "2.0", "id": request_id,
                "result": {"sessionId": self.session_id, "modes": None, "configOptions": None},
            }))

        elif method == "session/prompt":
            params = msg.get("params", {})
            prompt_blocks = params.get("prompt", [])
            user_text = ""
            for block in prompt_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    user_text += block.get("text", "")

            if not user_text:
                if request_id is not None:
                    await self.ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": request_id,
                        "result": {"stopReason": "end_turn"},
                    }))
                return

            logger.info("sandbox.prompt", session_id=self.session_id, length=len(user_text))
            self.history.append({"role": "user", "content": user_text})

            await self._send_update("user_message_chunk", {"type": "text", "text": user_text})
            await self._call_dashscope(request_id)

        elif method == "session/cancel":
            logger.info("sandbox.cancel", session_id=self.session_id)

        elif method == "__ping":
            pass  # Relay keepalive

    async def _call_dashscope(self, request_id):
        headers = {
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"model": MODEL, "messages": self.history, "stream": True}

        full_response = ""
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", f"{DASHSCOPE_BASE_URL}/chat/completions",
                    json=payload, headers=headers,
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        error_msg = f"Error: DashScope {resp.status_code}: {body.decode()[:200]}"
                        await self._send_update("agent_message_chunk", {"type": "text", "text": error_msg})
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                full_response += text
                                await self._send_update(
                                    "agent_message_chunk", {"type": "text", "text": text}
                                )
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue

        except Exception as e:
            logger.error("sandbox.dashscope_error", error=str(e))
            full_response = f"Error: {e}"
            await self._send_update("agent_message_chunk", {"type": "text", "text": full_response})

        self.history.append({"role": "assistant", "content": full_response})

        if request_id is not None:
            await self.ws.send(json.dumps({
                "jsonrpc": "2.0", "id": request_id,
                "result": {"stopReason": "end_turn"},
            }))

        logger.info("sandbox.turn_complete", length=len(full_response))

    async def _send_update(self, update_type: str, content: dict):
        await self.ws.send(json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": self.session_id,
                "update": {"sessionUpdate": update_type, "content": content},
            },
        }))


async def connect_to_relay():
    """Connect to the Relay as an agent and handle messages."""
    from urllib.parse import urlencode
    params = {
        "session_id": SESSION_ID,
        "role": "agent",
        "token": RELAY_TOKEN,
    }
    if WEBUILD_USER_ID:
        params["user_id"] = WEBUILD_USER_ID
    url = f"{RELAY_URL}?{urlencode(params)}"
    logger.info("sandbox.connecting", url=RELAY_URL, session_id=SESSION_ID)

    while True:
        try:
            async with websockets.connect(url, open_timeout=10, ping_interval=20) as ws:
                logger.info("sandbox.connected", session_id=SESSION_ID)
                session = SandboxSession(ws, SESSION_ID)

                async for raw in ws:
                    await session.handle_message(raw)

        except websockets.ConnectionClosed as e:
            logger.warning("sandbox.disconnected", code=e.code, reason=e.reason)
        except Exception as e:
            logger.error("sandbox.connection_error", error=str(e))

        logger.info("sandbox.reconnecting", delay=RECONNECT_DELAY)
        await asyncio.sleep(RECONNECT_DELAY)


async def main():
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )

    logger.info(
        "sandbox_agent.starting",
        model=MODEL,
        relay=RELAY_URL,
        session_id=SESSION_ID,
    )

    if not DASHSCOPE_API_KEY:
        logger.warning("sandbox_agent.no_api_key", detail="DashScope calls will fail")

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: sys.exit(0))

    await connect_to_relay()


if __name__ == "__main__":
    asyncio.run(main())
