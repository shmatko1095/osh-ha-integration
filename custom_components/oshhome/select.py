"""Select platform for OSHHome."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OshHomeCoordinator
from .entity import OshHomeBaseEntity, OshHomeEntityManager, command_names


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OSHHome select entities."""
    coordinator: OshHomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    manager = OshHomeEntityManager(
        coordinator,
        "select",
        async_add_entities,
        lambda entity_uid: OshHomeSelectEntity(coordinator, entity_uid),
    )
    await manager.async_setup()
    entry.async_on_unload(manager.async_unload)


class OshHomeSelectEntity(OshHomeBaseEntity, SelectEntity):
    """Projected select entity."""

    _attr_icon = "mdi:format-list-bulleted-square"

    @property
    def current_option(self) -> str | None:
        value = self.state_value("value", self.state_value("option"))
        return value if isinstance(value, str) else None

    @property
    def options(self) -> list[str]:
        raw = self.descriptor.get("options", {}).get("options", [])
        if not isinstance(raw, list):
            return []
        return [value for value in raw if isinstance(value, str)]

    async def async_select_option(self, option: str) -> None:
        if "select_option" not in command_names(self.descriptor):
            raise ValueError("Command select_option is not declared for this entity")
        await self.async_send_command("select_option", option)
