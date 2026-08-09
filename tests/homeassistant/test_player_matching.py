"""Tests for safe native-alias player matching and trailing recovery."""

from __future__ import annotations

from custom_components.jellyfin_assist.player_matching import (
    PlayerCandidate,
    compact_player_text,
    humanize_player_entity_id,
    normalize_player_text,
    recover_trailing_player,
    resolve_player_text,
)


CANDIDATES = (
    PlayerCandidate(
        "media_player.example_chromecast",
        "Example Chromecast",
        aliases=("Movie TV", "Primary Screen"),
    ),
    PlayerCandidate(
        "media_player.example_secondary_chromecast",
        "Example Secondary Chromecast",
        aliases=("Secondary TV",),
    ),
)


def test_tv_punctuation_and_initials_normalize_equivalently() -> None:
    assert normalize_player_text("Movie.T v") == "movie tv"
    assert compact_player_text("the Movie T. V.") == "movietv"



def test_entity_id_match_retains_preferred_native_alias() -> None:
    result = resolve_player_text(
        "media_player.example_chromecast",
        CANDIDATES,
        allow_fuzzy=True,
    )

    assert result.matched is True
    assert result.method == "entity_id"
    assert result.matched_alias == "Movie TV"



def test_entity_id_humanization_preserves_tv_acronym() -> None:
    assert humanize_player_entity_id("media_player.attic_tv") == "Attic TV"


def test_entity_id_match_uses_entity_household_name_when_friendly_name_differs() -> None:
    candidate = PlayerCandidate(
        "media_player.attic_tv",
        "Main TV",
        aliases=("Attic Tv",),
    )

    result = resolve_player_text(
        "media_player.attic_tv",
        (candidate,),
        allow_fuzzy=True,
    )

    assert result.matched is True
    assert result.method == "entity_id"
    assert result.matched_alias == "Attic TV"

def test_native_alias_exact_match() -> None:
    result = resolve_player_text("Movie TV", CANDIDATES, allow_fuzzy=False)

    assert result.matched is True
    assert result.entity_id == "media_player.example_chromecast"
    assert result.method == "normalized_exact"


def test_compact_tv_variant_matches_without_fuzzy() -> None:
    result = resolve_player_text("Movie.T v", CANDIDATES, allow_fuzzy=False)

    assert result.matched is True
    assert result.entity_id == "media_player.example_chromecast"
    assert result.method in {"normalized_exact", "compact_exact"}


def test_unique_typo_requires_configured_target_scope() -> None:
    assert resolve_player_text(
        "secndary tv", CANDIDATES, allow_fuzzy=False
    ).status == "not_found"

    result = resolve_player_text("secndary tv", CANDIDATES, allow_fuzzy=True)
    assert result.matched is True
    assert result.entity_id == "media_player.example_secondary_chromecast"
    assert result.method == "fuzzy_alias"


def test_partial_name_is_ambiguous_when_multiple_targets_share_it() -> None:
    candidates = (
        PlayerCandidate("media_player.bedroom_tv", "Bedroom TV"),
        PlayerCandidate("media_player.bedroom_speaker", "Bedroom Speaker"),
    )

    result = resolve_player_text("bedroom", candidates, allow_fuzzy=True)

    assert result.status == "ambiguous"
    assert {item["entity_id"] for item in result.candidates} == {
        "media_player.bedroom_tv",
        "media_player.bedroom_speaker",
    }


def test_trailing_player_recovery_cleans_artist_context() -> None:
    recovery = recover_trailing_player(
        {
            "query": "Crash Into Me",
            "artist": "Dave Matthews Band on Movie.T v",
            "series": "",
            "album": "",
        },
        CANDIDATES,
        allow_fuzzy=True,
    )

    assert recovery.recovered is True
    assert recovery.match is not None
    assert recovery.match.entity_id == "media_player.example_chromecast"
    assert recovery.field_name == "artist"
    assert recovery.fields["artist"] == "Dave Matthews Band"


def test_trailing_player_recovery_cleans_title_context() -> None:
    recovery = recover_trailing_player(
        {"query": "Bubba Ho-tep on secndary tv", "artist": "", "series": ""},
        CANDIDATES,
        allow_fuzzy=True,
    )

    assert recovery.recovered is True
    assert recovery.match is not None
    assert recovery.match.entity_id == "media_player.example_secondary_chromecast"
    assert recovery.fields["query"] == "Bubba Ho-tep"


def test_unresolved_player_like_suffix_is_removed_before_follow_up() -> None:
    recovery = recover_trailing_player(
        {"query": "Bubba Ho-tep on Bedroom TV", "artist": "", "series": ""},
        CANDIDATES,
        allow_fuzzy=False,
    )

    assert recovery.recovered is False
    assert recovery.player_phrase_detected is True
    assert recovery.original_player_text == "Bedroom TV"
    assert recovery.fields["query"] == "Bubba Ho-tep"


def test_title_ending_in_partial_player_name_is_not_stripped() -> None:
    candidates = (PlayerCandidate("media_player.fire_tv", "Fire TV"),)

    recovery = recover_trailing_player(
        {"query": "Room on Fire", "artist": "", "series": ""},
        candidates,
        allow_fuzzy=True,
    )

    assert recovery.recovered is False
    assert recovery.player_phrase_detected is False
    assert recovery.fields["query"] == "Room on Fire"


def test_trailing_recovery_uses_rightmost_preposition() -> None:
    recovery = recover_trailing_player(
        {
            "query": "Love on the Brain on Movie TV",
            "artist": "",
            "series": "",
        },
        CANDIDATES,
        allow_fuzzy=True,
    )

    assert recovery.recovered is True
    assert recovery.match is not None
    assert recovery.match.entity_id == "media_player.example_chromecast"
    assert recovery.fields["query"] == "Love on the Brain"
