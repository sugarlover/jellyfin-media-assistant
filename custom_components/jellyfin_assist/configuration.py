"""Public configuration schema and compatibility helpers.

The integration owns two persisted configuration surfaces:

* config-entry data for Jellyfin connection and identity values; and
* config-entry options for user-selectable playback behavior.

This module is deliberately independent of Home Assistant flow objects so the
same normalization rules are used by setup, options, migrations, diagnostics,
and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping
from urllib.parse import urlparse

from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_MEDIA_PLAYER,
    CONF_PLAYBACK_TARGETS,
    CONF_QUEUE_SERVICE_URL,
    CONF_SERVER_URL,
    CONF_USER_ID,
    CONF_VERIFY_SSL,
    DEFAULT_VERIFY_SSL,
)

CONFIG_ENTRY_VERSION: Final = 1
CONFIG_ENTRY_MINOR_VERSION: Final = 3

CONNECTION_DATA_KEYS: Final = frozenset(
    {
        CONF_SERVER_URL,
        CONF_API_KEY,
        CONF_USER_ID,
        CONF_VERIFY_SSL,
    }
)
BEHAVIOR_OPTION_KEYS: Final = frozenset(
    {
        CONF_DEFAULT_MEDIA_PLAYER,
        CONF_PLAYBACK_TARGETS,
    }
)
LEGACY_RETIRED_OPTION_KEYS: Final = frozenset({CONF_QUEUE_SERVICE_URL})


def normalize_server_url(value: str) -> str:
    """Validate and normalize a complete Jellyfin HTTP(S) base URL."""

    if not isinstance(value, str):
        raise ValueError("Jellyfin server URL must be a string")
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "Jellyfin server URL must be a complete http:// or https:// URL"
        )
    if parsed.username or parsed.password:
        raise ValueError("Jellyfin server URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Jellyfin server URL must not contain a query or fragment")
    return normalized


def _clean_required_text(value: Any, *, field: str) -> str:
    """Return one required, stripped text field."""

    if value is None:
        raise ValueError(f"{field} must not be empty")
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    return cleaned


def normalize_playback_targets(value: Any) -> tuple[str, ...]:
    """Normalize selector output and tolerate one legacy scalar value."""

    values = [value] if isinstance(value, str) else (value or [])
    return tuple(
        dict.fromkeys(
            str(entity_id).strip()
            for entity_id in values
            if str(entity_id).strip()
        )
    )


@dataclass(frozen=True, slots=True)
class JellyfinConnectionSettings:
    """Validated connection settings persisted in config-entry data."""

    server_url: str
    api_key: str
    user_id: str
    verify_ssl: bool = DEFAULT_VERIFY_SSL

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "JellyfinConnectionSettings":
        """Build normalized connection settings from persisted or flow data."""

        verify_ssl = data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        if not isinstance(verify_ssl, bool):
            raise ValueError(f"{CONF_VERIFY_SSL} must be a boolean")

        return cls(
            server_url=normalize_server_url(
                _clean_required_text(data.get(CONF_SERVER_URL), field=CONF_SERVER_URL)
            ),
            api_key=_clean_required_text(data.get(CONF_API_KEY), field=CONF_API_KEY),
            user_id=_clean_required_text(data.get(CONF_USER_ID), field=CONF_USER_ID),
            verify_ssl=verify_ssl,
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize the canonical config-entry data shape."""

        return {
            CONF_SERVER_URL: self.server_url,
            CONF_API_KEY: self.api_key,
            CONF_USER_ID: self.user_id,
            CONF_VERIFY_SSL: self.verify_ssl,
        }


