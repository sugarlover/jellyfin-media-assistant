"""Tests for controlled typing and swipe-like lexical matching."""

from __future__ import annotations

import pytest

from custom_components.jellyfin_assist.matching.fuzzy import (
    FuzzyMatchMethod,
    TitleCandidate,
    classify_fuzzy_match,
    damerau_levenshtein_distance,
    rank_fuzzy_candidates,
    score_for_fuzzy_match,
)


def _required_match(query: str, title: str):
    match = classify_fuzzy_match(query, title)
    assert match is not None
    return match


def test_edit_distance_supports_the_controlled_operations() -> None:
    assert damerau_levenshtein_distance("matrix", "matirx") == 1
    assert damerau_levenshtein_distance("jurasic", "jurassic") == 1
    assert damerau_levenshtein_distance("spidder", "spider") == 1
    assert damerau_levenshtein_distance("supernaturall", "supernatural") == 1


def test_adjacent_transposition_has_its_own_method() -> None:
    match = _required_match("matirx", "Matrix")

    assert match.method is FuzzyMatchMethod.ADJACENT_TRANSPOSITION
    assert match.edit_distance == 1
    assert match.lexical_score == 84


def test_adjacent_keyboard_substitution_has_its_own_method() -> None:
    match = _required_match("matric", "Matrix")

    assert match.method is FuzzyMatchMethod.ADJACENT_KEY_SUBSTITUTION
    assert match.edit_distance == 1
    assert match.lexical_score == 83


@pytest.mark.parametrize(
    ("query", "title"),
    [
        ("jurasic park", "Jurassic Park"),
        ("spidder man", "Spider-Man"),
        ("supernaturall", "Supernatural"),
        ("metalllica", "Metallica"),
    ],
)
def test_single_insertions_deletions_and_repeated_characters_match(
    query: str,
    title: str,
) -> None:
    match = _required_match(query, title)

    assert match.edit_distance == 1
    assert match.method in {
        FuzzyMatchMethod.SINGLE_EDIT,
        FuzzyMatchMethod.ADJACENT_TRANSPOSITION,
        FuzzyMatchMethod.ADJACENT_KEY_SUBSTITUTION,
    }


def test_limited_multi_edit_requires_a_longer_title() -> None:
    match = _required_match("jurasic prk", "Jurassic Park")

    assert match.method is FuzzyMatchMethod.LIMITED_MULTI_EDIT
    assert match.edit_distance == 2
    assert match.lexical_score == 76


def test_very_long_titles_can_tolerate_at_most_three_edits() -> None:
    match = _required_match(
        "pirats of the carribean",
        "Pirates of the Caribbean",
    )

    assert match.method is FuzzyMatchMethod.LIMITED_MULTI_EDIT
    assert match.edit_distance == 3
    assert match.lexical_score == 73


def test_short_titles_are_not_fuzzily_matched() -> None:
    assert classify_fuzzy_match("Up", "Us") is None
    assert classify_fuzzy_match("Heat", "Beat") is None


def test_word_boundary_changes_are_not_combined_with_typo_matching() -> None:
    assert classify_fuzzy_match("run arond", "Runaround") is None


def test_deterministic_equivalence_is_not_duplicated_as_fuzzy() -> None:
    assert classify_fuzzy_match("run around", "Run-Around") is None
    assert classify_fuzzy_match("three am", "3AM") is None
    assert classify_fuzzy_match("Beyonce", "Beyoncé") is None


def test_unrelated_titles_are_rejected() -> None:
    assert classify_fuzzy_match("Runaway", "Run Around") is None
    assert classify_fuzzy_match("Frozen", "Finding Nemo") is None


def test_scores_remain_below_all_deterministic_scores() -> None:
    scores = [
        score_for_fuzzy_match(FuzzyMatchMethod.ADJACENT_TRANSPOSITION, 1),
        score_for_fuzzy_match(FuzzyMatchMethod.ADJACENT_KEY_SUBSTITUTION, 1),
        score_for_fuzzy_match(FuzzyMatchMethod.SINGLE_EDIT, 1),
        score_for_fuzzy_match(FuzzyMatchMethod.LIMITED_MULTI_EDIT, 2),
        score_for_fuzzy_match(FuzzyMatchMethod.LIMITED_MULTI_EDIT, 3),
    ]

    assert scores == sorted(scores, reverse=True)
    assert max(scores) < 88


def test_ranking_places_safer_error_patterns_first() -> None:
    ranking = rank_fuzzy_candidates(
        "matirx",
        [
            TitleCandidate(key="single", title="Matirp"),
            TitleCandidate(key="keyboard", title="Matirc"),
            TitleCandidate(key="transpose", title="Matrix"),
            TitleCandidate(key="unrelated", title="Avatar"),
        ],
    )

    assert [item.candidate.key for item in ranking.matches] == [
        "transpose",
        "keyboard",
        "single",
    ]
    assert ranking.top_score == 84
    assert ranking.top_score_is_unique is True
    assert ranking.top_margin == 1


def test_equal_fuzzy_scores_preserve_catalog_order_and_ambiguity() -> None:
    ranking = rank_fuzzy_candidates(
        "spidder man",
        [
            TitleCandidate(key="first", title="Spider Man"),
            TitleCandidate(key="second", title="Spidder Men"),
        ],
    )

    assert [item.candidate.key for item in ranking.matches] == ["first", "second"]
    assert ranking.top_score_is_unique is False
    assert ranking.top_margin == 0


def test_single_fuzzy_match_has_no_observed_margin() -> None:
    ranking = rank_fuzzy_candidates(
        "jurasic park",
        [TitleCandidate(key="movie", title="Jurassic Park")],
    )

    assert ranking.top_score_is_unique is True
    assert ranking.top_margin is None

def test_fuzzy_typo_can_compare_against_numeric_ordinal_word_alias() -> None:
    match = _required_match("the thirteeth warrior", "The 13th Warrior")

    assert match.method is FuzzyMatchMethod.SINGLE_EDIT
    assert match.edit_distance == 1
    assert match.query_value == "the thirteeth warrior"
    assert match.candidate_value == "the thirteenth warrior"


def test_reverse_ordinal_alias_does_not_join_unrelated_numbers() -> None:
    assert classify_fuzzy_match("the thirtieth warrior", "The 13th Warrior") is None
