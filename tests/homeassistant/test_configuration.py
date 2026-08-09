"""Tests for the public configuration schema and compatibility rules."""

from __future__ import annotations

import pytest

from tests.homeassistant.ha_stubs import install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist.configuration import (
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    JellyfinBehaviorSettings,
    JellyfinConnectionSettings,
    migrate_config_entry_payload,
    normalize_behavior_options,
    normalize_playback_targets,
)


def test_connection_settings_normalize_to_canonical_data_shape() -> None:
    settings = JellyfinConnectionSettings.from_mapping(
        {
            "server_url": " https://jellyfin.example:8096/ ",
            "api_key": " secret ",
            "user_id": " USER-1 ",
        }
    )

    assert settings.as_dict() == {
        "server_url": "https://jellyfin.example:8096",
        "api_key": "secret",
        "user_id": "USER-1",
        "verify_ssl": True,
    }


def test_connection_settings_reject_non_boolean_ssl_value() -> None:
    with pytest.raises(ValueError, match="verify_ssl"):
        JellyfinConnectionSettings.from_mapping(
            {
                "server_url": "https://jellyfin.example",
                "api_key": "secret",
                "user_id": "USER-1",
                "verify_ssl": "false",
            }
        )


@pytest.mark.parametrize("field", ["server_url", "api_key", "user_id"])
def test_connection_settings_reject_missing_required_values(field: str) -> None:
    data = {
        "server_url": "https://jellyfin.example",
        "api_key": "secret",
        "user_id": "USER-1",
    }
    data.pop(field)

    with pytest.raises(ValueError, match=field):
        JellyfinConnectionSettings.from_mapping(data)


def test_behavior_settings_store_default_only_once() -> None:
    settings = JellyfinBehaviorSettings.from_mappings(
        {
            "default_media_player": " media_player.example_chromecast ",
            "playback_targets": [
                "media_player.example_chromecast",
                "media_player.example_secondary_chromecast",
                "media_player.example_secondary_chromecast",
            ],
        }
    )

    assert settings.as_options() == {
        "default_media_player": "media_player.example_chromecast",
        "playback_targets": ["media_player.example_secondary_chromecast"],
    }
    assert settings.effective_playback_targets == (
        "media_player.example_chromecast",
        "media_player.example_secondary_chromecast",
    )


def test_migration_retires_legacy_queue_service_url() -> None:
    data, options = migrate_config_entry_payload(
        {
            "server_url": "https://jellyfin.example",
            "api_key": "secret",
            "user_id": "USER-1",
            "queue_service_url": "http://queue.example:8787",
        },
        {"queue_service_url": "http://other-queue.example:8787"},
    )

    assert "queue_service_url" not in data
    assert "queue_service_url" not in options


def test_explicit_blank_option_overrides_legacy_default() -> None:
    settings = JellyfinBehaviorSettings.from_mappings(
        {"default_media_player": ""},
        legacy_data={"default_media_player": "media_player.legacy"},
    )

    assert settings.default_media_player is None
    assert settings.as_options() == {}


def test_scalar_playback_target_compatibility_is_canonicalized() -> None:
    assert normalize_playback_targets(" media_player.example_chromecast ") == (
        "media_player.example_chromecast",
    )
    assert normalize_behavior_options(
        {"playback_targets": "media_player.example_chromecast"}
    ) == {"playback_targets": ["media_player.example_chromecast"]}


def test_migration_moves_legacy_behavior_data_into_options() -> None:
    data, options = migrate_config_entry_payload(
        {
            "server_url": "https://jellyfin.example",
            "api_key": "secret",
            "user_id": "USER-1",
            "default_media_player": "media_player.example_chromecast",
            "playback_targets": "media_player.example_secondary_chromecast",
        },
        {},
    )

    assert data == {
        "server_url": "https://jellyfin.example",
        "api_key": "secret",
        "user_id": "USER-1",
    }
    assert options == {
        "default_media_player": "media_player.example_chromecast",
        "playback_targets": ["media_player.example_secondary_chromecast"],
    }


def test_migration_prefers_existing_options_and_preserves_unknown_keys() -> None:
    data, options = migrate_config_entry_payload(
        {
            "server_url": "https://jellyfin.example",
            "api_key": "secret",
            "user_id": "USER-1",
            "default_media_player": "media_player.legacy",
            "future_data": "keep",
        },
        {
            "default_media_player": "media_player.example_chromecast",
            "future_option": True,
        },
    )

    assert data["future_data"] == "keep"
    assert "default_media_player" not in data
    assert options == {
        "future_option": True,
        "default_media_player": "media_player.example_chromecast",
    }


def test_migration_is_idempotent() -> None:
    initial_data = {
        "server_url": "https://jellyfin.example",
        "api_key": "secret",
        "user_id": "USER-1",
    }
    initial_options = {
        "default_media_player": "media_player.example_chromecast",
        "playback_targets": ["media_player.example_secondary_chromecast"],
    }

    first = migrate_config_entry_payload(initial_data, initial_options)
    second = migrate_config_entry_payload(*first)

    assert first == second
    assert (CONFIG_ENTRY_VERSION, CONFIG_ENTRY_MINOR_VERSION) == (1, 3)
