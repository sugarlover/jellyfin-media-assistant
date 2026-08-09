"""Tests for deterministic media context ranking."""

from __future__ import annotations

from custom_components.jellyfin_assist.matching.context import (
    ContextField,
    ContextRelation,
    MediaCandidate,
    MediaSearchContext,
    rank_context_candidates,
)
from custom_components.jellyfin_assist.matching.deterministic import (
    DeterministicMatchMethod,
)
from custom_components.jellyfin_assist.matching.fuzzy import FuzzyMatchMethod


def _evidence(result, field: ContextField):
    return next(item for item in result.evidence if item.field is field)


def test_empty_context_preserves_title_only_ranking() -> None:
    ranking = rank_context_candidates(
        "Run-Around",
        [
            MediaCandidate(key="compact", title="Runaround"),
            MediaCandidate(key="exact", title="Run-Around"),
            MediaCandidate(key="punctuation", title="Run Around"),
        ],
    )

    assert [item.candidate.key for item in ranking.matches] == [
        "exact",
        "punctuation",
        "compact",
    ]
    assert all(item.context_score == 0 for item in ranking.matches)


def test_media_type_match_is_a_positive_signal() -> None:
    ranking = rank_context_candidates(
        "Home",
        [MediaCandidate(key="movie", title="Home", media_type="Movie")],
        MediaSearchContext(media_type="movie"),
    )

    result = ranking.matches[0]
    evidence = _evidence(result, ContextField.MEDIA_TYPE)
    assert evidence.relation is ContextRelation.MATCH
    assert evidence.adjustment > 0
    assert result.total_score == result.title_match.score + result.context_score


def test_media_type_spacing_is_normalized_without_semantic_aliases() -> None:
    ranking = rank_context_candidates(
        "Weathered",
        [
            MediaCandidate(
                key="album",
                title="Weathered",
                media_type="MusicAlbum",
            )
        ],
        MediaSearchContext(media_type="Music Album"),
    )

    assert [item.candidate.key for item in ranking.matches] == ["album"]


def test_explicit_media_type_mismatch_is_hard_rejected() -> None:
    ranking = rank_context_candidates(
        "Home",
        [
            MediaCandidate(key="movie", title="Home", media_type="Movie"),
            MediaCandidate(key="song", title="Home", media_type="Audio"),
        ],
        MediaSearchContext(media_type="Movie"),
    )

    assert [item.candidate.key for item in ranking.matches] == ["movie"]
    assert [item.candidate.key for item in ranking.rejected] == ["song"]
    assert ranking.rejected[0].reason == "media_type_mismatch"


def test_missing_candidate_media_type_is_neutral_not_wrong() -> None:
    ranking = rank_context_candidates(
        "Home",
        [MediaCandidate(key="unknown", title="Home")],
        MediaSearchContext(media_type="Movie"),
    )

    result = ranking.matches[0]
    evidence = _evidence(result, ContextField.MEDIA_TYPE)
    assert evidence.relation is ContextRelation.MISSING
    assert evidence.adjustment == 0
    assert not ranking.rejected


def test_artist_context_disambiguates_equal_song_titles() -> None:
    ranking = rank_context_candidates(
        "One",
        [
            MediaCandidate(key="u2", title="One", media_type="Audio", artist="U2"),
            MediaCandidate(
                key="metallica",
                title="One",
                media_type="Audio",
                artist="Metallica",
            ),
        ],
        MediaSearchContext(media_type="Audio", artist="Metallica"),
    )

    assert [item.candidate.key for item in ranking.matches] == ["metallica", "u2"]
    assert ranking.matches[0].has_context_contradiction is False
    assert ranking.matches[1].has_context_contradiction is True
    assert ranking.top_score_is_unique is True
    assert ranking.top_margin is not None and ranking.top_margin > 0


def test_diacritic_artist_equivalence_is_recorded_with_method() -> None:
    ranking = rank_context_candidates(
        "Halo",
        [MediaCandidate(key="song", title="Halo", artist="Beyoncé")],
        MediaSearchContext(artist="Beyonce"),
    )

    evidence = _evidence(ranking.matches[0], ContextField.ARTIST)
    assert evidence.relation is ContextRelation.MATCH
    assert evidence.method is DeterministicMatchMethod.DIACRITIC_FOLD


def test_album_context_ranks_the_requested_recording_first() -> None:
    ranking = rank_context_candidates(
        "Intro",
        [
            MediaCandidate(key="first", title="Intro", album="First Album"),
            MediaCandidate(key="second", title="Intro", album="Second Album"),
        ],
        MediaSearchContext(album="Second Album"),
    )

    assert ranking.matches[0].candidate.key == "second"
    assert _evidence(ranking.matches[0], ContextField.ALBUM).relation is ContextRelation.MATCH


def test_series_context_ranks_the_requested_episode_first() -> None:
    ranking = rank_context_candidates(
        "Pilot",
        [
            MediaCandidate(key="lost", title="Pilot", series="Lost"),
            MediaCandidate(key="fringe", title="Pilot", series="Fringe"),
        ],
        MediaSearchContext(series="Fringe"),
    )

    assert ranking.matches[0].candidate.key == "fringe"
    assert _evidence(ranking.matches[1], ContextField.SERIES).relation is ContextRelation.MISMATCH


