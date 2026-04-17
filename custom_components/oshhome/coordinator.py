"""Coordinator for OSHHome."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any
from uuid import uuid4

from aiohttp import ClientError, ClientResponseError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import OshHomeApiClient, OshHomeAuthError
from .const import (
    ATTR_ATTRIBUTES,
    ATTR_CURSOR,
    ATTR_DELETED,
    ATTR_STATE,
    CONF_API_BASE_URL,
    CONF_INSTALLATION_ID,
    DEFAULT_API_BASE_URL,
    DOMAIN,
    PLATFORMS,
)
from .oauth import OshHomeOAuthSession

_LOGGER = logging.getLogger(__name__)


class OshHomeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Store bootstrap and live state for OSHHome."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        oauth_session: OshHomeOAuthSession,
    ) -> None:
        self.entry = entry
        self._oauth_session = oauth_session
        self._api_base_url: str = entry.data.get(CONF_API_BASE_URL, DEFAULT_API_BASE_URL)
        self._installation_id: str = entry.data.get(CONF_INSTALLATION_ID, str(uuid4()))
        self.client = OshHomeApiClient(
            async_get_clientsession(hass),
            self._api_base_url,
            self._oauth_session.async_get_access_token,
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=None,
            update_method=self._async_refresh_bootstrap,
            config_entry=entry,
        )
        self.cursor = 0
        self._stream_task: asyncio.Task[None] | None = None

        self._device_payloads: dict[str, dict[str, Any]] = {}
        self._entity_payloads: dict[str, dict[str, Any]] = {}
        self._entity_runtime: dict[str, dict[str, Any]] = {}
        self._inventory_listeners: dict[str, list] = {platform: [] for platform in PLATFORMS}

    async def async_initialize(self) -> None:
        """Initialize integration data."""
        await self.async_config_entry_first_refresh()
        if hasattr(self.entry, "async_create_background_task"):
            self._stream_task = self.entry.async_create_background_task(
                self.hass,
                self._async_stream_loop(),
                "oshhome_stream_loop",
            )
        else:
            self._stream_task = self.hass.async_create_task(self._async_stream_loop())

    async def async_shutdown(self) -> None:
        """Stop background tasks."""
        if self._stream_task is not None:
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
            self._stream_task = None

    def async_subscribe_inventory(self, platform: str, callback) -> callable:
        """Subscribe for inventory changes for one platform."""
        listeners = self._inventory_listeners.setdefault(platform, [])
        listeners.append(callback)

        def _unsubscribe() -> None:
            if callback in listeners:
                listeners.remove(callback)

        return _unsubscribe

    def entities_for_platform(self, platform: str) -> list[dict[str, Any]]:
        """Return active entities for a platform."""
        result: list[dict[str, Any]] = []
        for entity_uid, payload in self._entity_payloads.items():
            if payload.get("platform") != platform:
                continue
            runtime = self._entity_runtime.get(entity_uid, {})
            if runtime.get(ATTR_DELETED, False):
                continue
            result.append(payload)
        return result

    def get_entity_payload(self, entity_uid: str) -> dict[str, Any] | None:
        """Get entity descriptor by uid."""
        return self._entity_payloads.get(entity_uid)

    def get_device_payload(self, device_uid: str) -> dict[str, Any] | None:
        """Get device descriptor by uid."""
        return self._device_payloads.get(device_uid)

    def get_entity_runtime(self, entity_uid: str) -> dict[str, Any]:
        """Get runtime state for entity."""
        return self._entity_runtime.get(entity_uid, {})

    async def async_execute_command(
        self,
        entity_uid: str,
        command: str,
        value: Any,
    ) -> dict[str, Any]:
        """Send command through OSH backend."""
        payload = self._entity_payloads.get(entity_uid)
        if payload is None:
            raise HomeAssistantError(f"Unknown entity: {entity_uid}")

        request = {
            "serial": payload.get("serial"),
            "entityId": payload.get("entity_id"),
            "deviceInstanceId": payload.get("device_instance_id"),
            "command": command,
            "value": value,
        }
        try:
            response = await self.client.async_execute_command(request)
        except OshHomeAuthError as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError("Reauthentication required") from err
        except ClientResponseError as err:
            _LOGGER.warning(
                "Command request failed: status=%s serial=%s entity=%s command=%s",
                err.status,
                payload.get("serial"),
                payload.get("entity_id"),
                command,
            )
            if err.status == 504:
                raise HomeAssistantError(
                    "OSH backend timeout while executing command. Try again."
                ) from err
            raise HomeAssistantError(
                f"OSH backend rejected command (HTTP {err.status})."
            ) from err
        except (ClientError, TimeoutError) as err:
            _LOGGER.warning(
                "Command transport error: serial=%s entity=%s command=%s error=%s",
                payload.get("serial"),
                payload.get("entity_id"),
                command,
                err,
            )
            raise HomeAssistantError(
                "Cannot reach OSH backend while executing command."
            ) from err
        if response.get("status") not in {"accepted", "ok"}:
            raise HomeAssistantError(
                f"Command rejected: {response.get('errorCode') or response.get('errorMessage') or 'unknown'}"
            )
        self.cursor = max(self.cursor, int(response.get("cursor", self.cursor)))
        changed = self._apply_updated_states(response.get("updatedStates"))
        if changed:
            self.async_set_updated_data(self._snapshot())
        return response

    async def _async_refresh_bootstrap(self) -> dict[str, Any]:
        """Refresh bootstrap from the backend."""
        bootstrap = await self.client.async_get_bootstrap()
        self._apply_bootstrap(bootstrap)
        return self._snapshot()

    async def _async_stream_loop(self) -> None:
        """Consume websocket stream and recover with states replay."""
        backoff_seconds = 1
        while True:
            try:
                await self._async_replay_since_cursor()
                backoff_seconds = 1
                async for message in self.client.async_stream(self._installation_id, self.cursor):
                    await self._async_handle_stream_message(message)
                raise ConnectionError("WebSocket stream closed")
            except asyncio.CancelledError:
                raise
            except OshHomeAuthError:
                _LOGGER.warning("OAuth token rejected by backend, starting reauth flow")
                self.entry.async_start_reauth(self.hass)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("OSHHome websocket loop failed (%s), retrying in %ss", err, backoff_seconds)
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 60)

    async def _async_replay_since_cursor(self) -> None:
        """Replay state deltas before (re)connecting websocket."""
        response = await self.client.async_get_states(self.cursor)
        if response.get("reset_required"):
            await self.async_request_refresh()
            return
        self._apply_states_payload(response)
        self.async_set_updated_data(self._snapshot())

    async def _async_handle_stream_message(self, message: dict[str, Any]) -> None:
        """Process one websocket payload."""
        msg_type = message.get("type")
        if msg_type == "entity_delta":
            self._apply_delta(message)
            self.async_set_updated_data(self._snapshot())
            return
        if msg_type == "inventory_changed":
            await self.async_request_refresh()
            return
        if msg_type in {"ready", "pong"}:
            return
        if msg_type == "error":
            _LOGGER.warning(
                "Received websocket error from backend: %s (%s)",
                message.get("code"),
                message.get("message"),
            )
            return
        _LOGGER.debug("Ignoring unsupported websocket payload: %s", message)

    def _apply_bootstrap(self, bootstrap: dict[str, Any]) -> None:
        """Replace device/entity descriptors from bootstrap payload."""
        old_platform_map = self._platform_entity_map()
        old_entity_ids = set(self._entity_payloads)
        incoming_entities = bootstrap.get("entities", [])

        self.cursor = max(self.cursor, int(bootstrap.get("cursor", 0)))
        self._device_payloads = {
            str(device["device_uid"]): device for device in bootstrap.get("devices", [])
        }

        next_entities: dict[str, dict[str, Any]] = {}
        next_runtime: dict[str, dict[str, Any]] = {}
        skipped_unsupported = 0
        for entity in incoming_entities:
            platform = entity.get("platform")
            if platform not in PLATFORMS:
                _LOGGER.debug("Skipping unsupported platform '%s' for entity %s", platform, entity)
                skipped_unsupported += 1
                continue
            entity_uid = str(entity["entity_uid"])
            next_entities[entity_uid] = entity
            next_runtime[entity_uid] = {
                ATTR_STATE: entity.get("state", {}),
                ATTR_ATTRIBUTES: entity.get("attributes", {}),
                ATTR_CURSOR: int(entity.get("cursor", self.cursor)),
                ATTR_DELETED: bool(entity.get("deleted", False)),
            }

        self._entity_payloads = next_entities
        self._entity_runtime = next_runtime

        new_platform_map = self._platform_entity_map()
        new_entity_ids = set(self._entity_payloads)
        removed_ids = old_entity_ids - new_entity_ids
        for entity_uid in removed_ids:
            self._entity_runtime.pop(entity_uid, None)

        _LOGGER.info(
            "Applied bootstrap: devices=%s entities_in=%s entities_active=%s skipped_unsupported=%s per_platform=%s cursor=%s",
            len(self._device_payloads),
            len(incoming_entities) if isinstance(incoming_entities, list) else 0,
            len(self._entity_payloads),
            skipped_unsupported,
            self._platform_counts(self._entity_payloads),
            self.cursor,
        )
        self._notify_inventory_changes(old_platform_map, new_platform_map)

    def _apply_states_payload(self, payload: dict[str, Any]) -> None:
        """Apply `/states` response payload."""
        self.cursor = max(self.cursor, int(payload.get("cursor", self.cursor)))
        for item in payload.get("items", []):
            self._apply_delta(item)

    def _apply_updated_states(self, updated_states: Any) -> bool:
        """Apply command response deltas without a forced bootstrap refresh."""
        if not isinstance(updated_states, list):
            return False
        changed = False
        for item in updated_states:
            if not isinstance(item, dict):
                continue
            self._apply_delta(item)
            changed = True
        return changed

    def _apply_delta(self, payload: dict[str, Any]) -> None:
        """Apply one delta payload to runtime state."""
        entity_uid = payload.get("entity_uid")
        if not isinstance(entity_uid, str):
            return
        if entity_uid not in self._entity_payloads:
            _LOGGER.debug("Ignoring delta for unknown entity_uid=%s", entity_uid)
            return
        runtime = self._entity_runtime.setdefault(
            entity_uid,
            {
                ATTR_STATE: {},
                ATTR_ATTRIBUTES: {},
                ATTR_CURSOR: self.cursor,
                ATTR_DELETED: False,
            },
        )
        runtime[ATTR_STATE] = payload.get("state", runtime.get(ATTR_STATE, {}))
        runtime[ATTR_ATTRIBUTES] = payload.get("attributes", runtime.get(ATTR_ATTRIBUTES, {}))
        runtime[ATTR_CURSOR] = int(payload.get("cursor", runtime.get(ATTR_CURSOR, self.cursor)))
        runtime[ATTR_DELETED] = bool(payload.get("deleted", False))
        self.cursor = max(self.cursor, int(runtime[ATTR_CURSOR]))

    def _snapshot(self) -> dict[str, Any]:
        """Build coordinator data snapshot."""
        return {
            "cursor": self.cursor,
            "devices": self._device_payloads,
            "entities": self._entity_payloads,
            "runtime": self._entity_runtime,
        }

    def _platform_entity_map(self) -> dict[str, set[str]]:
        """Collect entity ids per platform."""
        result: dict[str, set[str]] = {platform: set() for platform in PLATFORMS}
        for entity_uid, entity in self._entity_payloads.items():
            platform = entity.get("platform")
            if platform in result:
                result[platform].add(entity_uid)
        return result

    def _notify_inventory_changes(
        self,
        old_platform_map: dict[str, set[str]],
        new_platform_map: dict[str, set[str]],
    ) -> None:
        """Notify platform listeners about added/removed entities."""
        for platform in PLATFORMS:
            old_set = old_platform_map.get(platform, set())
            new_set = new_platform_map.get(platform, set())
            added = new_set - old_set
            removed = old_set - new_set
            if not added and not removed:
                continue
            for callback in list(self._inventory_listeners.get(platform, [])):
                callback(added, removed)

    def _platform_counts(self, entities: Any) -> dict[str, int]:
        """Count entities by platform for diagnostics."""
        counts: dict[str, int] = {platform: 0 for platform in PLATFORMS}
        if isinstance(entities, dict):
            items = entities.values()
        elif isinstance(entities, (list, tuple, set)):
            items = entities
        else:
            return counts
        for entity in items:
            if not isinstance(entity, dict):
                continue
            platform = entity.get("platform")
            if isinstance(platform, str) and platform in counts:
                counts[platform] += 1
        return counts
