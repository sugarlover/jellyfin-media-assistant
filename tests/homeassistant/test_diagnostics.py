"""Tests for redacted Home Assistant diagnostics."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from tests.homeassistant.ha_stubs import FakeEntry, FakeHass, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist.diagnostics import async_get_config_entry_diagnostics
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime
from custom_components.jellyfin_assist.search import CatalogManager


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_api_key_is_redacted(tmp_path: Path) -> None:
    async def loader() -> Any:
        raise AssertionError("not used")

    entry = FakeEntry(
        "entry",
        {
            "server_url": "http://host",
            "api_key": "top-secret",
            "user_id": "user",
        },
    )
    entry.runtime_data = JellyfinAssistRuntime(
        client=object(),  # type: ignore[arg-type]
        catalog_manager=CatalogManager(
            snapshot_loader=loader,
            requested_types=["Movie"],
            cache_identity="server:user",
            cache_store=None,
        ),
        connection_info=None,
        default_media_player="media_player.example_chromecast",
        playback_targets=(
            "media_player.example_chromecast",
            "media_player.example_secondary_chromecast",
        ),
        last_player_resolution={
            "match_method": "normalized_exact",
            "matched_entity_id": "media_player.example_chromecast",
        },
    )

    diagnostics = run(async_get_config_entry_diagnostics(FakeHass(tmp_path), entry))

    assert diagnostics["configuration_schema"] == {
        "stored_version": 1,
        "stored_minor_version": 1,
        "current_version": 1,
        "current_minor_version": 3,
    }
    assert diagnostics["entry"]["api_key"] == "**REDACTED**"
    assert diagnostics["player_configuration"] == {
        "default_media_player": "media_player.example_chromecast",
        "playback_targets": [
            "media_player.example_chromecast",
            "media_player.example_secondary_chromecast",
        ],
    }
    assert diagnostics["queue"] == {
        "storage": "home_assistant_store",
        "configured": False,
        "storage_key": None,
    }
    assert diagnostics["queue_advancement"] == {
        "mode": "native",
        "registered_targets": [],
        "completion_threshold_percent": 95,
        "last_result": None,
    }
    assert diagnostics["pending_selection"] == {
        "storage": "integration_runtime",
        "active": False,
        "choice_count": 0,
        "media_player": None,
        "operation": None,
        "intent": None,
    }
    assert diagnostics["last_player_resolution"]["match_method"] == "normalized_exact"
    assert diagnostics["voice"] == {
        "native_intent_handlers_expected": 27,
        "native_intent_handlers_registered": 0,
        "all_native_intent_handlers_registered": False,
        "custom_sentences_packaged": True,
        "custom_sentences_installed": False,
        "custom_sentences_current": False,
        "custom_sentences_managed": False,
        "custom_sentences_user_modified": False,
        "custom_sentences_status": "missing",
        "custom_sentence_language": "en",
        "custom_sentence_filename": "jellyfin_assist_media.yaml",
        "last_provisioning_status": None,
        "last_reload_attempted": False,
        "last_reload_succeeded": False,
        "last_provisioning_error": None,
    }
    assert "top-secret" not in str(diagnostics)
