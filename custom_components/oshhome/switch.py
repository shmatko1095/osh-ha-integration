"""Switch platform for OSHHome."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OshHomeCoordinator
from .entity import OshHomeBaseEntity, OshHomeEntityManager, command_names


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OSHHome switch entities."""
    coordinator: OshHomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    manager = OshHomeEntityManager(
        coordinator,
        "switch",
        async_add_entities,
        lambda entity_uid: OshHomeSwitchEntity(coordinator, entity_uid),
    )
    await manager.async_setup()
    entry.async_on_unload(manager.async_unload)


class OshHomeSwitchEntity(OshHomeBaseEntity, SwitchEntity):
    """Projected switch entity."""

    _attr_icon = "mdi:toggle-switch"

    @property
    def is_on(self) -> bool | None:
        value = self.state_value("value", self.state_value("is_on"))
        if isinstance(value, bool):
            return value
        return None

    async def async_turn_on(self, **kwargs) -> None:
        if "turn_on" not in command_names(self.descriptor):
            raise ValueError("Command turn_on is not declared for this entity")
        await self.async_send_command("turn_on", True)

    async def async_turn_off(self, **kwargs) -> None:
        if "turn_off" not in command_names(self.descriptor):
            raise ValueError("Command turn_off is not declared for this entity")
        await self.async_send_command("turn_off", False)
