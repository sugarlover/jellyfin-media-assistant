"""Tests for deterministic media-title classification and scoring."""

from __future__ import annotations

from custom_components.jellyfin_assist.matching.deterministic import (
    DeterministicMatchMethod,
    TitleCandidate,
    classify_deterministic_match,
    classify_title_fragment_match,
    rank_deterministic_candidates,
    score_for_method,
)


def _required_match(query: str, title: str):
    match = classify_deterministic_match(query, title)
    assert match is not None
    return match


def test_exact_original_is_strongest() -> None:
    match = _required_match("3AM", "3AM")
    assert match.method is DeterministicMatchMethod.EXACT_ORIGINAL
    assert match.score == 100
    assert match.shared_value == "3AM"


def test_case_and_unicode_compatibility_are_classified() -> None:
    case_match = _required_match("The Matrix", "the matrix")
    width_match = _required_match("３ＡＭ", "3am")

    assert case_match.method is DeterministicMatchMethod.UNICODE_CASEFOLD
    assert width_match.method is DeterministicMatchMethod.UNICODE_CASEFOLD


def test_diacritic_equivalence_is_weaker_than_casefolding() -> None:
    match = _required_match("Beyoncé", "Beyonce")
    assert match.method is DeterministicMatchMethod.DIACRITIC_FOLD
    assert match.score < score_for_method(DeterministicMatchMethod.UNICODE_CASEFOLD)


def test_punctuation_equivalence_is_classified() -> None:
    match = _required_match("Run-Around", "run around")
    assert match.method is DeterministicMatchMethod.PUNCTUATION_SPACING


def test_number_word_equivalence_is_classified() -> None:
    match = _required_match("the thirteenth warrior", "The 13th Warrior")
    assert match.method is DeterministicMatchMethod.NUMBER_EQUIVALENT
    assert match.shared_value == "the 13th warrior"


def test_three_am_known_regressions_match_conservatively() -> None:
    spoken = _required_match("three am", "3AM")
    spaced = _required_match("3 am", "3AM")

    assert spoken.method is DeterministicMatchMethod.COMPACT_SPACING
    assert spaced.method is DeterministicMatchMethod.COMPACT_SPACING
    assert spoken.shared_value == "3am"
    assert spaced.shared_value == "3am"


def test_joined_and_separated_runaround_match_conservatively() -> None:
    joined = _required_match("runaround", "Run-Around")
    separated = _required_match("run around", "Run-Around")

    assert joined.method is DeterministicMatchMethod.COMPACT_SPACING
    assert separated.method is DeterministicMatchMethod.PUNCTUATION_SPACING
    assert joined.score < separated.score


def test_method_scores_have_the_intended_strength_order() -> None:
    ordered = [
        DeterministicMatchMethod.EXACT_ORIGINAL,
        DeterministicMatchMethod.UNICODE_CASEFOLD,
        DeterministicMatchMethod.DIACRITIC_FOLD,
        DeterministicMatchMethod.PUNCTUATION_SPACING,
        DeterministicMatchMethod.NUMBER_EQUIVALENT,
        DeterministicMatchMethod.COMPACT_SPACING,
        DeterministicMatchMethod.TITLE_FRAGMENT,
    ]
    scores = [score_for_method(method) for method in ordered]
    assert scores == sorted(scores, reverse=True)
    assert len(scores) == len(set(scores))


def test_unrelated_titles_do_not_receive_a_score() -> None:
    assert classify_deterministic_match("Runaway", "Run Around") is None
    assert classify_deterministic_match("13", "30") is None


def test_ranking_places_the_strongest_match_first() -> None:
    ranking = rank_deterministic_candidates(
        "Run-Around",
        [
            TitleCandidate(key="compact", title="Runaround"),
            TitleCandidate(key="exact", title="Run-Around"),
            TitleCandidate(key="punctuation", title="Run Around"),
            TitleCandidate(key="unrelated", title="Runaway"),
        ],
    )

    assert [entry.candidate.key for entry in ranking.matches] == [
        "exact",
        "punctuation",
        "compact",
    ]
    assert ranking.top_score == 100
    assert ranking.top_score_is_unique is True
    assert ranking.top_margin == 5


def test_equal_top_scores_are_reported_as_ambiguous() -> None:
    ranking = rank_deterministic_candidates(
        "the matrix",
        [
            TitleCandidate(key="first", title="The Matrix"),
            TitleCandidate(key="second", title="THE MATRIX"),
        ],
    )

    assert [entry.candidate.key for entry in ranking.matches] == ["first", "second"]
    assert ranking.top_score_is_unique is False
    assert ranking.top_margin == 0


def test_ties_preserve_catalog_order_instead_of_inventing_a_winner() -> None:
    candidates = [
        TitleCandidate(key="z", title="THE MATRIX"),
        TitleCandidate(key="a", title="The Matrix"),
    ]
    ranking = rank_deterministic_candidates("the matrix", candidates)

    assert [entry.candidate.key for entry in ranking.matches] == ["z", "a"]


def test_single_match_does_not_claim_a_measured_margin() -> None:
    ranking = rank_deterministic_candidates(
        "3AM",
        [TitleCandidate(key="song", title="3AM")],
    )

    assert ranking.top_score_is_unique is True
    assert ranking.top_margin is None


def test_whole_token_title_fragment_is_classified_separately() -> None:
    match = classify_title_fragment_match("planet", "Planet Terror")

    assert match is not None
    assert match.method is DeterministicMatchMethod.TITLE_FRAGMENT
    assert match.shared_value == "planet"
    assert match.score == score_for_method(DeterministicMatchMethod.TITLE_FRAGMENT)


def test_title_fragment_respects_token_boundaries() -> None:
    assert classify_title_fragment_match("plan", "Planet Terror") is None
    assert classify_title_fragment_match("it", "It Comes at Night") is None


def test_title_fragment_uses_safe_normalized_and_numeric_variants() -> None:
    punctuation = classify_title_fragment_match("bubba ho", "Bubba Ho-tep")
    number = classify_title_fragment_match(
        "thirteenth warrior",
        "The 13th Warrior Returns",
    )

    assert punctuation is not None
    assert punctuation.shared_value == "bubba ho"
    assert number is not None
    assert number.shared_value == "13th warrior"


def test_title_fragment_is_weaker_than_full_title_equivalence() -> None:
    assert score_for_method(DeterministicMatchMethod.TITLE_FRAGMENT) < score_for_method(
        DeterministicMatchMethod.COMPACT_SPACING
    )
