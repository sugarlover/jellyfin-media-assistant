"""Tests for bounded deterministic Jellyfin catalog query planning."""

from __future__ import annotations

import pytest

from custom_components.jellyfin_assist.search import (
    CatalogAttemptResult,
    CatalogQueryMethod,
    aggregate_catalog_results,
    plan_catalog_queries,
)


def test_original_query_is_always_first() -> None:
    plan = plan_catalog_queries("  Jurassic   Park  ")

    assert plan.original_query == "Jurassic Park"
    assert plan.attempts[0].term == "Jurassic Park"
    assert plan.attempts[0].methods == (CatalogQueryMethod.ORIGINAL,)


def test_case_only_duplicate_is_not_sent_to_jellyfin() -> None:
    plan = plan_catalog_queries("Jurassic Park")

    assert plan.attempted_terms == (
        "Jurassic Park",
        "JurassicPark",
        "jurassic-park",
    )
    assert "jurassic park" not in plan.attempted_terms
    assert plan.attempts[-1].fallback_only


def test_three_am_gets_ordered_numeric_and_compact_attempts() -> None:
    plan = plan_catalog_queries("three am")

    assert plan.attempted_terms == ("three am", "3 am", "3am")
    assert CatalogQueryMethod.NUMBER_EQUIVALENT in plan.attempts[1].methods
    assert CatalogQueryMethod.COMPACT_SPACING in plan.attempts[2].methods


def test_ordinal_words_get_a_digit_attempt_without_long_compaction() -> None:
    plan = plan_catalog_queries("the thirteenth warrior")

    assert plan.attempted_terms == (
        "the thirteenth warrior",
        "the 13th warrior",
    )


def test_dash_and_spacing_forms_get_small_useful_attempt_set() -> None:
    plan = plan_catalog_queries("run-around")

    assert plan.attempted_terms == ("run-around", "run around", "runaround")


def test_two_word_spaced_title_can_try_joined_and_hyphenated_stylizations() -> None:
    plan = plan_catalog_queries("run around")

    assert plan.attempted_terms == ("run around", "runaround", "run-around")
    assert plan.attempts[2].methods == (CatalogQueryMethod.HYPHENATED_SPACING,)
    assert plan.attempts[2].fallback_only


def test_hyphenated_spacing_fallback_is_conservative() -> None:
    assert "the-matrix" not in plan_catalog_queries("the matrix").attempted_terms
    assert "up-next" not in plan_catalog_queries("up next").attempted_terms
    assert "one-two-three" not in plan_catalog_queries("one two three").attempted_terms


def test_joined_word_gets_bounded_split_fallbacks() -> None:
    plan = plan_catalog_queries("runaround")

    assert plan.attempted_terms[:3] == (
        "runaround",
        "run around",
        "run-around",
    )
    assert plan.attempts[1].methods == (CatalogQueryMethod.JOINED_WORD_SPLIT,)
    assert plan.attempts[2].methods == (CatalogQueryMethod.JOINED_WORD_SPLIT,)
    assert plan.attempts[1].fallback_only
    assert plan.attempts[2].fallback_only
    assert len(plan.attempts) <= 6




def test_joined_word_tries_hyphen_before_another_split_boundary() -> None:
    plan = plan_catalog_queries("runaround")

    assert plan.attempted_terms[:3] == (
        "runaround",
        "run around",
        "run-around",
    )
    assert "runaro und" not in plan.attempted_terms[:3]

def test_digit_letter_boundary_gets_safe_split_fallback() -> None:
    plan = plan_catalog_queries("3am")

    assert plan.attempted_terms == ("3am", "3 am")
    assert plan.attempts[1].fallback_only


def test_article_led_title_is_not_compacted() -> None:
    plan = plan_catalog_queries("The Thing")

    assert "thething" not in plan.attempted_terms


def test_diacritic_fold_is_sent_after_original() -> None:
    plan = plan_catalog_queries("Beyoncé")

    assert plan.attempted_terms[:2] == ("Beyoncé", "beyonce")
    assert CatalogQueryMethod.DIACRITIC_FOLD in plan.attempts[1].methods
    assert all(attempt.fallback_only for attempt in plan.attempts[2:])


