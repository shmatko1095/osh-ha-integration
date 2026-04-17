"""Button platform for OSHHome."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OshHomeCoordinator
from .entity import OshHomeBaseEntity, OshHomeEntityManager, command_names


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OSHHome button entities."""
    coordinator: OshHomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    manager = OshHomeEntityManager(
        coordinator,
        "button",
        async_add_entities,
        lambda entity_uid: OshHomeButtonEntity(coordinator, entity_uid),
    )
    await manager.async_setup()
    entry.async_on_unload(manager.async_unload)


class OshHomeButtonEntity(OshHomeBaseEntity, ButtonEntity):
    """Projected button entity."""

    async def async_press(self) -> None:
        if "press" not in command_names(self.descriptor):
            raise ValueError("Command press is not declared for this entity")
        await self.async_send_command("press", None)
