"""Entity helpers for OSHHome."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.helpers.entity import DeviceInfo, Entity, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_ATTRIBUTES, ATTR_DELETED, ATTR_STATE, DOMAIN
from .coordinator import OshHomeCoordinator

_LOGGER = logging.getLogger(__name__)


class OshHomeBaseEntity(CoordinatorEntity[OshHomeCoordinator], Entity):
    """Base entity backed by coordinator descriptor + runtime state."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: OshHomeCoordinator, entity_uid: str) -> None:
        super().__init__(coordinator)
        self._entity_uid = entity_uid

        descriptor = coordinator.get_entity_payload(entity_uid) or {}
        self._attr_unique_id = entity_uid
        self._attr_name = descriptor.get("name") or descriptor.get("entity_id", entity_uid)
        self._attr_entity_category = _parse_entity_category(descriptor.get("entity_category"))
        self._attr_entity_registry_enabled_default = bool(
            descriptor.get("enabled_by_default", True)
        )
        icon = descriptor.get("icon")
        if isinstance(icon, str) and icon:
            self._attr_icon = icon

    @property
    def descriptor(self) -> dict[str, Any]:
        """Return immutable descriptor payload."""
        return self.coordinator.get_entity_payload(self._entity_uid) or {}

    @property
    def runtime(self) -> dict[str, Any]:
        """Return mutable runtime state payload."""
        return self.coordinator.get_entity_runtime(self._entity_uid)

    @property
    def available(self) -> bool:
        """Entity availability reflects stream runtime and delete markers."""
        return bool(self.descriptor) and not bool(self.runtime.get(ATTR_DELETED, False))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Pass-through projected attributes from backend."""
        attributes = self.runtime.get(ATTR_ATTRIBUTES, {})
        return attributes if isinstance(attributes, dict) else {}

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device registry info."""
        descriptor = self.descriptor
        device_uid = descriptor.get("device_uid")
        if not isinstance(device_uid, str):
            return None
        device = self.coordinator.get_device_payload(device_uid) or {}
        via_device_uid = device.get("via_device_uid")

        return DeviceInfo(
            identifiers={(DOMAIN, device_uid)},
            name=device.get("name"),
            manufacturer=device.get("manufacturer"),
            model=device.get("model") or device.get("kind"),
            sw_version=device.get("sw_version"),
            hw_version=device.get("hw_version"),
            via_device=(DOMAIN, via_device_uid) if via_device_uid else None,
        )

    def state_value(self, key: str, default: Any = None) -> Any:
        """Read one projected value from runtime state."""
        state = self.runtime.get(ATTR_STATE, {})
        if not isinstance(state, dict):
            return default
        return state.get(key, default)

    async def async_send_command(self, command: str, value: Any) -> dict[str, Any]:
        """Send command through backend command API."""
        return await self.coordinator.async_execute_command(self._entity_uid, command, value)


class OshHomeEntityManager:
    """Dynamic platform entity manager."""

    def __init__(
        self,
        coordinator: OshHomeCoordinator,
        platform: str,
        async_add_entities: Callable[[list[Entity]], None],
        factory: Callable[[str], Entity],
    ) -> None:
        self._coordinator = coordinator
        self._platform = platform
        self._async_add_entities = async_add_entities
        self._factory = factory
        self._entities: dict[str, Entity] = {}
        self._unsubscribe: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        """Create initial entities and subscribe for inventory changes."""
        initial_uids = {
            entity["entity_uid"]
            for entity in self._coordinator.entities_for_platform(self._platform)
            if isinstance(entity.get("entity_uid"), str)
        }
        self._add_entities(initial_uids)
        _LOGGER.info(
            "Platform %s setup completed with %s initial entities",
            self._platform,
            len(initial_uids),
        )
        self._unsubscribe = self._coordinator.async_subscribe_inventory(
            self._platform, self._handle_inventory_update
        )

    def async_unload(self) -> None:
        """Unsubscribe and remove runtime entities."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        for entity in list(self._entities.values()):
            entity.async_remove()
        self._entities.clear()

    def _handle_inventory_update(self, added: set[str], removed: set[str]) -> None:
        """Handle added and removed entity descriptors."""
        _LOGGER.debug(
            "Platform %s inventory update added=%s removed=%s",
            self._platform,
            len(added),
            len(removed),
        )
        for entity_uid in removed:
            entity = self._entities.pop(entity_uid, None)
            if entity is not None:
                entity.async_remove()
        self._add_entities(added)

    def _add_entities(self, entity_uids: set[str]) -> None:
        entities_to_add: list[Entity] = []
        for entity_uid in entity_uids:
            if entity_uid in self._entities:
                continue
            entity = self._factory(entity_uid)
            self._entities[entity_uid] = entity
            entities_to_add.append(entity)
        if entities_to_add:
            self._async_add_entities(entities_to_add)
            _LOGGER.debug(
                "Platform %s added %s entities (tracked=%s)",
                self._platform,
                len(entities_to_add),
                len(self._entities),
            )


def command_names(descriptor: dict[str, Any]) -> set[str]:
    """Extract declared command names for one entity."""
    commands = descriptor.get("commands")
    if isinstance(commands, dict):
        return set(commands)
    if isinstance(commands, list):
        return {name for name in commands if isinstance(name, str)}
    return set()


def _parse_entity_category(value: Any) -> EntityCategory | None:
    """Map backend entity_category string to Home Assistant enum."""
    if isinstance(value, EntityCategory):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    try:
        return EntityCategory(normalized)
    except ValueError:
        _LOGGER.warning("Ignoring unsupported entity_category value: %s", value)
        return None
