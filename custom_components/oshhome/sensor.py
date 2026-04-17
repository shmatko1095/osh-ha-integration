"""Sensor platform for OSHHome."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OshHomeCoordinator
from .entity import OshHomeBaseEntity, OshHomeEntityManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OSHHome sensor entities."""
    coordinator: OshHomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    manager = OshHomeEntityManager(
        coordinator,
        "sensor",
        async_add_entities,
        lambda entity_uid: OshHomeSensorEntity(coordinator, entity_uid),
    )
    await manager.async_setup()
    entry.async_on_unload(manager.async_unload)


class OshHomeSensorEntity(OshHomeBaseEntity, SensorEntity):
    """Projected sensor entity."""

    @property
    def native_value(self) -> Any:
        value = self.state_value("value")
        if value is not None:
            return value
        state = self.runtime.get("state", {})
        if isinstance(state, dict) and len(state) == 1:
            return next(iter(state.values()))
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        unit = self.descriptor.get("unit")
        return unit if isinstance(unit, str) else None

    @property
    def device_class(self) -> SensorDeviceClass | str | None:
        return _as_enum(self.descriptor.get("device_class"), SensorDeviceClass)

    @property
    def state_class(self) -> SensorStateClass | None:
        return _as_enum(self.descriptor.get("state_class"), SensorStateClass)


def _as_enum(value: Any, enum_cls: Any) -> Any:
    if not isinstance(value, str):
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return value