def test_unicode_compatibility_form_remains_a_distinct_attempt() -> None:
    plan = plan_catalog_queries("３ＡＭ")

    assert plan.attempted_terms[0] == "３ＡＭ"
    assert "3am" in plan.attempted_terms
    normalized = next(attempt for attempt in plan.attempts if attempt.term == "3am")
    assert CatalogQueryMethod.UNICODE_COMPATIBILITY in normalized.methods


def test_attempt_count_and_candidate_limits_are_bounded() -> None:
    plan = plan_catalog_queries(
        "three am",
        max_attempts=2,
        per_attempt_limit=7,
        max_unique_candidates=11,
    )

    assert len(plan.attempts) == 2
    assert plan.per_attempt_limit == 7
    assert plan.max_unique_candidates == 11


@pytest.mark.parametrize(
    ("keyword", "message"),
    [
        ({"max_attempts": 0}, "max_attempts must be positive"),
        ({"per_attempt_limit": 0}, "per_attempt_limit must be positive"),
        ({"max_unique_candidates": 0}, "max_unique_candidates must be positive"),
    ],
)
def test_nonpositive_limits_are_rejected(keyword: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        plan_catalog_queries("Matrix", **keyword)


def test_empty_and_non_string_queries_are_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        plan_catalog_queries("   ")
    with pytest.raises(TypeError, match="query must be a string"):
        plan_catalog_queries(3)  # type: ignore[arg-type]


def test_candidate_pool_deduplicates_by_jellyfin_id_and_tracks_sources() -> None:
    plan = plan_catalog_queries("run-around")
    results = (
        CatalogAttemptResult(
            attempt=plan.attempts[0],
            items=(
                {"id": "song-1", "name": "Run-Around"},
                {"id": "song-2", "name": "Runaway"},
            ),
        ),
        CatalogAttemptResult(
            attempt=plan.attempts[1],
            items=(
                {"id": "song-1", "name": "Run-Around duplicate payload"},
            ),
        ),
    )

    pool = aggregate_catalog_results(plan, results)

    assert [candidate.item_id for candidate in pool.candidates] == ["song-1", "song-2"]
    assert pool.candidates[0].item["name"] == "Run-Around"
    assert len(pool.candidates[0].sources) == 2
    assert pool.raw_item_count == 3
    assert pool.duplicate_item_count == 1
    assert not pool.truncated


def test_candidate_pool_accepts_raw_jellyfin_Id_field() -> None:
    plan = plan_catalog_queries("Matrix")
    result = CatalogAttemptResult(
        attempt=plan.attempts[0],
        items=({"Id": "movie-1", "Name": "The Matrix"},),
    )

    pool = aggregate_catalog_results(plan, (result,))

    assert pool.candidates[0].item_id == "movie-1"


def test_candidate_pool_reports_invalid_items() -> None:
    plan = plan_catalog_queries("Matrix")
    result = CatalogAttemptResult(
        attempt=plan.attempts[0],
        items=({}, {"id": ""}, {"id": "movie-1"}),
    )

    pool = aggregate_catalog_results(plan, (result,))

    assert pool.invalid_item_count == 2
    assert [candidate.item_id for candidate in pool.candidates] == ["movie-1"]


def test_candidate_pool_caps_unique_items_but_retains_diagnostics() -> None:
    plan = plan_catalog_queries("Matrix", max_unique_candidates=2)
    result = CatalogAttemptResult(
        attempt=plan.attempts[0],
        items=(
            {"id": "1"},
            {"id": "2"},
            {"id": "3"},
            {"id": "3"},
            {"id": "4"},
        ),
    )

    pool = aggregate_catalog_results(plan, (result,))

    assert [candidate.item_id for candidate in pool.candidates] == ["1", "2"]
    assert pool.raw_item_count == 5
    assert pool.dropped_unique_count == 2
    assert pool.truncated


def test_result_from_another_plan_is_rejected() -> None:
    plan = plan_catalog_queries("Matrix")
    other_plan = plan_catalog_queries("Alien")
    result = CatalogAttemptResult(attempt=other_plan.attempts[0], items=())

    with pytest.raises(ValueError, match="does not belong"):
        aggregate_catalog_results(plan, (result,))
