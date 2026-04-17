"""Config flow for OSHHome."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any
from uuid import uuid4

from aiohttp import ClientError, ClientResponseError
import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACCOUNT_ID,
    CONF_API_BASE_URL,
    CONF_AUTH_IMPLEMENTATION,
    CONF_INSTALLATION_ID,
    DEFAULT_API_BASE_URL,
    DOMAIN,
    OAUTH_SCOPE,
)
from .oauth import async_ensure_implementation_registered

_LOGGER = logging.getLogger(__name__)


class OshHomeConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle an OSHHome config flow."""

    DOMAIN = DOMAIN
    VERSION = 1
    MINOR_VERSION = 2

    @property
    def logger(self) -> logging.Logger:
        """Return flow logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Append OAuth2 scope for OSH account permissions."""
        return {"scope": OAUTH_SCOPE}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Start OAuth2 config flow."""
        async_ensure_implementation_registered(self.hass)
        return await super().async_step_user(user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Perform reauth when tokens are invalidated."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauth and restart OAuth2 login."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({}))
        reauth_entry = self._get_reauth_entry()
        async_ensure_implementation_registered(self.hass)
        implementation = reauth_entry.data.get(CONF_AUTH_IMPLEMENTATION, DOMAIN)
        return await self.async_step_pick_implementation(user_input={"implementation": implementation})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow user to refresh the installation id and reconnect stream."""
        if user_input is None:
            return self.async_show_form(step_id="reconfigure", data_schema=vol.Schema({}))
        entry = self._get_reconfigure_entry()
        data_updates = {
            **entry.data,
            CONF_INSTALLATION_ID: str(uuid4()),
        }
        return self.async_update_reload_and_abort(
            entry,
            data_updates=data_updates,
            reason="reconfigure_successful",
        )

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create or update config entry after OAuth callback."""
        try:
            account_id = await self._async_fetch_account_id(data)
        except ClientResponseError as err:
            if err.status in (401, 403):
                return self.async_abort(reason="invalid_auth")
            return self.async_abort(reason="cannot_connect")
        except (ClientError, KeyError, ValueError):
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(account_id)
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="reauth_account_mismatch")
            entry = self._get_reauth_entry()
            return self.async_update_reload_and_abort(
                entry,
                data_updates={
                    **entry.data,
                    **data,
                    CONF_ACCOUNT_ID: account_id,
                    CONF_API_BASE_URL: entry.data.get(CONF_API_BASE_URL, DEFAULT_API_BASE_URL),
                    CONF_INSTALLATION_ID: entry.data.get(CONF_INSTALLATION_ID, str(uuid4())),
                },
            )

        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="OSHHome",
            data={
                **data,
                CONF_ACCOUNT_ID: account_id,
                CONF_API_BASE_URL: DEFAULT_API_BASE_URL,
                CONF_INSTALLATION_ID: str(uuid4()),
            },
        )

    async def _async_fetch_account_id(self, data: dict[str, Any]) -> str:
        """Use bootstrap endpoint as post-auth identity check."""
        token_data = data[CONF_TOKEN]
        access_token = token_data[CONF_ACCESS_TOKEN]
        session = async_get_clientsession(self.hass)
        async with session.get(
            f"{DEFAULT_API_BASE_URL}/v1/ha/bootstrap",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        account_id = payload.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("bootstrap response does not contain account_id")
        return account_id
