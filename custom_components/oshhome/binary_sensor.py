"""Binary sensor platform for OSHHome."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OshHomeCoordinator
from .entity import OshHomeBaseEntity, OshHomeEntityManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OSHHome binary sensor entities."""
    coordinator: OshHomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    manager = OshHomeEntityManager(
        coordinator,
        "binary_sensor",
        async_add_entities,
        lambda entity_uid: OshHomeBinarySensorEntity(coordinator, entity_uid),
    )
    await manager.async_setup()
    entry.async_on_unload(manager.async_unload)


class OshHomeBinarySensorEntity(OshHomeBaseEntity, BinarySensorEntity):
    """Projected binary sensor."""

    @property
    def is_on(self) -> bool | None:
        value = self.state_value("value", self.state_value("is_on"))
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"true", "on", "1", "yes"}
        if isinstance(value, (int, float)):
            return value != 0
        return None

    @property
    def device_class(self) -> BinarySensorDeviceClass | str | None:
        value = self.descriptor.get("device_class")
        if not isinstance(value, str):
            return None
        try:
            return BinarySensorDeviceClass(value)
        except ValueError:
            return value
