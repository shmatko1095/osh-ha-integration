"""Climate platform for OSHHome."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OshHomeCoordinator
from .entity import OshHomeBaseEntity, OshHomeEntityManager, command_names

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OSHHome climate entities."""
    coordinator: OshHomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    manager = OshHomeEntityManager(
        coordinator,
        "climate",
        async_add_entities,
        lambda entity_uid: OshHomeClimateEntity(coordinator, entity_uid),
    )
    await manager.async_setup()
    entry.async_on_unload(manager.async_unload)


class OshHomeClimateEntity(OshHomeBaseEntity, ClimateEntity):
    """Projected climate entity."""

    _attr_icon = "mdi:thermostat"

    @property
    def temperature_unit(self) -> str | None:
        return _to_temperature_unit(self.descriptor.get("unit"))

    @property
    def current_temperature(self) -> float | None:
        value = self.state_value("current_temperature")
        return _to_float(value)

    @property
    def target_temperature(self) -> float | None:
        value = self.state_value("target_temperature")
        return _to_float(value)

    @property
    def hvac_mode(self) -> HVACMode | None:
        return _to_hvac_mode(self.state_value("hvac_mode"))

    @property
    def hvac_modes(self) -> list[HVACMode]:
        raw = self.descriptor.get("options", {}).get("hvac_modes", [])
        modes = [_to_hvac_mode(value) for value in raw]
        return [mode for mode in modes if mode is not None]

    @property
    def hvac_action(self) -> HVACAction | None:
        return _to_hvac_action(self.state_value("hvac_action"))

    @property
    def preset_mode(self) -> str | None:
        value = self.state_value("preset_mode")
        return value if isinstance(value, str) else None

    @property
    def preset_modes(self) -> list[str] | None:
        raw = self.descriptor.get("options", {}).get("preset_modes", [])
        if not isinstance(raw, list):
            return None
        return [value for value in raw if isinstance(value, str)]

    @property
    def supported_features(self) -> ClimateEntityFeature:
        commands = command_names(self.descriptor)
        features = ClimateEntityFeature(0)
        if "set_preset_mode" in commands:
            features |= ClimateEntityFeature.PRESET_MODE
        if "set_temperature" in commands:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if "turn_on" in commands:
            features |= ClimateEntityFeature.TURN_ON
        if "turn_off" in commands:
            features |= ClimateEntityFeature.TURN_OFF
        return features

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if "set_hvac_mode" not in command_names(self.descriptor):
            raise ValueError("Command set_hvac_mode is not declared for this entity")
        await self.async_send_command("set_hvac_mode", hvac_mode.value)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if "set_preset_mode" not in command_names(self.descriptor):
            raise ValueError("Command set_preset_mode is not declared for this entity")
        await self.async_send_command("set_preset_mode", preset_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if "set_temperature" not in command_names(self.descriptor):
            raise ValueError("Command set_temperature is not declared for this entity")
        temperature = kwargs.get("temperature")
        if not isinstance(temperature, (int, float)):
            raise ValueError("temperature is required")
        await self.async_send_command("set_temperature", float(temperature))

    async def async_turn_on(self) -> None:
        if "turn_on" not in command_names(self.descriptor):
            raise ValueError("Command turn_on is not declared for this entity")
        await self.async_send_command("turn_on", True)

    async def async_turn_off(self) -> None:
        if "turn_off" not in command_names(self.descriptor):
            raise ValueError("Command turn_off is not declared for this entity")
        await self.async_send_command("turn_off", False)


def _to_hvac_mode(value: Any) -> HVACMode | None:
    if isinstance(value, HVACMode):
        return value
    if not isinstance(value, str):
        return None
    mapping = {
        HVACMode.OFF.value: HVACMode.OFF,
        HVACMode.HEAT.value: HVACMode.HEAT,
        HVACMode.AUTO.value: HVACMode.AUTO,
        HVACMode.COOL.value: HVACMode.COOL,
        HVACMode.HEAT_COOL.value: HVACMode.HEAT_COOL,
    }
    return mapping.get(value)


def _to_hvac_action(value: Any) -> HVACAction | None:
    if isinstance(value, HVACAction):
        return value
    if not isinstance(value, str):
        return None
    mapping = {
        HVACAction.HEATING.value: HVACAction.HEATING,
        HVACAction.COOLING.value: HVACAction.COOLING,
        HVACAction.DRYING.value: HVACAction.DRYING,
        HVACAction.FAN.value: HVACAction.FAN,
        HVACAction.IDLE.value: HVACAction.IDLE,
        HVACAction.OFF.value: HVACAction.OFF,
    }
    return mapping.get(value)


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _to_temperature_unit(value: Any) -> str:
    """Map backend temperature unit to Home Assistant climate unit."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        mapping = {
            "c": UnitOfTemperature.CELSIUS,
            "°c": UnitOfTemperature.CELSIUS,
            "celsius": UnitOfTemperature.CELSIUS,
            "f": UnitOfTemperature.FAHRENHEIT,
            "°f": UnitOfTemperature.FAHRENHEIT,
            "fahrenheit": UnitOfTemperature.FAHRENHEIT,
        }
        if normalized in mapping:
            return mapping[normalized]
        if value in (UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT):
            return value
        if normalized:
            _LOGGER.warning(
                "Unsupported climate temperature unit '%s', defaulting to Celsius",
                value,
            )
    return UnitOfTemperature.CELSIUS
