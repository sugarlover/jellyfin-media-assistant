"""Protect native player resolution across queue-management intents."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Final

import yaml

from custom_components.jellyfin_assist import orchestration
from custom_components.jellyfin_assist.voice import build_voice_script_call

ROOT: Final = Path(__file__).resolve().parents[2]
HA_REFERENCE: Final = ROOT / "reference" / "current-working" / "home-assistant"
SENTENCES: Final = (
    ROOT
    / "custom_components"
    / "jellyfin_assist"
    / "custom_sentences"
    / "en"
    / "jellyfin_assist_media.yaml"
)
QUEUE_CONTROL: Final = (
    ROOT
    / "custom_components"
    / "jellyfin_assist"
    / "queue_control.py"
)


def test_queue_sentences_capture_raw_player_text_and_cover_natural_status_phrase() -> None:
    sentence_data = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))
    intents = sentence_data["intents"]
    status_sentences = intents["JellyfinAssistQueueStatus"]["data"][0]["sentences"]

    assert (
        "what is [the] (queue|cue) status on {media_player_request}"
        in status_sentences
    )
    assert "what is [the] (queue|cue) status" in status_sentences
    assert any(
        "{media_player_request}" in sentence
        for sentence in status_sentences
    )
    assert not any(
        "{media_player}" in sentence
        for sentence in status_sentences
    )


def test_queue_control_sentences_cover_queue_cue_stt_variants() -> None:
    sentence_data = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))
    intents = sentence_data["intents"]

    next_sentences = (
        intents["JellyfinAssistQueueNext"]["data"][0]["sentences"]
    )
    assert (
        "advance [the] (queue|cue) on {media_player_request}"
        in next_sentences
    )
    assert "advance [the] (queue|cue)" in next_sentences

    status_sentences = (
        intents["JellyfinAssistQueueStatus"]["data"][0]["sentences"]
    )
    assert "(queue|cue) status on {media_player_request}" in status_sentences
    assert (
        "what is [the] (queue|cue) status on {media_player_request}"
        in status_sentences
    )
    assert (
        "what's in [the] (queue|cue) on {media_player_request}"
        in status_sentences
    )
    assert (
        "how many items are in [the] (queue|cue) on {media_player_request}"
        in status_sentences
    )
    assert "(queue|cue) status" in status_sentences
    assert "what is in [the] (queue|cue)" in status_sentences

    clear_sentences = (
        intents["JellyfinAssistQueueClear"]["data"][0]["sentences"]
    )
    assert (
        "(clear|empty) [the] (queue|cue) (on|for) {media_player_request}"
        in clear_sentences
    )
    assert (
        "(clear|empty) {media_player_request} (queue|cue)"
        in clear_sentences
    )
    assert all(
        "{media_player_request}" in sentence
        for sentence in clear_sentences
    )

    shuffle_sentences = (
        intents["JellyfinAssistQueueShuffle"]["data"][0]["sentences"]
    )
    assert (
        "(shuffle|randomize) [the] (queue|cue) on {media_player_request}"
        in shuffle_sentences
    )
    assert "(shuffle|randomize) [the] (queue|cue)" in shuffle_sentences

    repeat_sentences = (
        intents["JellyfinAssistQueueRepeatQueueEnable"]["data"][0]["sentences"]
    )
    assert (
        "repeat [the] (queue|cue) on {media_player_request}"
        in repeat_sentences
    )
    assert (
        "repeat this (queue|cue) on {media_player_request}"
        in repeat_sentences
    )
    assert (
        "turn on (repeat queue|repeat cue|queue repeat|cue repeat) "
        "on {media_player_request}"
        in repeat_sentences
    )
    assert (
        "loop [the] (queue|cue) on {media_player_request}"
        in repeat_sentences
    )
    assert "repeat [the] (queue|cue)" in repeat_sentences
    assert "repeat this (queue|cue)" in repeat_sentences
    assert (
        "turn on (repeat queue|repeat cue|queue repeat|cue repeat)"
        in repeat_sentences
    )
    assert "loop [the] (queue|cue)" in repeat_sentences

    toggle_sentences = (
        intents["JellyfinAssistQueueRepeatQueueToggle"]["data"][0]["sentences"]
    )
    assert (
        "toggle repeat (queue|cue) on {media_player_request}"
        in toggle_sentences
    )
    assert (
        "toggle (queue|cue) repeat on {media_player_request}"
        in toggle_sentences
    )
    assert "toggle repeat (queue|cue)" in toggle_sentences
    assert "toggle (queue|cue) repeat" in toggle_sentences


def test_all_queue_intents_use_shared_native_player_dispatcher() -> None:
    expected = {
        "JellyfinAssistQueueNext": "queue_next",
        "JellyfinAssistQueueWhatsPlaying": "whats_playing",
        "JellyfinAssistQueueWhatJustPlayed": "what_just_played",
        "JellyfinAssistQueueStatus": "queue_status",
        "JellyfinAssistQueueClear": "queue_clear",
        "JellyfinAssistQueueShuffle": "queue_shuffle",
        "JellyfinAssistQueueRepeatItemEnable": "repeat_item_enable",
        "JellyfinAssistQueueRepeatQueueEnable": "repeat_queue_enable",
        "JellyfinAssistQueueRepeatOff": "repeat_off",
        "JellyfinAssistQueueRepeatItemToggle": "repeat_item_toggle",
        "JellyfinAssistQueueRepeatQueueToggle": "repeat_queue_toggle",
    }

    for intent_name, operation in expected.items():
        call = build_voice_script_call(
            intent_name,
            {"media_player_request": "Example Living Room TV"},
        )
        assert call.domain == "jellyfin_assist"
        assert call.service == "queue_command"
        assert call.data == {
            "operation": operation,
            "media_player": "Example Living Room TV",
        }


def test_native_queue_dispatcher_routes_every_supported_operation_and_preserves_alias() -> None:
    source = QUEUE_CONTROL.read_text(encoding="utf-8")

    assert "SERVICE_RESOLVE_MEDIA_PLAYER" in source

    for operation in (
        "queue_next",
        "whats_playing",
        "what_just_played",
        "queue_status",
        "queue_clear",
        "queue_shuffle",
        "repeat_item_enable",
        "repeat_queue_enable",
        "repeat_off",
        "repeat_item_toggle",
        "repeat_queue_toggle",
    ):
        assert operation in source

    assert "requested_entity_name" in source
    assert 'replace("_", " ").title().replace(" Tv", " TV")' in source
    assert 'status": "media_player_required"' in source


def test_player_follow_up_dispatches_pending_queue_or_media_operation_natively() -> None:
    source = inspect.getsource(orchestration.async_resume_pending_media_request)

    assert "QUEUE_PLAYER_OPERATIONS" in source
    assert "await async_queue_command(" in source
    assert "await async_media_orchestrator(" in source
    assert "script." not in source