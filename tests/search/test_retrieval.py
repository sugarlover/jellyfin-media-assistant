"""Tests for mockable catalog retrieval, conversion, ranking, and decisions."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from custom_components.jellyfin_assist.matching import (
    LexicalMatchFamily,
    MatchDecisionStatus,
    MediaSearchContext,
    SearchDecisionReason,
)
from custom_components.jellyfin_assist.search import (
    CandidateMappingIssueReason,
    CatalogExecutionStopReason,
    CatalogRetrievalError,
    CatalogSearchFilters,
    CatalogSearchRequest,
    convert_catalog_pool,
    execute_catalog_plan,
    plan_catalog_queries,
    retrieve_rank_and_decide,
)
from custom_components.jellyfin_assist.search.planning import (
    CatalogAttemptResult,
    aggregate_catalog_results,
)


class RecordingCatalog:
    """Small deterministic async catalog client used by retrieval tests."""

    def __init__(
        self,
        responses: Mapping[str, Sequence[Mapping[str, Any]] | Exception],
    ) -> None:
        self.responses = responses
        self.requests: list[CatalogSearchRequest] = []

    async def __call__(
        self,
        request: CatalogSearchRequest,
    ) -> Sequence[Mapping[str, Any]]:
        self.requests.append(request)
        response = self.responses.get(request.term, ())
        if isinstance(response, Exception):
            raise response
        return response


def run(coro: Any) -> Any:
    """Run one async retrieval function without an asyncio pytest plugin."""

    return asyncio.run(coro)


def test_plan_executes_in_order_with_original_first() -> None:
    plan = plan_catalog_queries("three am")
    client = RecordingCatalog({})

    execution = run(execute_catalog_plan(plan, client))

    assert [request.term for request in client.requests] == [
        "three am",
        "3 am",
        "3am",
    ]
    assert execution.stop_reason is CatalogExecutionStopReason.PLAN_COMPLETE
    assert execution.completed_attempt_count == 3


def test_per_attempt_limit_and_filters_are_passed_to_client() -> None:
    plan = plan_catalog_queries("Matrix", per_attempt_limit=7)
    filters = CatalogSearchFilters(
        media_type="Movie",
        is_played=False,
        is_favorite=True,
        genre="Science Fiction",
        year=1999,
        min_rating=7.5,
        season=1,
        episode=2,
    )
    client = RecordingCatalog({})

    run(execute_catalog_plan(plan, client, filters=filters))

    assert all(request.limit == 7 for request in client.requests)
    assert all(request.filters == filters for request in client.requests)


def test_adapter_enforces_limit_when_client_returns_too_many_items() -> None:
    plan = plan_catalog_queries("Matrix", per_attempt_limit=2)
    client = RecordingCatalog(
        {
            "Matrix": (
                {"id": "1", "name": "Matrix"},
                {"id": "2", "name": "Matrix Reloaded"},
                {"id": "3", "name": "Matrix Revolutions"},
            )
        }
    )

    execution = run(execute_catalog_plan(plan, client))

    assert [item.item_id for item in execution.candidate_pool.candidates][:2] == ["1", "2"]
    assert "3" not in [item.item_id for item in execution.candidate_pool.candidates]
    assert execution.server_overflow_item_count == 1


def test_primary_one_word_result_skips_joined_word_fallbacks() -> None:
    plan = plan_catalog_queries("Matrix")
    client = RecordingCatalog(
        {"Matrix": ({"id": "movie", "name": "Matrix"},)}
    )

    execution = run(execute_catalog_plan(plan, client))

    assert [request.term for request in client.requests] == ["Matrix"]
    assert execution.stop_reason is CatalogExecutionStopReason.PRIMARY_RESULTS_FOUND
    assert not execution.partial


def test_primary_two_word_result_skips_hyphenated_fallback() -> None:
    plan = plan_catalog_queries("Jurassic Park")
    client = RecordingCatalog(
        {"Jurassic Park": ({"id": "movie", "name": "Jurassic Park"},)}
    )

    execution = run(execute_catalog_plan(plan, client))

    assert [request.term for request in client.requests] == [
        "Jurassic Park",
        "JurassicPark",
    ]
    assert execution.stop_reason is CatalogExecutionStopReason.PRIMARY_RESULTS_FOUND


def test_zero_result_joined_word_uses_first_successful_split_and_stops() -> None:
    plan = plan_catalog_queries("runaround")
    client = RecordingCatalog(
        {"run around": ({"id": "song", "name": "Run-Around"},)}
    )

    execution = run(execute_catalog_plan(plan, client))

    assert [request.term for request in client.requests] == [
        "runaround",
        "run around",
    ]
    assert execution.stop_reason is CatalogExecutionStopReason.FALLBACK_RESULT_FOUND
    assert not execution.partial




def test_zero_result_joined_word_uses_hyphenated_split_and_stops() -> None:
    plan = plan_catalog_queries("runaround")
    client = RecordingCatalog(
        {"run-around": ({"id": "song", "name": "Run-Around"},)}
    )

    execution = run(execute_catalog_plan(plan, client))

    assert [request.term for request in client.requests] == [
        "runaround",
        "run around",
        "run-around",
    ]
    assert execution.stop_reason is CatalogExecutionStopReason.FALLBACK_RESULT_FOUND
    assert not execution.partial

def test_results_are_deduplicated_and_keep_attempt_provenance() -> None:
    plan = plan_catalog_queries("run-around")
    client = RecordingCatalog(
        {
            "run-around": ({"id": "song", "name": "Run-Around"},),
            "run around": ({"id": "song", "name": "Run-Around"},),
            "runaround": ({"id": "song", "name": "Run-Around"},),
        }
    )

    execution = run(execute_catalog_plan(plan, client))

    assert len(execution.candidate_pool.candidates) == 1
    assert len(execution.candidate_pool.candidates[0].sources) == 3
    assert execution.candidate_pool.duplicate_item_count == 2


def test_execution_stops_when_unique_candidate_limit_is_reached() -> None:
    plan = plan_catalog_queries(
        "three am",
        per_attempt_limit=3,
        max_unique_candidates=2,
    )
    client = RecordingCatalog(
        {
            "three am": (
                {"id": "1", "name": "3AM"},
                {"id": "2", "name": "Three"},
            ),
            "3 am": ({"id": "3", "name": "3 A.M."},),
        }
    )

    execution = run(execute_catalog_plan(plan, client))

    assert [request.term for request in client.requests] == ["three am"]
    assert execution.stop_reason is CatalogExecutionStopReason.CANDIDATE_LIMIT_REACHED
    assert execution.partial


def test_duplicates_do_not_falsely_fill_unique_candidate_limit() -> None:
    plan = plan_catalog_queries("run-around", max_unique_candidates=2)
    client = RecordingCatalog(
        {
            "run-around": ({"id": "song", "name": "Run-Around"},),
            "run around": ({"id": "song", "name": "Run-Around"},),
            "runaround": ({"id": "other", "name": "Runaround Sue"},),
        }
    )

    execution = run(execute_catalog_plan(plan, client))

    assert [request.term for request in client.requests] == [
        "run-around",
        "run around",
        "runaround",
    ]
    assert execution.stop_reason is CatalogExecutionStopReason.CANDIDATE_LIMIT_REACHED


def test_client_error_is_fail_fast_by_default() -> None:
    plan = plan_catalog_queries("Matrix")
    client = RecordingCatalog({"Matrix": RuntimeError("server unavailable")})

    with pytest.raises(CatalogRetrievalError, match="server unavailable") as error:
        run(execute_catalog_plan(plan, client))

    assert error.value.attempt.term == "Matrix"
    assert isinstance(error.value.cause, RuntimeError)


def test_continue_on_error_records_failure_and_uses_later_attempts() -> None:
    plan = plan_catalog_queries("three am")
    client = RecordingCatalog(
        {
            "three am": RuntimeError("temporary failure"),
            "3 am": ({"id": "song", "name": "3AM"},),
        }
    )

    execution = run(
        execute_catalog_plan(plan, client, continue_on_error=True)
    )

    assert len(execution.failures) == 1
    assert execution.failures[0].attempt.term == "three am"
    assert execution.failures[0].error_type == "RuntimeError"
    assert [candidate.item_id for candidate in execution.candidate_pool.candidates] == ["song"]
    assert execution.partial


def test_nonsequence_client_response_is_rejected() -> None:
    plan = plan_catalog_queries("Matrix")

    async def invalid(_request: CatalogSearchRequest) -> Any:
        return {"items": []}

    with pytest.raises(CatalogRetrievalError, match="sequence of mappings"):
        run(execute_catalog_plan(plan, invalid))


def test_nonmapping_result_item_is_rejected() -> None:
    plan = plan_catalog_queries("Matrix")

    async def invalid(_request: CatalogSearchRequest) -> Any:
        return ["not a mapping"]

    with pytest.raises(CatalogRetrievalError, match="items must be mappings"):
        run(execute_catalog_plan(plan, invalid))


def test_transformed_jellyha_item_maps_to_media_candidate() -> None:
    plan = plan_catalog_queries("3AM")
    pool = aggregate_catalog_results(
        plan,
        (
            CatalogAttemptResult(
                attempt=plan.attempts[0],
                items=(
                    {
                        "id": "song",
                        "name": "3AM",
                        "type": "Audio",
                        "artist_name": "Matchbox Twenty",
                        "album": "Yourself or Someone Like You",
                        "year": 1996,
                    },
                ),
            ),
        ),
    )

    converted = convert_catalog_pool(pool)
    candidate = converted.candidates[0]

    assert candidate.key == "song"
    assert candidate.title == "3AM"
    assert candidate.media_type == "Audio"
    assert candidate.artist == "Matchbox Twenty"
    assert candidate.album == "Yourself or Someone Like You"
    assert candidate.year == 1996


def test_raw_jellyfin_item_maps_to_media_candidate() -> None:
    plan = plan_catalog_queries("Matrix")
    pool = aggregate_catalog_results(
        plan,
        (
            CatalogAttemptResult(
                attempt=plan.attempts[0],
                items=(
                    {
                        "Id": "movie",
                        "Name": "The Matrix",
                        "Type": "Movie",
                        "ProductionYear": 1999,
                    },
                ),
            ),
        ),
    )

    candidate = convert_catalog_pool(pool).candidates[0]

    assert candidate.key == "movie"
    assert candidate.title == "The Matrix"
    assert candidate.media_type == "Movie"
    assert candidate.year == 1999


def test_artist_list_is_used_when_direct_artist_fields_are_missing() -> None:
    plan = plan_catalog_queries("One")
    pool = aggregate_catalog_results(
        plan,
        (
            CatalogAttemptResult(
                attempt=plan.attempts[0],
                items=({"Id": "song", "Name": "One", "Artists": ["Metallica"]},),
            ),
        ),
    )

    assert convert_catalog_pool(pool).candidates[0].artist == "Metallica"


def test_series_name_is_mapped_for_episode_context() -> None:
    plan = plan_catalog_queries("Pilot")
    pool = aggregate_catalog_results(
        plan,
        (
            CatalogAttemptResult(
                attempt=plan.attempts[0],
                items=(
                    {
                        "Id": "episode",
                        "Name": "Pilot",
                        "Type": "Episode",
                        "SeriesName": "Supernatural",
                    },
                ),
            ),
        ),
    )

    assert convert_catalog_pool(pool).candidates[0].series == "Supernatural"


def test_missing_title_is_reported_and_skipped() -> None:
    plan = plan_catalog_queries("Matrix")
    pool = aggregate_catalog_results(
        plan,
        (
            CatalogAttemptResult(
                attempt=plan.attempts[0],
                items=({"id": "missing-title", "type": "Movie"},),
            ),
        ),
    )

    converted = convert_catalog_pool(pool)

    assert converted.candidates == ()
    assert converted.issues[0].item_id == "missing-title"
    assert converted.issues[0].reason is CandidateMappingIssueReason.MISSING_TITLE


def test_three_am_retrieval_reaches_known_regression_match() -> None:
    client = RecordingCatalog(
        {
            "3am": (
                {
                    "id": "song",
                    "name": "3AM",
                    "type": "Audio",
                    "artist_name": "Matchbox Twenty",
                },
            )
        }
    )

    outcome = run(
        retrieve_rank_and_decide(
            "three am",
            client,
            context=MediaSearchContext(media_type="Audio"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_catalog_candidate is not None
    assert outcome.selected_catalog_candidate.item_id == "song"
    assert [request.term for request in client.requests] == ["three am", "3 am", "3am"]


def test_joined_runaround_query_is_retrieved_by_split_fallback() -> None:
    client = RecordingCatalog(
        {"run around": ({"id": "song", "name": "Run-Around", "type": "Audio"},)}
    )

    outcome = run(
        retrieve_rank_and_decide(
            "runaround",
            client,
            context=MediaSearchContext(media_type="Audio"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_catalog_candidate is not None
    assert outcome.selected_catalog_candidate.item_id == "song"
    assert [request.term for request in client.requests] == [
        "runaround",
        "run around",
    ]
    assert outcome.selected_catalog_candidate.sources[0].term == "run around"




def test_joined_runaround_query_is_retrieved_by_hyphenated_fallback() -> None:
    client = RecordingCatalog(
        {"run-around": ({"id": "song", "name": "Run-Around", "type": "Audio"},)}
    )

    outcome = run(
        retrieve_rank_and_decide(
            "runaround",
            client,
            context=MediaSearchContext(media_type="Audio"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_catalog_candidate is not None
    assert outcome.selected_catalog_candidate.item_id == "song"
    assert [request.term for request in client.requests] == [
        "runaround",
        "run around",
        "run-around",
    ]
    assert outcome.selected_catalog_candidate.sources[0].term == "run-around"

def test_runaround_candidate_found_by_spacing_variant_is_selected() -> None:
    client = RecordingCatalog(
        {"runaround": ({"id": "song", "name": "Run-Around", "type": "Audio"},)}
    )

    outcome = run(
        retrieve_rank_and_decide(
            "run around",
            client,
            context=MediaSearchContext(media_type="Audio"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_catalog_candidate is not None
    assert outcome.selected_catalog_candidate.sources[0].term == "runaround"
    assert [request.term for request in client.requests] == [
        "run around",
        "runaround",
    ]


def test_spaced_run_around_query_uses_hyphenated_fallback() -> None:
    client = RecordingCatalog(
        {"run-around": ({"id": "song", "name": "Run-Around", "type": "Audio"},)}
    )

    outcome = run(
        retrieve_rank_and_decide(
            "run around",
            client,
            context=MediaSearchContext(media_type="Audio"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_catalog_candidate is not None
    assert outcome.selected_catalog_candidate.item_id == "song"
    assert [request.term for request in client.requests] == [
        "run around",
        "runaround",
        "run-around",
    ]
    assert outcome.selected_catalog_candidate.sources[0].term == "run-around"


def test_equal_catalog_titles_remain_ambiguous() -> None:
    client = RecordingCatalog(
        {
            "The Matrix": (
                {"id": "copy-a", "name": "The Matrix", "type": "Movie"},
                {"id": "copy-b", "name": "The Matrix", "type": "Movie"},
            )
        }
    )

    outcome = run(
        retrieve_rank_and_decide(
            "The Matrix",
            client,
            context=MediaSearchContext(media_type="Movie"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.AMBIGUOUS
    assert outcome.decision.reason is SearchDecisionReason.TOP_SCORE_TIED
    assert outcome.selected_catalog_candidate is None


def test_artist_context_disambiguates_equal_song_titles() -> None:
    client = RecordingCatalog(
        {
            "One": (
                {"id": "metallica", "name": "One", "type": "Audio", "artist_name": "Metallica"},
                {"id": "u2", "name": "One", "type": "Audio", "artist_name": "U2"},
            )
        }
    )

    outcome = run(
        retrieve_rank_and_decide(
            "One",
            client,
            context=MediaSearchContext(media_type="Audio", artist="Metallica"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_catalog_candidate is not None
    assert outcome.selected_catalog_candidate.item_id == "metallica"


def test_fuzzy_matching_stays_local_and_is_not_added_to_server_plan() -> None:
    client = RecordingCatalog(
        {
            "jurasic park": (
                {"id": "movie", "name": "Jurassic Park", "type": "Movie"},
            )
        }
    )

    outcome = run(
        retrieve_rank_and_decide(
            "jurasic park",
            client,
            context=MediaSearchContext(media_type="Movie"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.ranking.active_family is LexicalMatchFamily.FUZZY
    assert all("jurassic" not in request.term.casefold() for request in client.requests)


def test_phonetic_matching_stays_local_and_requires_context() -> None:
    client = RecordingCatalog(
        {
            "Right Here": (
                {
                    "id": "song",
                    "name": "Write Here",
                    "type": "Audio",
                    "artist_name": "Example Artist",
                },
            )
        }
    )

    outcome = run(
        retrieve_rank_and_decide(
            "Right Here",
            client,
            context=MediaSearchContext(media_type="Audio", artist="Example Artist"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.ranking.active_family is LexicalMatchFamily.PHONETIC
    assert [request.term for request in client.requests] == ["Right Here", "RightHere"]


def test_empty_catalog_produces_not_found_decision() -> None:
    outcome = run(retrieve_rank_and_decide("Unknown Title", RecordingCatalog({})))

    assert outcome.decision.status is MatchDecisionStatus.NOT_FOUND
    assert outcome.decision.reason is SearchDecisionReason.NO_MATCHING_CANDIDATES
    assert outcome.media_candidates.candidates == ()


def test_context_media_type_is_copied_to_retrieval_filter() -> None:
    client = RecordingCatalog({})

    outcome = run(
        retrieve_rank_and_decide(
            "Matrix",
            client,
            context=MediaSearchContext(media_type="Movie", year=1999),
        )
    )

    assert outcome.filters.media_type == "Movie"
    assert all(request.filters.media_type == "Movie" for request in client.requests)
    assert all(request.filters.year is None for request in client.requests)


def test_explicit_year_filter_is_passed_when_caller_requests_it() -> None:
    client = RecordingCatalog({})

    outcome = run(
        retrieve_rank_and_decide(
            "Matrix",
            client,
            context=MediaSearchContext(media_type="Movie", year=1999),
            filters=CatalogSearchFilters(year=1999),
        )
    )

    assert outcome.filters.media_type == "Movie"
    assert outcome.filters.year == 1999


def test_conflicting_filter_and_context_media_types_are_rejected() -> None:
    with pytest.raises(ValueError, match="conflicts"):
        run(
            retrieve_rank_and_decide(
                "One",
                RecordingCatalog({}),
                context=MediaSearchContext(media_type="Audio"),
                filters=CatalogSearchFilters(media_type="Movie"),
            )
        )
