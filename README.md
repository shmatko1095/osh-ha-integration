# OSHHome Home Assistant Integration

Custom integration for OSHHome devices via push-first OSH backend API.

## Current Scope
- OAuth2 config flow (Authorization Code + PKCE) against OSH Keycloak
- Bootstrap-driven entity/device materialization
- WebSocket primary updates with REST replay recovery
- Dynamic entity reconciliation on inventory changes
- Command response `updatedStates` is applied locally (no forced full refresh per command)
- Platform entities: climate, sensor, binary_sensor, number, switch, select, button, text

## Current Limitation
- OAuth constants are static (`client_id`, auth/token URLs, API base URL) and may need environment overrides.
- Future `ha-core` submission may require packaging credentials via `application_credentials` or Cloud linking.

## Local Development
1. Mount `custom_components/oshhome` into your Home Assistant container.
2. Ensure your Keycloak OAuth client allows HA callback URLs.
3. Start flow from HA UI and authenticate in OSH login page.
4. Validate websocket updates and fallback replay after reconnect.

## Planned Next Steps
- Add integration tests with Home Assistant pytest harness.
- Prepare packaging adjustments required for ha-core review.
