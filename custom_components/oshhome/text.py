"""Text platform for OSHHome."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.text import TextEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OshHomeCoordinator
from .entity import OshHomeBaseEntity, OshHomeEntityManager, command_names


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OSHHome text entities."""
    coordinator: OshHomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    manager = OshHomeEntityManager(
        coordinator,
        "text",
        async_add_entities,
        lambda entity_uid: OshHomeTextEntity(coordinator, entity_uid),
    )
    await manager.async_setup()
    entry.async_on_unload(manager.async_unload)


class OshHomeTextEntity(OshHomeBaseEntity, TextEntity):
    """Projected text entity."""

    @property
    def native_value(self) -> str | None:
        value = self.state_value("value")
        return value if isinstance(value, str) else None

    @property
    def native_min(self) -> int:
        return _as_int(self.descriptor.get("options", {}).get("min_length"), 0)

    @property
    def native_max(self) -> int:
        return _as_int(self.descriptor.get("options", {}).get("max_length"), 255)

    async def async_set_value(self, value: str) -> None:
        if "set_value" not in command_names(self.descriptor):
            raise ValueError("Command set_value is not declared for this entity")
        await self.async_send_command("set_value", value)


def _as_int(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    return default