@dataclass(frozen=True, slots=True)
class JellyfinBehaviorSettings:
    """Playback behavior persisted in config-entry options."""

    default_media_player: str | None = None
    additional_playback_targets: tuple[str, ...] = ()

    @classmethod
    def from_mappings(
        cls,
        options: Mapping[str, Any] | None,
        *,
        legacy_data: Mapping[str, Any] | None = None,
    ) -> "JellyfinBehaviorSettings":
        """Normalize options with a temporary legacy config-data fallback.

        Explicit option keys always win, including an explicitly blank value.
        Legacy config-entry data is consulted only when an option key is absent.
        """

        option_values = options or {}
        legacy_values = legacy_data or {}

        raw_default = (
            option_values[CONF_DEFAULT_MEDIA_PLAYER]
            if CONF_DEFAULT_MEDIA_PLAYER in option_values
            else legacy_values.get(CONF_DEFAULT_MEDIA_PLAYER, "")
        )
        default_media_player = str(raw_default or "").strip() or None

        raw_targets = (
            option_values[CONF_PLAYBACK_TARGETS]
            if CONF_PLAYBACK_TARGETS in option_values
            else legacy_values.get(CONF_PLAYBACK_TARGETS, [])
        )
        targets = normalize_playback_targets(raw_targets)
        if default_media_player:
            targets = tuple(
                entity_id
                for entity_id in targets
                if entity_id != default_media_player
            )

        return cls(
            default_media_player=default_media_player,
            additional_playback_targets=targets,
        )

    @property
    def effective_playback_targets(self) -> tuple[str, ...]:
        """Return the default plus all additional allowed targets."""

        return tuple(
            dict.fromkeys(
                [
                    *(
                        [self.default_media_player]
                        if self.default_media_player
                        else []
                    ),
                    *self.additional_playback_targets,
                ]
            )
        )

    def as_options(self) -> dict[str, Any]:
        """Serialize the canonical config-entry options shape."""

        result: dict[str, Any] = {}
        if self.default_media_player:
            result[CONF_DEFAULT_MEDIA_PLAYER] = self.default_media_player
        if self.additional_playback_targets:
            result[CONF_PLAYBACK_TARGETS] = list(self.additional_playback_targets)
        return result


def normalize_behavior_options(
    options: Mapping[str, Any] | None,
    *,
    legacy_data: Mapping[str, Any] | None = None,
    preserve_unknown: bool = True,
) -> dict[str, Any]:
    """Return the canonical options mapping while optionally preserving unknowns."""

    original = dict(options or {})
    normalized = JellyfinBehaviorSettings.from_mappings(
        original,
        legacy_data=legacy_data,
    ).as_options()
    if not preserve_unknown:
        return normalized

    unknown = {
        key: value
        for key, value in original.items()
        if key not in BEHAVIOR_OPTION_KEYS and key not in LEGACY_RETIRED_OPTION_KEYS
    }
    return {**unknown, **normalized}


def migrate_config_entry_payload(
    data: Mapping[str, Any],
    options: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Move legacy behavior keys from data to options without losing values.

    Existing options take precedence. Unknown data and option keys are retained
    so a compatibility migration cannot discard configuration owned by a later
    feature or a temporary development build.
    """

    new_data = dict(data)
    original_options = dict(options or {})
    for key in LEGACY_RETIRED_OPTION_KEYS:
        new_data.pop(key, None)
        original_options.pop(key, None)

    legacy_behavior = {
        key: new_data[key]
        for key in BEHAVIOR_OPTION_KEYS
        if key in new_data
    }
    for key in BEHAVIOR_OPTION_KEYS:
        new_data.pop(key, None)

    new_options = normalize_behavior_options(
        original_options,
        legacy_data=legacy_behavior,
        preserve_unknown=True,
    )
    return new_data, new_options


__all__ = [
    "BEHAVIOR_OPTION_KEYS",
    "CONFIG_ENTRY_MINOR_VERSION",
    "CONFIG_ENTRY_VERSION",
    "CONNECTION_DATA_KEYS",
    "LEGACY_RETIRED_OPTION_KEYS",
    "JellyfinBehaviorSettings",
    "JellyfinConnectionSettings",
    "migrate_config_entry_payload",
    "normalize_behavior_options",
    "normalize_playback_targets",
    "normalize_server_url",
]
