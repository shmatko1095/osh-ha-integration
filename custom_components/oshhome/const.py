"""Constants for the OSHHome integration."""

from __future__ import annotations

DOMAIN = "oshhome"
PLATFORMS = [
    "climate",
    "sensor",
    "binary_sensor",
    "number",
    "switch",
    "select",
    "button",
    "text",
]

CONF_ACCOUNT_ID = "account_id"
CONF_API_BASE_URL = "api_base_url"
CONF_INSTALLATION_ID = "installation_id"
CONF_AUTH_IMPLEMENTATION = "auth_implementation"
CONF_TOKEN = "token"

DEFAULT_API_BASE_URL = "https://api.oshhome.com"
# DEFAULT_API_BASE_URL = "http://localhost:18080"
DEFAULT_REST_TIMEOUT = 15

OAUTH_CLIENT_ID = "osh-home-assistant"
OAUTH_SCOPE = "openid profile email offline_access"
OAUTH_AUTHORIZE_URL = "https://auth.oshhome.com/realms/users-dev/protocol/openid-connect/auth"
OAUTH_TOKEN_URL = "https://auth.oshhome.com/realms/users-dev/protocol/openid-connect/token"

ATTR_STATE = "state"
ATTR_ATTRIBUTES = "attributes"
ATTR_CURSOR = "cursor"
ATTR_DELETED = "deleted"
