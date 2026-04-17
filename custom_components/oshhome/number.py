"""Number platform for OSHHome."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OshHomeCoordinator
from .entity import OshHomeBaseEntity, OshHomeEntityManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OSHHome number entities."""
    coordinator: OshHomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    manager = OshHomeEntityManager(
        coordinator,
        "number",
        async_add_entities,
        lambda entity_uid: OshHomeNumberEntity(coordinator, entity_uid),
    )
    await manager.async_setup()
    entry.async_on_unload(manager.async_unload)


class OshHomeNumberEntity(OshHomeBaseEntity, NumberEntity):
    """Projected number entity."""

    _attr_icon = "mdi:numeric"

    @property
    def native_value(self) -> float | None:
        value = self.state_value("value")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    @property
    def native_min_value(self) -> float | None:
        return _as_float(self.descriptor.get("options", {}).get("min"))

    @property
    def native_max_value(self) -> float | None:
        return _as_float(self.descriptor.get("options", {}).get("max"))

    @property
    def native_step(self) -> float | None:
        return _as_float(self.descriptor.get("options", {}).get("step"))

    @property
    def native_unit_of_measurement(self) -> str | None:
        unit = self.descriptor.get("unit")
        return unit if isinstance(unit, str) else None

    @property
    def mode(self) -> NumberMode:
        return NumberMode.AUTO

    async def async_set_native_value(self, value: float) -> None:
        await self.async_send_command("set_value", value)


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
