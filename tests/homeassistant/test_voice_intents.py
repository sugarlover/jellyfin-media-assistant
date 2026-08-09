"""Tests for native Jellyfin Media Assistant voice intents."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.homeassistant.ha_stubs import (
    FakeHass,
    Intent,
    ServiceCall,
    install_homeassistant_stubs,
)

install_homeassistant_stubs()

from custom_components.jellyfin_assist.intent import (
    JellyfinAssistIntentHandler,
    async_setup_intents,
)
from custom_components.jellyfin_assist.voice import (
    INTENT_DESCRIPTIONS,
    NATIVE_INTENT_TYPES,
    VoiceIntentValidationError,
    build_voice_script_call,
    clean_request_text,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_native_intent_inventory_is_complete_and_described() -> None:
    assert len(NATIVE_INTENT_TYPES) == 27
    assert len(set(NATIVE_INTENT_TYPES)) == 27
    assert set(NATIVE_INTENT_TYPES) == set(INTENT_DESCRIPTIONS)
    assert all(name.startswith("JellyfinAssist") for name in NATIVE_INTENT_TYPES)


def test_request_cleanup_matches_previous_intent_script_rules() -> None:
    assert clean_request_text("  Jurassic   World!!!  ") == "Jurassic World"
    assert clean_request_text("The Sound Of Silence, ") == "The Sound Of Silence"


def test_album_request_splits_optional_artist_and_preserves_player() -> None:
    call = build_voice_script_call(
        "JellyfinAssistMusicAlbumPlay",
        {
            "album_request": "  Weathered by Creed. ",
            "media_player": "media_player.example_chromecast",
        },
    )

    assert call.service == "media_orchestrator"
    assert call.domain == "jellyfin_assist"
    assert call.data == {
        "query": "Weathered",
        "artist": "Creed",
        "media_type": "MusicAlbum",
        "media_player": "media_player.example_chromecast",
        "operation": "play",
    }


def test_episode_title_request_splits_series_qualifier() -> None:
    call = build_voice_script_call(
        "JellyfinAssistEpisodeTitleAdd",
        {
            "episode_request": "Pilot from the show Lost",
            "media_player": "media_player.example_chromecast",
        },
    )

    assert call.data == {
        "query": "Pilot",
        "series": "Lost",
        "media_type": "Episode",
        "media_player": "media_player.example_chromecast",
        "operation": "add",
    }


def test_show_request_forwards_season_and_episode() -> None:
    call = build_voice_script_call(
        "JellyfinAssistShowPlay",
        {
            "show_request": "The Simpsons",
            "season": "2",
            "episode": 3,
        },
    )

    assert call.data == {
        "query": "The Simpsons",
        "media_type": "Series",
        "media_player": "",
        "operation": "play",
        "season": 2,
        "episode": 3,
    }


def test_queue_request_prefers_spoken_player_request() -> None:
    call = build_voice_script_call(
        "JellyfinAssistQueueStatus",
        {
            "media_player_request": "Basement TV",
            "media_player": "media_player.example_chromecast",
        },
    )

    assert call.service == "queue_command"
    assert call.domain == "jellyfin_assist"
    assert call.data == {
        "operation": "queue_status",
        "media_player": "Basement TV",
    }


def test_pending_selection_and_player_follow_up_use_native_actions() -> None:
    select = build_voice_script_call(
        "JellyfinAssistMediaSelect",
        {"selection": "2"},
    )
    player = build_voice_script_call(
        "JellyfinAssistMediaPlayerSelect",
        {"media_player_request": "Basement", "media_player_kind": "TV"},
    )

    assert select.service == "play_pending_media"
    assert select.domain == "jellyfin_assist"
    assert select.data == {"selection": 2}
    assert player.service == "resume_pending_media_request"
    assert player.domain == "jellyfin_assist"
    assert player.data == {"media_player": "Basement TV"}


def test_invalid_pending_selection_is_rejected_before_script_call() -> None:
    with pytest.raises(VoiceIntentValidationError, match="valid result number"):
        build_voice_script_call("JellyfinAssistMediaSelect", {"selection": 0})


def test_async_setup_intents_registers_all_canonical_handlers(tmp_path: Path) -> None:
    hass = FakeHass(tmp_path)

    run(async_setup_intents(hass))

    assert set(hass.data["intent"]) == set(NATIVE_INTENT_TYPES)
    assert all(
        isinstance(handler, JellyfinAssistIntentHandler)
        for handler in hass.data["intent"].values()
    )


def test_handler_calls_native_orchestrator_and_returns_established_speech(
    tmp_path: Path,
) -> None:
    hass = FakeHass(tmp_path)
    context = object()

    async def orchestrator(call: ServiceCall) -> dict[str, Any]:
        assert call.data == {
            "query": "Jurassic World",
            "media_type": "Movie",
            "media_player": "media_player.example_chromecast",
            "operation": "play",
        }
        return {
            "success": True,
            "status": "playing",
            "speak": "Playing Jurassic World (2015) on Example Chromecast.",
        }

    hass.services.async_register(
        "jellyfin_assist",
        "media_orchestrator",
        orchestrator,
    )
    handler = JellyfinAssistIntentHandler("JellyfinAssistMoviePlay")
    intent_obj = Intent(
        hass,
        {
            "movie_request": {"value": "Jurassic World"},
            "media_player": {"value": "media_player.example_chromecast"},
        },
        context=context,
    )

    response = run(handler.async_handle(intent_obj))

    assert response.speech["plain"]["speech"] == (
        "Playing Jurassic World (2015) on Example Chromecast."
    )
    assert hass.services.calls[-1] == {
        "domain": "jellyfin_assist",
        "service": "media_orchestrator",
        "data": {
            "query": "Jurassic World",
            "media_type": "Movie",
            "media_player": "media_player.example_chromecast",
            "operation": "play",
        },
        "blocking": True,
        "return_response": True,
        "context": context,
    }


def test_handler_speaks_validation_error_without_running_action(tmp_path: Path) -> None:
    hass = FakeHass(tmp_path)
    handler = JellyfinAssistIntentHandler("JellyfinAssistMediaSelect")
    response = run(handler.async_handle(Intent(hass, {"selection": {"value": 0}})))

    assert response.speech["plain"]["speech"] == "Please provide a valid result number."
    assert hass.services.calls == []
