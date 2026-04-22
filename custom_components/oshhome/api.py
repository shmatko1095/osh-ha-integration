"""Async API client for OSHHome BFF."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import contextlib
from typing import Any

from aiohttp import ClientResponseError, ClientSession, WSMsgType, WSServerHandshakeError

from .const import DEFAULT_REST_TIMEOUT


class OshHomeAuthError(Exception):
    """Raised when OSHHome credentials are invalid or expired."""


class OshHomeWebSocketClosed(Exception):
    """Raised when websocket stream closes and reconnect should be attempted."""

    def __init__(
        self,
        close_code: int | None,
        message_type: WSMsgType,
        reason: str | None = None,
    ) -> None:
        self.close_code = close_code
        self.message_type = message_type
        self.reason = reason
        details = reason or "stream closed"
        super().__init__(
            f"WebSocket stream closed type={message_type.name} code={close_code}: {details}"
        )


class OshHomeApiClient:
    """Thin async client for the OSHHome BFF."""

    _APP_PING_INTERVAL_SECONDS = 25

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        access_token_provider: Callable[[], Awaitable[str]],
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._access_token_provider = access_token_provider

    async def async_get_bootstrap(self) -> dict[str, Any]:
        """Fetch the HA bootstrap document."""
        return await self._request_json("GET", "/v1/ha/bootstrap")

    async def async_get_states(self, since: int) -> dict[str, Any]:
        """Fetch delta states since a cursor."""
        return await self._request_json("GET", "/v1/ha/states", params={"since": since})

    async def async_execute_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a write command through the BFF."""
        return await self._request_json("POST", "/v1/ha/commands", json=payload)

    async def async_stream(self, installation_id: str, last_cursor: int) -> AsyncIterator[dict[str, Any]]:
        """Connect to the websocket stream."""
        ws_url = self._base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        headers = await self._auth_headers()
        try:
            websocket = await self._session.ws_connect(
                f"{ws_url}/v1/ha/ws",
                headers=headers,
                heartbeat=30,
                receive_timeout=None,
            )
        except (ClientResponseError, WSServerHandshakeError) as err:
            self._raise_auth_error_if_needed(err)
            raise
        await websocket.send_json(
            {
                "type": "hello",
                "installation_id": installation_id,
                "last_cursor": int(last_cursor),
            }
        )
        ping_task = asyncio.create_task(self._async_app_ping_loop(websocket))
        try:
            async for message in websocket:
                if message.type == WSMsgType.TEXT:
                    yield message.json()
                elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    reason: str | None = None
                    if message.type == WSMsgType.ERROR:
                        error = websocket.exception()
                        if error is not None:
                            reason = str(error)
                    if reason is None and isinstance(message.extra, str) and message.extra:
                        reason = message.extra
                    raise OshHomeWebSocketClosed(
                        self._safe_close_code(websocket.close_code),
                        message.type,
                        reason,
                    )
            raise OshHomeWebSocketClosed(
                self._safe_close_code(websocket.close_code),
                WSMsgType.CLOSED,
                "websocket iterator ended",
            )
        finally:
            ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ping_task
            await websocket.close()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                params=params,
                json=json,
                timeout=DEFAULT_REST_TIMEOUT,
            ) as response:
                response.raise_for_status()
                return await response.json()
        except ClientResponseError as err:
            self._raise_auth_error_if_needed(err)
            raise

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._access_token_provider()
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _raise_auth_error_if_needed(err: ClientResponseError | WSServerHandshakeError) -> None:
        if err.status in (401, 403):
            raise OshHomeAuthError("OAuth token rejected by OSH backend") from err

    @staticmethod
    def _safe_close_code(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def _async_app_ping_loop(self, websocket: Any) -> None:
        """Keep app-level ping/pong flow active for intermediaries/proxies."""
        while True:
            await asyncio.sleep(self._APP_PING_INTERVAL_SECONDS)
            if getattr(websocket, "closed", False):
                return
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:  # noqa: BLE001
                return
