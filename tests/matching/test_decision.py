"""Tests for conservative deterministic confidence decisions."""

from __future__ import annotations

from custom_components.jellyfin_assist.matching.context import (
    MediaCandidate,
    MediaSearchContext,
    rank_context_candidates,
)
from custom_components.jellyfin_assist.matching.decision import (
    MatchDecisionReason,
    MatchDecisionStatus,
    decide_context_ranking,
    threshold_for_method,
)
from custom_components.jellyfin_assist.matching.deterministic import (
    DeterministicMatchMethod,
)


def _decide(
    query: str,
    candidates: list[MediaCandidate],
    context: MediaSearchContext | None = None,
):
    return decide_context_ranking(
        rank_context_candidates(query, candidates, context)
    )


def test_no_deterministic_matches_returns_not_found() -> None:
    decision = _decide(
        "Run Around",
        [MediaCandidate(key="wrong", title="Runaway")],
    )

    assert decision.status is MatchDecisionStatus.NOT_FOUND
    assert decision.reason is MatchDecisionReason.NO_MATCHING_CANDIDATES
    assert decision.selected is None
    assert not decision.alternatives
    assert not decision.automatic_selection_allowed


def test_single_exact_match_can_be_selected() -> None:
    decision = _decide(
        "3AM",
        [MediaCandidate(key="song", title="3AM")],
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.reason is MatchDecisionReason.UNIQUE_CONFIDENT_MATCH
    assert decision.selected is not None
    assert decision.selected.candidate.key == "song"
    assert decision.automatic_selection_allowed
    assert not decision.selection_required


def test_single_number_equivalent_regression_can_be_selected() -> None:
    decision = _decide(
        "the thirteenth warrior",
        [MediaCandidate(key="movie", title="The 13th Warrior")],
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert (
        decision.selected.title_match.method
        is DeterministicMatchMethod.NUMBER_EQUIVALENT
    )


def test_single_compact_spacing_regression_can_be_selected() -> None:
    decision = _decide(
        "run around",
        [MediaCandidate(key="song", title="Runaround")],
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert (
        decision.selected.title_match.method
        is DeterministicMatchMethod.COMPACT_SPACING
    )
    assert decision.required_margin == 6


def test_equal_top_scores_require_selection() -> None:
    decision = _decide(
        "The Matrix",
        [
            MediaCandidate(key="copy-a", title="The Matrix"),
            MediaCandidate(key="copy-b", title="The Matrix"),
        ],
    )

    assert decision.status is MatchDecisionStatus.AMBIGUOUS
    assert decision.reason is MatchDecisionReason.TOP_SCORE_TIED
    assert decision.selected is None
    assert [item.candidate.key for item in decision.alternatives] == [
        "copy-a",
        "copy-b",
    ]
    assert decision.observed_margin == 0
    assert decision.selection_required


def test_small_exact_to_casefold_margin_requires_selection() -> None:
    decision = _decide(
        "Home",
        [
            MediaCandidate(key="exact", title="Home"),
            MediaCandidate(key="case", title="HOME"),
        ],
    )

    assert decision.status is MatchDecisionStatus.AMBIGUOUS
    assert decision.reason is MatchDecisionReason.INSUFFICIENT_MARGIN
    assert decision.observed_margin == 1
    assert decision.required_margin == 3


def test_sufficient_exact_to_punctuation_margin_can_select() -> None:
    decision = _decide(
        "Run-Around",
        [
            MediaCandidate(key="exact", title="Run-Around"),
            MediaCandidate(key="spaced", title="Run Around"),
        ],
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "exact"
    assert [item.candidate.key for item in decision.alternatives] == ["spaced"]
    assert decision.observed_margin == 5
    assert decision.required_margin == 3


def test_artist_context_can_create_a_safe_unique_margin() -> None:
    decision = _decide(
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

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "metallica"
    assert decision.observed_margin is not None
    assert decision.observed_margin >= decision.required_margin


def test_single_context_contradiction_is_not_selected() -> None:
    decision = _decide(
        "3AM",
        [MediaCandidate(key="song", title="3AM", artist="Matchbox Twenty")],
        MediaSearchContext(artist="Eminem"),
    )

    assert decision.status is MatchDecisionStatus.NOT_FOUND
    assert decision.reason is MatchDecisionReason.TOP_CONTEXT_CONTRADICTION
    assert decision.selected is None
    assert [item.candidate.key for item in decision.alternatives] == ["song"]


def test_contradictory_top_among_multiple_candidates_requires_selection() -> None:
    decision = _decide(
        "Home",
        [
            MediaCandidate(key="exact-wrong", title="Home", year=2015),
            MediaCandidate(key="case-wrong", title="HOME", year=2015),
        ],
        MediaSearchContext(year=2009),
    )

    assert decision.status is MatchDecisionStatus.AMBIGUOUS
    assert decision.reason is MatchDecisionReason.TOP_CONTEXT_CONTRADICTION
    assert decision.selected is None


def test_missing_context_metadata_does_not_block_selection() -> None:
    decision = _decide(
        "Home",
        [MediaCandidate(key="unknown", title="Home")],
        MediaSearchContext(media_type="Movie", year=2015),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "unknown"


def test_hard_media_type_rejections_remain_visible() -> None:
    ranking = rank_context_candidates(
        "Home",
        [MediaCandidate(key="song", title="Home", media_type="Audio")],
        MediaSearchContext(media_type="Movie"),
    )
    decision = decide_context_ranking(ranking)

    assert decision.status is MatchDecisionStatus.NOT_FOUND
    assert decision.reason is MatchDecisionReason.NO_MATCHING_CANDIDATES
    assert [item.candidate.key for item in decision.rejected] == ["song"]


def test_thresholds_become_more_conservative_for_compact_spacing() -> None:
    exact = threshold_for_method(DeterministicMatchMethod.EXACT_ORIGINAL)
    compact = threshold_for_method(DeterministicMatchMethod.COMPACT_SPACING)

    assert exact.minimum_total_score == 100
    assert compact.minimum_total_score == 88
    assert compact.minimum_margin > exact.minimum_margin
