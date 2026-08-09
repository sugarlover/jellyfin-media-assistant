"""Tests for the UI config flow boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from tests.homeassistant.ha_stubs import FakeEntry, FakeHass, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist.api import (
    JellyfinAuthenticationError,
    JellyfinConnectionInfo,
)
from custom_components.jellyfin_assist.config_flow import (
    JellyfinAssistConfigFlow,
    JellyfinAssistOptionsFlow,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_user_step_validates_normalizes_and_creates_unique_entry(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        assert user_id == "user-1"
        return JellyfinConnectionInfo(
            server_id="server-1",
            server_name="My Jellyfin",
            server_version="10.11.11",
            user_id="USER-1",
            user_name="Example User",
        )

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.config_flow.JellyfinApiClient.async_validate_connection",
        validate,
    )
    flow = JellyfinAssistConfigFlow()
    flow.hass = FakeHass(tmp_path, session=object())

    result = run(
        flow.async_step_user(
            {
                "server_url": " http://jellyfin.local:8096/ ",
                "api_key": " secret ",
                "user_id": " user-1 ",
                "verify_ssl": True,
            }
        )
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "My Jellyfin"
    assert result["data"]["server_url"] == "http://jellyfin.local:8096"
    assert result["data"]["api_key"] == "secret"
    assert result["data"]["user_id"] == "USER-1"
    assert flow.unique_id == "server-1:user-1"


def test_user_step_maps_authentication_failure_to_form_error(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        raise JellyfinAuthenticationError("bad token")

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.config_flow.JellyfinApiClient.async_validate_connection",
        validate,
    )
    flow = JellyfinAssistConfigFlow()
    flow.hass = FakeHass(tmp_path, session=object())

    result = run(
        flow.async_step_user(
            {
                "server_url": "http://jellyfin.local:8096",
                "api_key": "bad",
                "user_id": "user",
                "verify_ssl": True,
            }
        )
    )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"


def test_options_flow_saves_optional_default_media_player() -> None:
    flow = JellyfinAssistOptionsFlow()
    flow.config_entry = FakeEntry(
        "entry-1",
        {},
        options={"default_media_player": "media_player.example_chromecast"},
    )

    form = run(flow.async_step_init())
    assert form["type"] == "form"
    assert flow.suggested_values == {
        "default_media_player": "media_player.example_chromecast",
        "playback_targets": [],
    }

    result = run(
        flow.async_step_init(
            {
                "default_media_player": " media_player.example_secondary_chromecast ",
                "playback_targets": [
                    "media_player.example_chromecast",
                    "media_player.example_secondary_chromecast",
                    "media_player.example_secondary_chromecast",
                ],
            }
        )
    )
    assert result == {
        "type": "create_entry",
        "data": {
            "default_media_player": "media_player.example_secondary_chromecast",
            "playback_targets": ["media_player.example_chromecast"],
        },
    }


def test_options_flow_allows_default_player_to_be_cleared() -> None:
    flow = JellyfinAssistOptionsFlow()
    flow.config_entry = FakeEntry(
        "entry-1",
        {},
        options={"default_media_player": "media_player.example_chromecast"},
    )

    result = run(flow.async_step_init({"default_media_player": ""}))

    assert result == {"type": "create_entry", "data": {}}



def test_options_flow_normalizes_scalar_playback_target() -> None:
    flow = JellyfinAssistOptionsFlow()
    flow.config_entry = FakeEntry("entry-1", {}, options={})

    result = run(
        flow.async_step_init(
            {
                "default_media_player": "media_player.example_chromecast",
                "playback_targets": "media_player.example_chromecast",
            }
        )
    )

    assert result == {
        "type": "create_entry",
        "data": {
            "default_media_player": "media_player.example_chromecast",
        },
    }

def test_config_flow_explicitly_advertises_options_support() -> None:
    entry = FakeEntry("entry-1", {})

    assert JellyfinAssistConfigFlow.async_supports_options_flow(entry) is True
    assert isinstance(
        JellyfinAssistConfigFlow.async_get_options_flow(entry),
        JellyfinAssistOptionsFlow,
    )


def test_options_flow_automatically_includes_default_as_effective_target() -> None:
    flow = JellyfinAssistOptionsFlow()
    flow.config_entry = FakeEntry("entry-1", {}, options={})

    result = run(
        flow.async_step_init(
            {
                "default_media_player": "media_player.example_chromecast",
                "playback_targets": ["media_player.example_secondary_chromecast"],
            }
        )
    )

    assert result == {
        "type": "create_entry",
        "data": {
            "default_media_player": "media_player.example_chromecast",
            "playback_targets": ["media_player.example_secondary_chromecast"],
        },
    }

def test_config_flow_declares_public_schema_version() -> None:
    assert JellyfinAssistConfigFlow.VERSION == 1
    assert JellyfinAssistConfigFlow.MINOR_VERSION == 3

def test_options_flow_suggests_legacy_behavior_data_before_migration() -> None:
    flow = JellyfinAssistOptionsFlow()
    flow.config_entry = FakeEntry(
        "entry-1",
        {
            "default_media_player": "media_player.example_chromecast",
            "playback_targets": "media_player.example_secondary_chromecast",
        },
        options={},
    )

    form = run(flow.async_step_init())

    assert form["type"] == "form"
    assert flow.suggested_values == {
        "default_media_player": "media_player.example_chromecast",
        "playback_targets": ["media_player.example_secondary_chromecast"],
    }
