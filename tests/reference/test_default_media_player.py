"""Protect optional default-player and player-follow-up behavior."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Final

import yaml

from custom_components.jellyfin_assist import orchestration
from custom_components.jellyfin_assist.voice import build_voice_script_call

ROOT: Final = Path(__file__).resolve().parents[2]
HA_REFERENCE: Final = ROOT / "reference" / "current-working" / "home-assistant"
CONFIGURATION: Final = HA_REFERENCE / "configuration.yaml"
SENTENCES: Final = ROOT / "custom_components" / "jellyfin_assist" / "custom_sentences" / "en" / "jellyfin_assist_media.yaml"


def test_orchestrator_resolves_player_before_media_resolution() -> None:
    source = inspect.getsource(orchestration.async_media_orchestrator)
    assert source.index("SERVICE_RESOLVE_MEDIA_PLAYER") < source.index("await async_resolve_media_intent(")
    assert 'status="media_player_required"' in source
    assert "Which media player would you like me to use?" in source


def test_pending_player_voice_follow_up_uses_native_resume_action() -> None:
    call = build_voice_script_call(
        "JellyfinAssistMediaPlayerSelect",
        {"media_player_request": "Basement", "media_player_kind": "TV"},
    )
    assert call.domain == "jellyfin_assist"
    assert call.service == "resume_pending_media_request"
    assert call.data == {"media_player": "Basement TV"}


def test_media_intents_do_not_hardcode_an_example_player_as_the_default() -> None:
    configuration = CONFIGURATION.read_text(encoding="utf-8")
    sentence_data = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))
    assert "media_player.example_chromecast" not in configuration
    assert "intent_script:" not in configuration
    assert "JellyfinAssistMediaPlayerSelect" in sentence_data["intents"]


def test_pending_player_follow_ups_require_explicit_continuation_phrases() -> None:
    sentence_data = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))
    intent = sentence_data["intents"]["JellyfinAssistMediaPlayerSelect"]
    groups = intent["data"]
    assert len(groups) == 1
    sentences = groups[0]["sentences"]
    assert "(use|choose|select) {media_player_request}" in sentences
    assert "(play|put|add) it (on|to) {media_player_request}" in sentences
    assert "continue (on|with) {media_player_request}" in sentences
    rendered = yaml.safe_dump(intent, sort_keys=False)
    assert "{name:media_player_request}" not in rendered
    assert '"{media_player_request} (TV|T V|television)"' not in rendered
    assert '"{media_player_request} (speaker|speakers)"' not in rendered


def test_native_media_control_phrases_are_not_claimed_by_pending_player_intent() -> None:
    sentence_data = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))
    sentences = sentence_data["intents"]["JellyfinAssistMediaPlayerSelect"]["data"][0]["sentences"]
    rendered = "\n".join(sentences).casefold()
    for native_verb in ("pause", "resume", "stop", "turn off", "mute", "volume"):
        assert native_verb not in rendered


def test_media_intents_use_separate_explicit_and_no_player_forms() -> None:
    sentence_data = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))
    intents = sentence_data["intents"]
    for intent_name in (
        "JellyfinAssistMusicAlbumPlay", "JellyfinAssistMusicAlbumAdd",
        "JellyfinAssistMusicSongPlay", "JellyfinAssistMusicSongAdd",
        "JellyfinAssistMusicArtistPlay", "JellyfinAssistMusicArtistAdd",
        "JellyfinAssistMoviePlay", "JellyfinAssistMovieAdd",
        "JellyfinAssistEpisodeTitlePlay", "JellyfinAssistEpisodeTitleAdd",
        "JellyfinAssistShowPlay", "JellyfinAssistShowAdd",
    ):
        sentences = intents[intent_name]["data"][0]["sentences"]
        assert not any("[on {media_player}]" in sentence for sentence in sentences)
        assert not any("[(to|on) {media_player}]" in sentence for sentence in sentences)
        assert any("{media_player}" in sentence for sentence in sentences)
        assert any("{media_player}" not in sentence for sentence in sentences)


def test_orchestrator_uses_player_recovered_request_fields() -> None:
    source = inspect.getsource(orchestration.async_media_orchestrator)
    for field in ("query", "artist", "series", "year", "season", "episode"):
        assert f'resolution.get("{field}")' in source


def test_integration_source_contains_no_instance_specific_player_aliases() -> None:
    integration_root = ROOT / "custom_components" / "jellyfin_assist"
    source = "\n".join(path.read_text(encoding="utf-8") for path in integration_root.rglob("*.py")).casefold()
    assert "media_player.example_chromecast" not in source
    assert "movie screen" not in source


def test_orchestrator_uses_resolved_player_display_name_in_responses() -> None:
    source = inspect.getsource(orchestration.async_media_orchestrator)
    assert "requested_display" in source
    assert "_requested_entity_display_name(requested_player)" in source
    assert 'resolution.get("media_player_name")' in source
    assert "resolved_player_name" in source


def test_explicit_entity_id_display_name_wins_over_friendly_name() -> None:
    assert orchestration._requested_entity_display_name("media_player.basement_tv") == "Basement TV"
    source = inspect.getsource(orchestration.async_media_orchestrator)
    expression = source[source.index("resolved_player_name ="):source.index("resolved_query =")]
    assert expression.index("requested_display") < expression.index("_requested_entity_display_name")
    assert expression.index("_requested_entity_display_name") < expression.index('resolution.get("media_player_name")')