def test_year_context_accepts_year_embedded_in_catalog_text() -> None:
    ranking = rank_context_candidates(
        "The Thing",
        [
            MediaCandidate(key="1982", title="The Thing", year="1982-06-25"),
            MediaCandidate(key="2011", title="The Thing", year=2011),
        ],
        MediaSearchContext(year="1982"),
    )

    assert ranking.matches[0].candidate.key == "1982"
    assert _evidence(ranking.matches[0], ContextField.YEAR).relation is ContextRelation.MATCH
    assert _evidence(ranking.matches[1], ContextField.YEAR).relation is ContextRelation.MISMATCH


def test_context_cannot_create_a_match_for_an_unrelated_title() -> None:
    ranking = rank_context_candidates(
        "Run Around",
        [
            MediaCandidate(
                key="wrong-title",
                title="Runaway",
                artist="Blues Traveler",
                album="Four",
                year=1994,
            )
        ],
        MediaSearchContext(artist="Blues Traveler", album="Four", year=1994),
    )

    assert not ranking.matches
    assert not ranking.rejected


def test_conflicting_metadata_is_visible_and_penalized() -> None:
    ranking = rank_context_candidates(
        "3AM",
        [MediaCandidate(key="song", title="3AM", artist="Matchbox Twenty", year=1996)],
        MediaSearchContext(artist="Eminem", year=2000),
    )

    result = ranking.matches[0]
    assert result.context_score < 0
    assert result.contradiction_count == 2
    assert result.has_context_contradiction is True


def test_equal_title_and_context_scores_remain_ambiguous() -> None:
    ranking = rank_context_candidates(
        "The Matrix",
        [
            MediaCandidate(key="copy-a", title="The Matrix", media_type="Movie", year=1999),
            MediaCandidate(key="copy-b", title="The Matrix", media_type="Movie", year=1999),
        ],
        MediaSearchContext(media_type="Movie", year=1999),
    )

    assert ranking.top_score_is_unique is False
    assert ranking.top_margin == 0
    assert [item.candidate.key for item in ranking.matches] == ["copy-a", "copy-b"]


def test_incomplete_artist_context_is_positive_evidence() -> None:
    ranking = rank_context_candidates(
        "Crash Into Me",
        [
            MediaCandidate(
                key="song",
                title="Crash Into Me",
                media_type="Audio",
                artist="Dave Matthews Band",
            )
        ],
        MediaSearchContext(media_type="Audio", artist="Dave Matthews"),
    )

    evidence = _evidence(ranking.matches[0], ContextField.ARTIST)
    assert evidence.relation is ContextRelation.MATCH
    assert evidence.method is DeterministicMatchMethod.TITLE_FRAGMENT
    assert evidence.adjustment > 0
    assert not ranking.matches[0].has_context_contradiction


def test_incomplete_artist_context_may_also_contain_a_controlled_typo() -> None:
    ranking = rank_context_candidates(
        "Crash Into Me",
        [
            MediaCandidate(
                key="song",
                title="Crash Into Me",
                media_type="Audio",
                artist="Dave Matthews Band",
            )
        ],
        MediaSearchContext(media_type="Audio", artist="Dave Mathews"),
    )

    evidence = _evidence(ranking.matches[0], ContextField.ARTIST)
    assert evidence.relation is ContextRelation.MATCH
    assert evidence.method is FuzzyMatchMethod.SINGLE_EDIT
    assert evidence.adjustment > 0


def test_incomplete_series_context_is_positive_evidence() -> None:
    ranking = rank_context_candidates(
        "Where Is Everybody?",
        [
            MediaCandidate(
                key="episode",
                title="Where Is Everybody?",
                media_type="Episode",
                series="The Twilight Zone",
            )
        ],
        MediaSearchContext(media_type="Episode", series="Twilight Zone"),
    )

    evidence = _evidence(ranking.matches[0], ContextField.SERIES)
    assert evidence.relation is ContextRelation.MATCH
    assert evidence.method is DeterministicMatchMethod.TITLE_FRAGMENT


def test_misspelled_series_context_is_controlled_fuzzy_evidence() -> None:
    ranking = rank_context_candidates(
        "Where Is Everybody?",
        [
            MediaCandidate(
                key="episode",
                title="Where Is Everybody?",
                media_type="Episode",
                series="The Twilight Zone",
            )
        ],
        MediaSearchContext(media_type="Episode", series="The Twlight Zone"),
    )

    evidence = _evidence(ranking.matches[0], ContextField.SERIES)
    assert evidence.relation is ContextRelation.MATCH
    assert evidence.method is FuzzyMatchMethod.SINGLE_EDIT


def test_unrelated_partial_context_remains_a_contradiction() -> None:
    ranking = rank_context_candidates(
        "Crash Into Me",
        [
            MediaCandidate(
                key="song",
                title="Crash Into Me",
                media_type="Audio",
                artist="Dave Matthews Band",
            )
        ],
        MediaSearchContext(media_type="Audio", artist="Coldplay"),
    )

    evidence = _evidence(ranking.matches[0], ContextField.ARTIST)
    assert evidence.relation is ContextRelation.MISMATCH
    assert ranking.matches[0].has_context_contradiction
