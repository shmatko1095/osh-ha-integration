"""OAuth helpers for OSHHome."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import (
    ImplementationUnavailableError,
    LocalOAuth2ImplementationWithPkce,
    OAuth2Session,
    async_get_config_entry_implementation,
)

from .const import (
    DOMAIN,
    OAUTH_AUTHORIZE_URL,
    OAUTH_CLIENT_ID,
    OAUTH_TOKEN_URL,
)

_REGISTERED_KEY = "oauth_registered"


def async_ensure_implementation_registered(hass: HomeAssistant) -> None:
    """Register static OAuth implementation once per HA instance."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_REGISTERED_KEY):
        return

    config_entry_oauth2_flow.async_register_implementation(
        hass,
        DOMAIN,
        LocalOAuth2ImplementationWithPkce(
            hass,
            DOMAIN,
            OAUTH_CLIENT_ID,
            authorize_url=OAUTH_AUTHORIZE_URL,
            token_url=OAUTH_TOKEN_URL,
            client_secret="",
            code_verifier_length=128,
        ),
    )
    domain_data[_REGISTERED_KEY] = True

class OshHomeOAuthSession:
    """Wrapper around Home Assistant OAuth2 session."""

    def __init__(self, session: OAuth2Session) -> None:
        self._session = session

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing when needed."""
        await self._session.async_ensure_token_valid()
        token = self._session.token.get(CONF_ACCESS_TOKEN, "")
        if not isinstance(token, str) or not token:
            raise ValueError("OAuth access token is missing")
        return token


async def async_get_oauth_session(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> OshHomeOAuthSession:
    """Build OAuth session for an existing config entry."""
    async_ensure_implementation_registered(hass)
    try:
        implementation = await async_get_config_entry_implementation(hass, entry)
    except ImplementationUnavailableError as err:
        raise RuntimeError("OAuth implementation is temporarily unavailable") from err
    return OshHomeOAuthSession(OAuth2Session(hass, entry, implementation))
