"""Async API client for OSHHome BFF."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from aiohttp import ClientResponseError, ClientSession, WSMsgType, WSServerHandshakeError

from .const import DEFAULT_REST_TIMEOUT


class OshHomeAuthError(Exception):
    """Raised when OSHHome credentials are invalid or expired."""


class OshHomeApiClient:
    """Thin async client for the OSHHome BFF."""

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
        try:
            async for message in websocket:
                if message.type == WSMsgType.TEXT:
                    yield message.json()
                elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        finally:
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
