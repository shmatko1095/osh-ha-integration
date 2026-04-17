"""OSHHome integration."""

from __future__ import annotations

from aiohttp import ClientError, ClientResponseError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import OshHomeAuthError
from .const import DOMAIN, PLATFORMS
from .coordinator import OshHomeCoordinator
from .oauth import async_ensure_implementation_registered, async_get_oauth_session


OshHomeConfigEntry = ConfigEntry


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up OSHHome integration."""
    async_ensure_implementation_registered(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OshHomeConfigEntry) -> bool:
    """Set up OSHHome from a config entry."""
    try:
        oauth_session = await async_get_oauth_session(hass, entry)
    except RuntimeError as err:
        raise ConfigEntryNotReady("OAuth implementation unavailable") from err

    coordinator = OshHomeCoordinator(hass, entry, oauth_session)
    try:
        await coordinator.async_initialize()
    except OshHomeAuthError as err:
        raise ConfigEntryAuthFailed("Token is no longer valid") from err
    except ClientResponseError as err:
        if err.status in (401, 403):
            raise ConfigEntryAuthFailed("Token is no longer valid") from err
        raise ConfigEntryNotReady("Cannot reach OSH backend") from err
    except ClientError as err:
        raise ConfigEntryNotReady("Cannot reach OSH backend") from err
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OshHomeConfigEntry) -> bool:
    """Unload an OSHHome config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.async_shutdown()
    return unload_ok
