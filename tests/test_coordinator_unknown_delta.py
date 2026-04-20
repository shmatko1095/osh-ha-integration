"""Unit tests for unknown delta handling in OshHomeCoordinator."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from typing import Any


def _install_homeassistant_stubs() -> None:
    if "homeassistant" in sys.modules:
        return

    aiohttp = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ClientResponseError(ClientError):
        def __init__(self, *_args, status: int = 500, **_kwargs) -> None:
            super().__init__()
            self.status = status

    class WSServerHandshakeError(ClientResponseError):
        pass

    class ClientSession:  # noqa: D401 - test stub
        """Client session stub."""

    class _WSMsgType:
        TEXT = 1
        CLOSE = 2
        CLOSED = 3
        ERROR = 4

    aiohttp.ClientError = ClientError
    aiohttp.ClientResponseError = ClientResponseError
    aiohttp.WSServerHandshakeError = WSServerHandshakeError
    aiohttp.ClientSession = ClientSession
    aiohttp.WSMsgType = _WSMsgType
    sys.modules["aiohttp"] = aiohttp

    homeassistant = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = homeassistant

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:  # noqa: D401 - test stub
        """ConfigEntry stub."""

    config_entries.ConfigEntry = ConfigEntry
    sys.modules["homeassistant.config_entries"] = config_entries

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:  # noqa: D401 - test stub
        """HomeAssistant stub."""

    core.HomeAssistant = HomeAssistant
    sys.modules["homeassistant.core"] = core

    exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    class ConfigEntryAuthFailed(HomeAssistantError):
        pass

    class ConfigEntryNotReady(HomeAssistantError):
        pass

    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    sys.modules["homeassistant.exceptions"] = exceptions

    const = types.ModuleType("homeassistant.const")
    const.CONF_ACCESS_TOKEN = "access_token"
    sys.modules["homeassistant.const"] = const

    helpers = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers

    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    class RegistryEntry:
        def __init__(
            self,
            entity_id: str,
            unique_id: str | None,
            platform: str,
            config_entry_id: str,
        ) -> None:
            self.entity_id = entity_id
            self.unique_id = unique_id
            self.platform = platform
            self.config_entry_id = config_entry_id

    class EntityRegistry:
        def __init__(self, entries: list[RegistryEntry]) -> None:
            self.entities = {entry.entity_id: entry for entry in entries}
            self.removed: list[str] = []

        def async_remove(self, entity_id: str) -> None:
            self.removed.append(entity_id)
            self.entities.pop(entity_id, None)

    def async_get(hass: Any) -> EntityRegistry:
        return hass.entity_registry

    def async_entries_for_config_entry(
        registry: EntityRegistry, config_entry_id: str
    ) -> list[RegistryEntry]:
        return [
            entry
            for entry in registry.entities.values()
            if entry.config_entry_id == config_entry_id
        ]

    entity_registry.RegistryEntry = RegistryEntry
    entity_registry.EntityRegistry = EntityRegistry
    entity_registry.async_get = async_get
    entity_registry.async_entries_for_config_entry = async_entries_for_config_entry
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry
    helpers.entity_registry = entity_registry

    device_registry = types.ModuleType("homeassistant.helpers.device_registry")

    class DeviceEntry:
        def __init__(
            self,
            device_id: str,
            identifiers: set[tuple[str, str]],
            config_entries: set[str],
        ) -> None:
            self.id = device_id
            self.identifiers = identifiers
            self.config_entries = config_entries

    class DeviceRegistry:
        def __init__(self, entries: list[DeviceEntry]) -> None:
            self.devices = {entry.id: entry for entry in entries}
            self.removed: list[str] = []

        def async_remove_device(self, device_id: str) -> None:
            self.removed.append(device_id)
            self.devices.pop(device_id, None)

    def async_get_device_registry(hass: Any) -> DeviceRegistry:
        return hass.device_registry

    def async_entries_for_config_entry_device(
        registry: DeviceRegistry, config_entry_id: str
    ) -> list[DeviceEntry]:
        return [
            entry
            for entry in registry.devices.values()
            if config_entry_id in entry.config_entries
        ]

    device_registry.DeviceEntry = DeviceEntry
    device_registry.DeviceRegistry = DeviceRegistry
    device_registry.async_get = async_get_device_registry
    device_registry.async_entries_for_config_entry = async_entries_for_config_entry_device
    sys.modules["homeassistant.helpers.device_registry"] = device_registry
    helpers.device_registry = device_registry

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")

    def async_get_clientsession(_: Any) -> object:
        return object()

    aiohttp_client.async_get_clientsession = async_get_clientsession
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, *_args, **_kwargs) -> None:
            self.data = None

        async def async_request_refresh(self) -> None:
            return None

        async def async_config_entry_first_refresh(self) -> None:
            return None

        def async_set_updated_data(self, data: Any) -> None:
            self.data = data

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    config_entry_oauth2_flow = types.ModuleType("homeassistant.helpers.config_entry_oauth2_flow")

    class ImplementationUnavailableError(Exception):
        pass

    class LocalOAuth2ImplementationWithPkce:  # noqa: D401 - test stub
        """OAuth impl stub."""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class OAuth2Session:  # noqa: D401 - test stub
        """OAuth2 session stub."""

        def __init__(self, *_args, **_kwargs) -> None:
            self.token = {"access_token": "token"}

        async def async_ensure_token_valid(self) -> None:
            return None

    async def async_get_config_entry_implementation(*_args, **_kwargs) -> object:
        return object()

    def async_register_implementation(*_args, **_kwargs) -> None:
        return None

    config_entry_oauth2_flow.ImplementationUnavailableError = ImplementationUnavailableError
    config_entry_oauth2_flow.LocalOAuth2ImplementationWithPkce = LocalOAuth2ImplementationWithPkce
    config_entry_oauth2_flow.OAuth2Session = OAuth2Session
    config_entry_oauth2_flow.async_get_config_entry_implementation = async_get_config_entry_implementation
    config_entry_oauth2_flow.async_register_implementation = async_register_implementation
    sys.modules["homeassistant.helpers.config_entry_oauth2_flow"] = config_entry_oauth2_flow
    helpers.config_entry_oauth2_flow = config_entry_oauth2_flow


class _FakeHass:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[None]] = []
        self.entity_registry = sys.modules[
            "homeassistant.helpers.entity_registry"
        ].EntityRegistry([])
        self.device_registry = sys.modules[
            "homeassistant.helpers.device_registry"
        ].DeviceRegistry([])

    def async_create_task(self, coro) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task


_install_homeassistant_stubs()
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.oshhome.coordinator import OshHomeCoordinator  # noqa: E402


class CoordinatorUnknownDeltaTest(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_delta_advances_cursor_and_coalesces_refresh(self) -> None:
        coordinator = OshHomeCoordinator.__new__(OshHomeCoordinator)
        coordinator.cursor = 10
        coordinator._entity_payloads = {"known_uid": {"platform": "sensor"}}
        coordinator._entity_runtime = {}
        coordinator._refresh_task = None
        coordinator.hass = _FakeHass()
        coordinator.entry = object()

        refresh_calls = 0

        async def _fake_refresh() -> None:
            nonlocal refresh_calls
            refresh_calls += 1
            await asyncio.sleep(0)

        coordinator.async_request_refresh = _fake_refresh  # type: ignore[method-assign]

        changed, needs_refresh = coordinator._apply_delta(
            {
                "type": "entity_delta",
                "entity_uid": "unknown_uid",
                "cursor": 15,
                "state": {"value": 1},
            }
        )
        self.assertFalse(changed)
        self.assertTrue(needs_refresh)
        self.assertEqual(coordinator.cursor, 15)

        coordinator._schedule_coalesced_refresh("unknown_entity")
        coordinator._schedule_coalesced_refresh("unknown_entity")
        await asyncio.gather(*coordinator.hass.tasks)
        self.assertEqual(refresh_calls, 1)

    def test_known_delta_updates_runtime(self) -> None:
        coordinator = OshHomeCoordinator.__new__(OshHomeCoordinator)
        coordinator.cursor = 1
        coordinator._entity_payloads = {"known_uid": {"platform": "sensor"}}
        coordinator._entity_runtime = {}
        coordinator._refresh_task = None

        changed, needs_refresh = coordinator._apply_delta(
            {
                "type": "entity_delta",
                "entity_uid": "known_uid",
                "cursor": 3,
                "state": {"value": 22.5},
                "attributes": {"unit": "C"},
                "deleted": False,
            }
        )
        self.assertTrue(changed)
        self.assertFalse(needs_refresh)
        self.assertEqual(coordinator.cursor, 3)
        self.assertEqual(coordinator._entity_runtime["known_uid"]["state"]["value"], 22.5)

    def test_bootstrap_prunes_stale_devices_from_registry(self) -> None:
        coordinator = _make_bootstrap_coordinator()
        registry_mod = sys.modules["homeassistant.helpers.device_registry"]
        coordinator.hass.device_registry = registry_mod.DeviceRegistry(
            [
                registry_mod.DeviceEntry(
                    "device-active",
                    {("oshhome", "SERIAL-1:main")},
                    {"entry-1"},
                ),
                registry_mod.DeviceEntry(
                    "device-stale",
                    {("oshhome", "SERIAL-1:legacy")},
                    {"entry-1"},
                ),
                registry_mod.DeviceEntry(
                    "device-other-config",
                    {("oshhome", "SERIAL-1:legacy")},
                    {"entry-2"},
                ),
                registry_mod.DeviceEntry(
                    "device-other-domain",
                    {("other_domain", "SERIAL-1:legacy")},
                    {"entry-1"},
                ),
            ]
        )

        coordinator._apply_bootstrap(_minimal_bootstrap())

        self.assertEqual(coordinator.hass.device_registry.removed, ["device-stale"])
        self.assertIn("device-active", coordinator.hass.device_registry.devices)
        self.assertIn("device-other-config", coordinator.hass.device_registry.devices)
        self.assertIn("device-other-domain", coordinator.hass.device_registry.devices)

    def test_bootstrap_prune_devices_is_idempotent(self) -> None:
        coordinator = _make_bootstrap_coordinator()
        registry_mod = sys.modules["homeassistant.helpers.device_registry"]
        coordinator.hass.device_registry = registry_mod.DeviceRegistry(
            [
                registry_mod.DeviceEntry(
                    "device-active",
                    {("oshhome", "SERIAL-1:main")},
                    {"entry-1"},
                ),
                registry_mod.DeviceEntry(
                    "device-stale",
                    {("oshhome", "SERIAL-1:legacy")},
                    {"entry-1"},
                ),
            ]
        )

        coordinator._apply_bootstrap(_minimal_bootstrap())
        coordinator._apply_bootstrap(_minimal_bootstrap())

        self.assertEqual(coordinator.hass.device_registry.removed, ["device-stale"])

    def test_bootstrap_prunes_stale_entities_from_registry(self) -> None:
        coordinator = _make_bootstrap_coordinator()
        registry_mod = sys.modules["homeassistant.helpers.entity_registry"]
        coordinator.hass.entity_registry = registry_mod.EntityRegistry(
            [
                registry_mod.RegistryEntry(
                    "number.oshhome_active_brightness",
                    "SERIAL-1:display_active_brightness",
                    "oshhome",
                    "entry-1",
                ),
                registry_mod.RegistryEntry(
                    "climate.oshhome_main",
                    "SERIAL-1:main_climate",
                    "oshhome",
                    "entry-1",
                ),
                registry_mod.RegistryEntry(
                    "sensor.other_platform",
                    "SERIAL-1:display_active_brightness",
                    "other_platform",
                    "entry-1",
                ),
                registry_mod.RegistryEntry(
                    "switch.other_config",
                    "SERIAL-1:display_dim_on_idle",
                    "oshhome",
                    "entry-2",
                ),
                registry_mod.RegistryEntry(
                    "sensor.invalid_unique",
                    None,
                    "oshhome",
                    "entry-1",
                ),
            ]
        )

        with self.assertLogs("custom_components.oshhome.coordinator", level="WARNING") as logs:
            coordinator._apply_bootstrap(_minimal_bootstrap())

        self.assertEqual(
            coordinator.hass.entity_registry.removed,
            ["number.oshhome_active_brightness"],
        )
        self.assertIn("sensor.invalid_unique", coordinator.hass.entity_registry.entities)
        self.assertIn("sensor.other_platform", coordinator.hass.entity_registry.entities)
        self.assertIn("switch.other_config", coordinator.hass.entity_registry.entities)
        self.assertTrue(
            any("invalid unique_id" in message for message in logs.output),
            logs.output,
        )

    def test_bootstrap_prune_is_idempotent(self) -> None:
        coordinator = _make_bootstrap_coordinator()
        registry_mod = sys.modules["homeassistant.helpers.entity_registry"]
        coordinator.hass.entity_registry = registry_mod.EntityRegistry(
            [
                registry_mod.RegistryEntry(
                    "number.oshhome_active_brightness",
                    "SERIAL-1:display_active_brightness",
                    "oshhome",
                    "entry-1",
                ),
                registry_mod.RegistryEntry(
                    "climate.oshhome_main",
                    "SERIAL-1:main_climate",
                    "oshhome",
                    "entry-1",
                ),
            ]
        )

        coordinator._apply_bootstrap(_minimal_bootstrap())
        coordinator._apply_bootstrap(_minimal_bootstrap())

        self.assertEqual(
            coordinator.hass.entity_registry.removed,
            ["number.oshhome_active_brightness"],
        )


def _make_bootstrap_coordinator() -> OshHomeCoordinator:
    coordinator = OshHomeCoordinator.__new__(OshHomeCoordinator)
    coordinator.cursor = 0
    coordinator.hass = _FakeHass()
    coordinator.entry = types.SimpleNamespace(entry_id="entry-1")
    coordinator._device_payloads = {}
    coordinator._entity_payloads = {}
    coordinator._entity_runtime = {}
    coordinator._inventory_listeners = {
        "climate": [],
        "sensor": [],
        "binary_sensor": [],
        "number": [],
        "switch": [],
        "select": [],
        "button": [],
        "text": [],
    }
    coordinator._refresh_task = None
    return coordinator


def _minimal_bootstrap() -> dict[str, Any]:
    return {
        "cursor": 10,
        "devices": [
            {
                "device_uid": "SERIAL-1:main",
                "serial": "SERIAL-1",
                "device_ref": "main",
                "kind": "thermostat",
                "name": "Thermostat",
                "manufacturer": "OSH",
                "model": "T1A-FL-WZE",
                "sw_version": "0.41",
                "hw_version": "T1A",
                "primary": True,
            }
        ],
        "entities": [
            {
                "entity_uid": "SERIAL-1:main_climate",
                "platform": "climate",
                "state": {},
                "attributes": {},
                "cursor": 10,
                "deleted": False,
            },
            {
                "entity_uid": "SERIAL-1:climate_sensor_temperature",
                "platform": "sensor",
                "state": {},
                "attributes": {},
                "cursor": 10,
                "deleted": False,
            },
            {
                "entity_uid": "SERIAL-1:climate_sensor_humidity",
                "platform": "sensor",
                "state": {},
                "attributes": {},
                "cursor": 10,
                "deleted": False,
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
