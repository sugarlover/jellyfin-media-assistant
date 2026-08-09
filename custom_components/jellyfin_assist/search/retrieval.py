"""Mockable catalog retrieval and ranking orchestration.

This module is the first end-to-end *pure Python* search path.  It executes a
bounded :class:`~.planning.CatalogQueryPlan` through an injected asynchronous
catalog client, aggregates raw or transformed Jellyfin items by ID, converts
those items into the matching engine's catalog shape, and returns a conservative
ranking decision.

It deliberately has no Home Assistant imports and no concrete Jellyfin client.
The injected callable is the seam that a later Home Assistant action adapter
will implement.  Tests can therefore exercise request ordering, filters,
partial failures, deduplication, candidate provenance, ranking, and confidence
without contacting a real server.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from ..matching.context import MediaCandidate, MediaSearchContext
from ..matching.pipeline import (
    SearchDecision,
    SearchRanking,
    decide_search_ranking,
    rank_search_candidates,
)
from .items import catalog_item_to_media_candidate
from .planning import (
    CatalogAttemptResult,
    CatalogCandidate,
    CatalogCandidatePool,
    CatalogQueryAttempt,
    CatalogQueryPlan,
    aggregate_catalog_results,
    plan_catalog_queries,
)


CatalogSearchCallable = Callable[
    ["CatalogSearchRequest"],
    Awaitable[Sequence[Mapping[str, Any]]],
]


@dataclass(frozen=True, slots=True)
class CatalogSearchFilters:
    """Optional server-side filters supported by the current JellyHA search.

    These are retrieval constraints, not ranking context.  In particular, a
    requested year remains ranking context unless the caller explicitly places
    it here as a hard Jellyfin filter.
    """

    media_type: str | None = None
    is_played: bool | None = None
    is_favorite: bool | None = None
    genre: str | None = None
    year: int | None = None
    min_rating: float | None = None
    season: int | None = None
    episode: int | None = None


@dataclass(frozen=True, slots=True)
class CatalogSearchRequest:
    """One concrete request sent to an injected catalog client."""

    attempt: CatalogQueryAttempt
    limit: int
    filters: CatalogSearchFilters

    @property
    def term(self) -> str:
        """Return the Jellyfin ``SearchTerm`` value for this request."""

        return self.attempt.term


@dataclass(frozen=True, slots=True)
class CatalogAttemptFailure:
    """Serializable diagnostics for one failed planned attempt."""

    attempt: CatalogQueryAttempt
    error_type: str
    message: str


class CatalogExecutionStopReason(StrEnum):
    """Why retrieval stopped executing planned attempts."""

    PLAN_COMPLETE = "plan_complete"
    CANDIDATE_LIMIT_REACHED = "candidate_limit_reached"
    PRIMARY_RESULTS_FOUND = "primary_results_found"
    FALLBACK_RESULT_FOUND = "fallback_result_found"


@dataclass(frozen=True, slots=True)
class CatalogExecution:
    """Executed requests, candidate pool, and retrieval diagnostics."""

    plan: CatalogQueryPlan
    requests: tuple[CatalogSearchRequest, ...]
    attempt_results: tuple[CatalogAttemptResult, ...]
    failures: tuple[CatalogAttemptFailure, ...]
    candidate_pool: CatalogCandidatePool
    stop_reason: CatalogExecutionStopReason
    server_overflow_item_count: int

    @property
    def completed_attempt_count(self) -> int:
        """Return the number of attempted server calls, including failures."""

        return len(self.requests)

    @property
    def successful_attempt_count(self) -> int:
        """Return the number of calls that returned a valid result sequence."""

        return len(self.attempt_results)

    @property
    def partial(self) -> bool:
        """Whether one or more planned attempts failed or were not executed."""

        return bool(self.failures) or (
            self.stop_reason is CatalogExecutionStopReason.CANDIDATE_LIMIT_REACHED
        )


class CatalogRetrievalError(RuntimeError):
    """Raised when a catalog attempt fails in fail-fast mode."""

    def __init__(self, attempt: CatalogQueryAttempt, cause: Exception) -> None:
        self.attempt = attempt
        self.cause = cause
        super().__init__(
            f"catalog attempt {attempt.index} for {attempt.term!r} failed: {cause}"
        )


class CandidateMappingIssueReason(StrEnum):
    """Why a deduplicated catalog item could not enter local ranking."""

    MISSING_TITLE = "missing_title"


@dataclass(frozen=True, slots=True)
class CandidateMappingIssue:
    """One catalog item skipped while building matching-engine candidates."""

    item_id: str
    reason: CandidateMappingIssueReason


@dataclass(frozen=True, slots=True)
class CatalogCandidateMapping:
    """Link one raw catalog candidate to its matching-engine representation."""

    catalog_candidate: CatalogCandidate
    media_candidate: MediaCandidate


@dataclass(frozen=True, slots=True)
class CatalogMediaCandidates:
    """Converted matching candidates plus transparent conversion diagnostics."""

    mappings: tuple[CatalogCandidateMapping, ...]
    issues: tuple[CandidateMappingIssue, ...]

    @property
    def candidates(self) -> tuple[MediaCandidate, ...]:
        """Return matching-engine candidates in catalog discovery order."""

        return tuple(mapping.media_candidate for mapping in self.mappings)


@dataclass(frozen=True, slots=True)
class CatalogSearchOutcome:
    """One complete pure search execution, ranking, and decision."""

    query: str
    context: MediaSearchContext
    filters: CatalogSearchFilters
    execution: CatalogExecution
    media_candidates: CatalogMediaCandidates
    ranking: SearchRanking
    decision: SearchDecision

    @property
    def selected_catalog_candidate(self) -> CatalogCandidate | None:
        """Return the raw selected Jellyfin candidate when selection is allowed."""

        if self.decision.selected is None:
            return None
        selected_key = self.decision.selected.candidate.key
        for mapping in self.media_candidates.mappings:
            if mapping.media_candidate.key == selected_key:
                return mapping.catalog_candidate
        return None


async def execute_catalog_plan(
    plan: CatalogQueryPlan,
    search: CatalogSearchCallable,
    *,
    filters: CatalogSearchFilters | None = None,
    continue_on_error: bool = False,
    stop_when_candidate_limit_reached: bool = True,
) -> CatalogExecution:
    """Execute planned attempts sequentially through an injected client.

    Sequential execution preserves deterministic request ordering and makes the
    candidate provenance diagnostics easy to understand.  The adapter enforces
    ``per_attempt_limit`` locally even if a future client or server ignores it.

    By default any client failure raises :class:`CatalogRetrievalError`; this
    avoids silently turning an unavailable Jellyfin server into a misleading
    ``not_found`` result.  Tests and future callers may opt into partial results
    with ``continue_on_error=True``.
    """

    active_filters = filters or CatalogSearchFilters()
    requests: list[CatalogSearchRequest] = []
    results: list[CatalogAttemptResult] = []
    failures: list[CatalogAttemptFailure] = []
    server_overflow_item_count = 0
    stop_reason = CatalogExecutionStopReason.PLAN_COMPLETE

    for attempt in plan.attempts:
        if attempt.fallback_only and any(result.items for result in results):
            stop_reason = CatalogExecutionStopReason.PRIMARY_RESULTS_FOUND
            break

        request = CatalogSearchRequest(
            attempt=attempt,
            limit=plan.per_attempt_limit,
            filters=active_filters,
        )
        requests.append(request)

        try:
            returned = await search(request)
            if isinstance(returned, (str, bytes)) or not isinstance(returned, Sequence):
                raise TypeError("catalog client must return a sequence of mappings")
            if any(not isinstance(item, Mapping) for item in returned):
                raise TypeError("catalog client result items must be mappings")
        except Exception as err:
            if not continue_on_error:
                raise CatalogRetrievalError(attempt, err) from err
            failures.append(
                CatalogAttemptFailure(
                    attempt=attempt,
                    error_type=type(err).__name__,
                    message=str(err),
                )
            )
            continue

        accepted = tuple(dict(item) for item in returned[: plan.per_attempt_limit])
        server_overflow_item_count += max(0, len(returned) - len(accepted))
        results.append(CatalogAttemptResult(attempt=attempt, items=accepted))

        if stop_when_candidate_limit_reached:
            interim = aggregate_catalog_results(plan, tuple(results))
            if len(interim.candidates) >= plan.max_unique_candidates:
                stop_reason = CatalogExecutionStopReason.CANDIDATE_LIMIT_REACHED
                break

        if attempt.fallback_only and accepted:
            stop_reason = CatalogExecutionStopReason.FALLBACK_RESULT_FOUND
            break

    pool = aggregate_catalog_results(plan, tuple(results))
    return CatalogExecution(
        plan=plan,
        requests=tuple(requests),
        attempt_results=tuple(results),
        failures=tuple(failures),
        candidate_pool=pool,
        stop_reason=stop_reason,
        server_overflow_item_count=server_overflow_item_count,
    )


def convert_catalog_pool(pool: CatalogCandidatePool) -> CatalogMediaCandidates:
    """Convert raw or transformed Jellyfin items into ranking candidates.

    Conversion is shared with the local catalog index through
    :func:`catalog_item_to_media_candidate`, ensuring both paths interpret item
    IDs, titles, types, artist, album, series, and year identically.
    """

    mappings: list[CatalogCandidateMapping] = []
    issues: list[CandidateMappingIssue] = []

    for catalog_candidate in pool.candidates:
        media_candidate = catalog_item_to_media_candidate(
            catalog_candidate.item,
            item_id=catalog_candidate.item_id,
        )
        if media_candidate is None:
            issues.append(
                CandidateMappingIssue(
                    item_id=catalog_candidate.item_id,
                    reason=CandidateMappingIssueReason.MISSING_TITLE,
                )
            )
            continue

        mappings.append(
            CatalogCandidateMapping(
                catalog_candidate=catalog_candidate,
                media_candidate=media_candidate,
            )
        )

    return CatalogMediaCandidates(mappings=tuple(mappings), issues=tuple(issues))


def _effective_filters(
    context: MediaSearchContext,
    filters: CatalogSearchFilters | None,
) -> CatalogSearchFilters:
    active = filters or CatalogSearchFilters()
    if context.media_type is None:
        return active
    if active.media_type is None:
        return replace(active, media_type=context.media_type)
    if active.media_type.casefold() != context.media_type.casefold():
        raise ValueError("filter media_type conflicts with ranking context media_type")
    return active


async def retrieve_rank_and_decide(
    query: str,
    search: CatalogSearchCallable,
    *,
    context: MediaSearchContext | None = None,
    filters: CatalogSearchFilters | None = None,
    max_attempts: int = 6,
    per_attempt_limit: int = 20,
    max_unique_candidates: int = 60,
    continue_on_error: bool = False,
    stop_when_candidate_limit_reached: bool = True,
) -> CatalogSearchOutcome:
    """Plan, retrieve, deduplicate, rank, and decide one media query.

    An explicit media type is copied from ranking context into retrieval filters
    because media type is the one hard context constraint in the matching
    engine.  Other metadata remains local ranking context unless callers
    explicitly supply it as a server-side filter.
    """

    active_context = context or MediaSearchContext()
    active_filters = _effective_filters(active_context, filters)
    plan = plan_catalog_queries(
        query,
        max_attempts=max_attempts,
        per_attempt_limit=per_attempt_limit,
        max_unique_candidates=max_unique_candidates,
    )
    execution = await execute_catalog_plan(
        plan,
        search,
        filters=active_filters,
        continue_on_error=continue_on_error,
        stop_when_candidate_limit_reached=stop_when_candidate_limit_reached,
    )
    media_candidates = convert_catalog_pool(execution.candidate_pool)
    ranking = rank_search_candidates(
        plan.original_query,
        media_candidates.candidates,
        active_context,
    )
    decision = decide_search_ranking(ranking)

    return CatalogSearchOutcome(
        query=plan.original_query,
        context=active_context,
        filters=active_filters,
        execution=execution,
        media_candidates=media_candidates,
        ranking=ranking,
        decision=decision,
    )
