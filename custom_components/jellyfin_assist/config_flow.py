"""UI configuration flow for Jellyfin Media Assistant."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    JellyfinApiClient,
    JellyfinAuthenticationError,
    JellyfinConnectionError,
    JellyfinConnectionInfo,
    JellyfinInvalidResponseError,
)
from .configuration import (
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    JellyfinBehaviorSettings,
    JellyfinConnectionSettings,
)
from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_MEDIA_PLAYER,
    CONF_PLAYBACK_TARGETS,
    CONF_SERVER_URL,
    CONF_USER_ID,
    CONF_USER_PASSWORD,
    CONF_USER_TOKEN,
    CONF_VERIFY_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERVER_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL, autocomplete="url")
        ),
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD,
                autocomplete="current-password",
            )
        ),
        vol.Required(CONF_USER_ID): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Optional(CONF_USER_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD,
                autocomplete="current-password",
            )
        ),
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): BooleanSelector(),
    }
)


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DEFAULT_MEDIA_PLAYER): EntitySelector(
            EntitySelectorConfig(domain="media_player", multiple=False)
        ),
        vol.Optional(CONF_PLAYBACK_TARGETS): EntitySelector(
            EntitySelectorConfig(domain="media_player", multiple=True)
        ),
    }
)


async def async_validate_input(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> tuple[dict[str, Any], JellyfinConnectionInfo]:
    """Normalize input, validate the server, and mint a user access token.

    When a user password is supplied, a user-bound access token is minted via
    the existing ``async_get_user_access_token`` and stored as
    ``CONF_USER_TOKEN``. The password itself is never returned in the
    normalized data — only the resulting token is. When no password is
    supplied (existing installations or a blank field), the token is omitted
    and the client falls back to the bare server API key.
    """

    settings = JellyfinConnectionSettings.from_mapping(data)
    normalized = settings.as_dict()

    client = JellyfinApiClient(
        session=async_get_clientsession(hass),
        server_url=settings.server_url,
        api_key=settings.api_key,
        verify_ssl=settings.verify_ssl,
        user_id=settings.user_id,
        user_token=settings.user_token,
    )
    info = await client.async_validate_connection(settings.user_id)
    normalized[CONF_USER_ID] = info.user_id

    password = str(data.get(CONF_USER_PASSWORD) or "").strip()
    if password:
        token = await client.async_get_user_access_token(
            info.user_id, password, user_name=info.user_name
        )
        normalized[CONF_USER_TOKEN] = token

    return normalized, info


class JellyfinAssistConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Jellyfin Media Assistant configuration."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    @classmethod
    @callback
    def async_supports_options_flow(
        cls,
        config_entry: config_entries.ConfigEntry,
    ) -> bool:
        """Explicitly advertise options support to Home Assistant."""

        return True

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the optional behavior-settings flow."""

        return JellyfinAssistOptionsFlow()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect and validate one Jellyfin connection."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                normalized, info = await async_validate_input(self.hass, user_input)
            except JellyfinAuthenticationError:
                _LOGGER.debug(
                    "Jellyfin Media Assistant install rejected: credentials rejected"
                )
                errors["base"] = "invalid_auth"
            except JellyfinConnectionError:
                _LOGGER.debug(
                    "Jellyfin Media Assistant install rejected: server unreachable"
                )
                errors["base"] = "cannot_connect"
            except (JellyfinInvalidResponseError, ValueError, TypeError):
                errors["base"] = "invalid_configuration"
            except Exception:  # pragma: no cover - defensive HA boundary
                _LOGGER.exception("Unexpected Jellyfin Media Assistant config-flow error")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info.unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info.server_name,
                    data=normalized,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Re-authenticate: prompt for the password to mint a fresh token.

        Triggered when a stored user access token is rejected (401) during a
        playback-position write. Prompts for the Jellyfin user password,
        mints a new user access token, and updates the config entry with only
        the token. The password is never persisted.
        """

        errors: dict[str, str] = {}
        if entry_data is not None:
            password = str(entry_data.get(CONF_USER_PASSWORD) or "")
            try:
                token = await async_get_user_access_token_for_reauth(
                    self.hass, dict(self.config_entry.data), password
                )
            except JellyfinAuthenticationError:
                errors["base"] = "invalid_auth"
            except (JellyfinConnectionError, JellyfinInvalidResponseError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_configuration"
            else:
                data = dict(self.config_entry.data)
                data[CONF_USER_TOKEN] = token
                self.config_entry.async_update_entry(data=data)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USER_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
                }
            ),
            errors=errors,
        )


async def async_get_user_access_token_for_reauth(
    hass: HomeAssistant, data: dict[str, Any], password: str
) -> str:
    """Mint a fresh user access token from the supplied password.

    The reachability/user validation is run with ``user_token=""`` so the
    client falls back to the server API key (always valid for reads). The
    stored token was the one just rejected with a 401, so validating with it
    would fail again before the mint could run. The mint itself authenticates
    with the server API key and the password, returning the replacement token.
    """

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    settings = JellyfinConnectionSettings.from_mapping(data)
    if not password.strip():
        raise ValueError(f"{CONF_USER_PASSWORD} must not be empty")
    client = JellyfinApiClient(
        session=async_get_clientsession(hass),
        server_url=settings.server_url,
        api_key=settings.api_key,
        verify_ssl=settings.verify_ssl,
        user_id=settings.user_id,
        # Empty token -> the validator uses the server API-key fallback and
        # does NOT present the stale, just-rejected user token. The mint below
        # authenticates via the API key + password and mints the fresh token.
        user_token="",
    )
    info = await client.async_validate_connection(settings.user_id)
    return await client.async_get_user_access_token(
        info.user_id, password, user_name=info.user_name
    )


class JellyfinAssistOptionsFlow(config_entries.OptionsFlowWithReload):
    """Manage optional media-assistant behavior."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Configure an optional default playback target."""

        errors: dict[str, str] = {}
        if user_input is not None:
            normalized = JellyfinBehaviorSettings.from_mappings(
                user_input
            ).as_options()
            return self.async_create_entry(data=normalized)

        suggested = JellyfinBehaviorSettings.from_mappings(
            self.config_entry.options,
            legacy_data=self.config_entry.data,
        ).as_options()
        suggested.setdefault(CONF_PLAYBACK_TARGETS, [])
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA,
                suggested,
            ),
            errors=errors,
        )


__all__ = [
    "JellyfinAssistConfigFlow",
    "JellyfinAssistOptionsFlow",
    "OPTIONS_SCHEMA",
    "STEP_USER_SCHEMA",
    "async_get_user_access_token_for_reauth",
    "async_validate_input",
]
