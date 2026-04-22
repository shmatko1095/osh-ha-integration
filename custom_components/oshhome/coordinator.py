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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import OshHomeApiClient, OshHomeAuthError, OshHomeWebSocketClosed
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
        self._refresh_task: asyncio.Task[None] | None = None

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
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None

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
        changed, needs_refresh = self._apply_updated_states(response.get("updatedStates"))
        if needs_refresh:
            self._schedule_coalesced_refresh("unknown_entity_in_command_response")
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
            except asyncio.CancelledError:
                raise
            except OshHomeAuthError:
                _LOGGER.warning("OAuth token rejected by backend, starting reauth flow")
                self.entry.async_start_reauth(self.hass)
                return
            except OshHomeWebSocketClosed as err:
                close_code = err.close_code
                if close_code in (1000, 1001):
                    _LOGGER.debug(
                        "OSHHome websocket closed gracefully (type=%s code=%s reason=%s), reconnecting in %ss",
                        err.message_type.name,
                        close_code,
                        err.reason or "n/a",
                        backoff_seconds,
                    )
                else:
                    _LOGGER.warning(
                        "OSHHome websocket closed unexpectedly (type=%s code=%s reason=%s), retrying in %ss",
                        err.message_type.name,
                        close_code,
                        err.reason or "n/a",
                        backoff_seconds,
                    )
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 60)
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
        needs_refresh = self._apply_states_payload(response)
        self.async_set_updated_data(self._snapshot())
        if needs_refresh:
            self._schedule_coalesced_refresh("unknown_entity_in_states_replay")

    async def _async_handle_stream_message(self, message: dict[str, Any]) -> None:
        """Process one websocket payload."""
        msg_type = message.get("type")
        if msg_type == "entity_delta":
            changed, needs_refresh = self._apply_delta(message)
            if changed:
                self.async_set_updated_data(self._snapshot())
            if needs_refresh:
                self._schedule_coalesced_refresh("unknown_entity_in_ws_delta")
            return
        if msg_type == "inventory_changed":
            self._schedule_coalesced_refresh("inventory_changed")
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
        self._prune_stale_device_registry_entries()
        self._prune_stale_entity_registry_entries()

    def _apply_states_payload(self, payload: dict[str, Any]) -> bool:
        """Apply `/states` response payload."""
        self.cursor = max(self.cursor, self._safe_int(payload.get("cursor"), self.cursor))
        needs_refresh = False
        for item in payload.get("items", []):
            _, unknown_entity = self._apply_delta(item)
            needs_refresh = needs_refresh or unknown_entity
        return needs_refresh

    def _apply_updated_states(self, updated_states: Any) -> tuple[bool, bool]:
        """Apply command response deltas without a forced bootstrap refresh."""
        if not isinstance(updated_states, list):
            return False, False
        changed = False
        needs_refresh = False
        for item in updated_states:
            if not isinstance(item, dict):
                continue
            applied, unknown_entity = self._apply_delta(item)
            changed = changed or applied
            needs_refresh = needs_refresh or unknown_entity
        return changed, needs_refresh

    def _apply_delta(self, payload: dict[str, Any] | Any) -> tuple[bool, bool]:
        """Apply one delta payload to runtime state."""
        if not isinstance(payload, dict):
            return False, False
        payload_cursor = self._safe_int(payload.get("cursor"), self.cursor)
        self.cursor = max(self.cursor, payload_cursor)

        entity_uid = payload.get("entity_uid")
        if not isinstance(entity_uid, str):
            return False, False
        if entity_uid not in self._entity_payloads:
            _LOGGER.debug(
                "Received delta for unknown entity_uid=%s cursor=%s, scheduling bootstrap refresh",
                entity_uid,
                payload_cursor,
            )
            return False, True
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
        runtime[ATTR_CURSOR] = self._safe_int(
            payload.get("cursor"),
            self._safe_int(runtime.get(ATTR_CURSOR), self.cursor),
        )
        runtime[ATTR_DELETED] = bool(payload.get("deleted", False))
        self.cursor = max(self.cursor, int(runtime[ATTR_CURSOR]))
        return True, False

    def _schedule_coalesced_refresh(self, reason: str) -> None:
        """Ensure only one bootstrap refresh runs at a time."""
        if self._refresh_task is not None:
            if not self._refresh_task.done():
                return
            self._refresh_task = None

        async def _refresh() -> None:
            try:
                await self.async_request_refresh()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Coalesced refresh failed (%s): %s", reason, err)
            finally:
                self._refresh_task = None

        if hasattr(self.entry, "async_create_background_task"):
            self._refresh_task = self.entry.async_create_background_task(
                self.hass,
                _refresh(),
                "oshhome_coalesced_refresh",
            )
        else:
            self._refresh_task = self.hass.async_create_task(_refresh())

    def _safe_int(self, value: Any, fallback: int | None = None) -> int:
        """Convert unknown payload cursor value to int safely."""
        try:
            return int(value)
        except (TypeError, ValueError):
            if fallback is None:
                return self.cursor
            return int(fallback)

    def _prune_stale_entity_registry_entries(self) -> None:
        """Delete stale registry entities that are no longer present in bootstrap."""
        active_entity_uids = set(self._entity_payloads.keys())
        registry = er.async_get(self.hass)
        stale_entity_ids: list[str] = []

        for entry in er.async_entries_for_config_entry(registry, self.entry.entry_id):
            if entry.platform != DOMAIN:
                continue
            unique_id = entry.unique_id
            if not isinstance(unique_id, str) or not unique_id.strip():
                _LOGGER.warning(
                    "Skipping registry prune for entity_id=%s due invalid unique_id=%r",
                    entry.entity_id,
                    unique_id,
                )
                continue
            if unique_id not in active_entity_uids:
                stale_entity_ids.append(entry.entity_id)

        for entity_id in stale_entity_ids:
            registry.async_remove(entity_id)

        if stale_entity_ids:
            _LOGGER.info(
                "Pruned stale OSHHome entities from registry count=%s entities=%s",
                len(stale_entity_ids),
                stale_entity_ids,
            )
        else:
            _LOGGER.debug("No stale OSHHome entities found in registry after bootstrap")

    def _prune_stale_device_registry_entries(self) -> None:
        """Delete stale registry devices that are no longer present in bootstrap."""
        active_device_uids = set(self._device_payloads.keys())
        registry = dr.async_get(self.hass)
        stale_device_ids: list[str] = []

        for entry in dr.async_entries_for_config_entry(registry, self.entry.entry_id):
            identifiers = getattr(entry, "identifiers", set()) or set()
            oshhome_identifiers = {
                identifier[1]
                for identifier in identifiers
                if isinstance(identifier, tuple)
                and len(identifier) == 2
                and identifier[0] == DOMAIN
                and isinstance(identifier[1], str)
                and identifier[1].strip()
            }
            if not oshhome_identifiers:
                continue
            if any(identifier not in active_device_uids for identifier in oshhome_identifiers):
                device_id = getattr(entry, "id", None)
                if isinstance(device_id, str) and device_id:
                    stale_device_ids.append(device_id)

        for device_id in stale_device_ids:
            registry.async_remove_device(device_id)

        if stale_device_ids:
            _LOGGER.info(
                "Pruned stale OSHHome devices from registry count=%s devices=%s",
                len(stale_device_ids),
                stale_device_ids,
            )
        else:
            _LOGGER.debug("No stale OSHHome devices found in registry after bootstrap")

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
