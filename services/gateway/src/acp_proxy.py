"""ACP WebSocket proxy — bidirectional JSON-RPC forwarding between browser and sandbox pod."""

from __future__ import annotations

import asyncio
import json

import httpx
import structlog
from fastapi import WebSocket, WebSocketDisconnect

from src.k8s_client import K8sClient

logger = structlog.get_logger()

ACP_PORT = 8080
ACP_WS_PATH = "/ws"


class ACPProxy:
    """Proxies WebSocket connections from the browser to a sandbox pod's ACP WebSocket."""

    def __init__(self, k8s: K8sClient) -> None:
        self._k8s = k8s

    async def proxy(self, browser_ws: WebSocket, sandbox_id: str) -> None:
        """
        Establish a bidirectional WebSocket proxy:
          browser_ws <--> sandbox pod ACP WebSocket
        """
        await browser_ws.accept()

        # Resolve pod IP
        pod_ip = await asyncio.to_thread(self._k8s.get_pod_ip, sandbox_id)
        if pod_ip is None:
            await browser_ws.close(code=4004, reason="Sandbox pod not found or not running")
            logger.warn("acp_proxy_pod_missing", sandbox_id=sandbox_id)
            return

        target_url = f"ws://{pod_ip}:{ACP_PORT}{ACP_WS_PATH}"
        logger.info("acp_proxy_connect", sandbox_id=sandbox_id, target=target_url)

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "GET",
                    f"http://{pod_ip}:{ACP_PORT}/health",
                    timeout=5.0,
                ) as resp:
                    if resp.status_code != 200:
                        logger.warn("acp_proxy_health_fail", sandbox_id=sandbox_id, status=resp.status_code)
        except Exception:
            logger.warn("acp_proxy_health_error", sandbox_id=sandbox_id)
            # Continue anyway — the WS might still work

        # Use websockets client to connect to pod
        try:
            import websockets

            async with websockets.connect(
                target_url,
                max_size=10 * 1024 * 1024,  # 10MB
                ping_interval=20,
                ping_timeout=10,
            ) as pod_ws:
                logger.info("acp_proxy_connected", sandbox_id=sandbox_id)

                # Bidirectional forwarding
                browser_to_pod = asyncio.create_task(
                    self._forward_browser_to_pod(browser_ws, pod_ws, sandbox_id)
                )
                pod_to_browser = asyncio.create_task(
                    self._forward_pod_to_browser(pod_ws, browser_ws, sandbox_id)
                )

                done, pending = await asyncio.wait(
                    [browser_to_pod, pod_to_browser],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Cancel the other direction
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        except WebSocketDisconnect:
            logger.info("acp_proxy_browser_disconnect", sandbox_id=sandbox_id)
        except Exception:
            logger.exception("acp_proxy_error", sandbox_id=sandbox_id)
        finally:
            try:
                await browser_ws.close()
            except Exception:
                pass

    async def _forward_browser_to_pod(self, browser_ws: WebSocket, pod_ws, sandbox_id: str) -> None:
        """Forward messages from browser to sandbox pod."""
        try:
            while True:
                data = await browser_ws.receive_text()
                # Validate JSON-RPC structure (best-effort)
                try:
                    msg = json.loads(data)
                    logger.debug("acp_msg_browser_to_pod", sandbox_id=sandbox_id, method=msg.get("method", ""))
                except json.JSONDecodeError:
                    logger.warn("acp_msg_invalid_json", sandbox_id=sandbox_id)

                await pod_ws.send(data)
        except WebSocketDisconnect:
            logger.info("acp_browser_closed", sandbox_id=sandbox_id)

    async def _forward_pod_to_browser(self, pod_ws, browser_ws: WebSocket, sandbox_id: str) -> None:
        """Forward messages from sandbox pod to browser."""
        try:
            async for data in pod_ws:
                if isinstance(data, bytes):
                    await browser_ws.send_bytes(data)
                else:
                    try:
                        msg = json.loads(data)
                        logger.debug("acp_msg_pod_to_browser", sandbox_id=sandbox_id, id=msg.get("id"))
                    except json.JSONDecodeError:
                        pass
                    await browser_ws.send_text(data)
        except Exception:
            logger.info("acp_pod_closed", sandbox_id=sandbox_id)
