"""Read-only in-memory Jellyfin catalog index and local search.

Jellyfin's ``SearchTerm`` behavior is intentionally treated as an optional fast
path, not the authority for robust title matching.  This module builds a small
metadata-only index from raw or JellyHA-transformed item dictionaries and feeds
bounded local candidates into the existing tiered ranking and confidence
engine.

The index never downloads media or images and never mutates Jellyfin.  It stores
only the item payload supplied by a future read-only catalog loader plus
precomputed title variants, tokens, and character n-grams used for candidate
shortlisting.  Shortlisting cannot create a match; deterministic, fuzzy, and
phonetic ranking still make the final decision.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
import re
import unicodedata
from typing import Any

from ..matching.context import MediaCandidate, MediaSearchContext
from ..matching.normalization import TextProfile, build_text_profile
from ..matching.pipeline import (
    SearchDecision,
    SearchRanking,
    decide_search_ranking,
    rank_search_candidates,
)
from .items import (
    catalog_item_id,
    catalog_item_to_media_candidate,
    trusted_logical_group_key,
)


_NON_ALPHANUMERIC_RE = re.compile(r"[^a-z0-9]+")
_LEADING_ARTICLES = frozenset({"a", "an", "the"})


class CatalogIndexIssueReason(StrEnum):
    """Why an input item was not added to the immutable index."""

    INVALID_ITEM = "invalid_item"
    MISSING_ID = "missing_id"
    MISSING_TITLE = "missing_title"
    DUPLICATE_ID = "duplicate_id"


class CatalogShortlistMethod(StrEnum):
    """How a record entered one local ranking shortlist."""

    DETERMINISTIC_VARIANT = "deterministic_variant"
    TOKEN_ANCHOR = "token_anchor"
    CHARACTER_NGRAM = "character_ngram"
    SMALL_TYPE_SCAN = "small_type_scan"


@dataclass(frozen=True, slots=True)
class CatalogIndexIssue:
    """One skipped catalog input and its stable diagnostic reason."""

    input_position: int
    reason: CatalogIndexIssueReason
    item_id: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogIndexRecord:
    """One logical catalog entity and its physical Jellyfin records."""

    position: int
    item_id: str
    item: Mapping[str, Any]
    physical_item_ids: tuple[str, ...]
    physical_items: tuple[Mapping[str, Any], ...]
    provider_ids: tuple[tuple[str, str], ...]
    logical_group_key: str | None
    candidate: MediaCandidate
    profile: TextProfile
    alias_profiles: tuple[TextProfile, ...]
    tokens: frozenset[str]
    ngrams: frozenset[str]

    @property
    def is_logical_group(self) -> bool:
        """Return whether multiple physical Jellyfin records form this entity."""

        return len(self.physical_item_ids) > 1


@dataclass(frozen=True, slots=True)
class CatalogShortlistEntry:
    """One record selected for full ranking plus retrieval-free evidence."""

    record: CatalogIndexRecord
    methods: tuple[CatalogShortlistMethod, ...]
    token_overlap: int
    ngram_overlap: int
    ngram_similarity: float


@dataclass(frozen=True, slots=True)
class LocalCatalogSearchOutcome:
    """Local shortlist, tiered ranking, and conservative search decision."""

    query: str
    context: MediaSearchContext
    eligible_record_count: int
    shortlist: tuple[CatalogShortlistEntry, ...]
    ranking: SearchRanking
    decision: SearchDecision

    @property
    def selected_record(self) -> CatalogIndexRecord | None:
        """Return the indexed raw item corresponding to an allowed selection."""

        if self.decision.selected is None:
            return None
        selected_key = self.decision.selected.candidate.key
        for entry in self.shortlist:
            if entry.record.item_id == selected_key:
                return entry.record
        return None


@dataclass(slots=True)
class _ShortlistEvidence:
    methods: set[CatalogShortlistMethod]
    token_overlap: int = 0
    ngram_overlap: int = 0
    ngram_similarity: float = 0.0


def _canonical_text(value: str) -> str:
    """Return lowercase, diacritic-folded, punctuation-spaced text."""

    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(_NON_ALPHANUMERIC_RE.sub(" ", without_marks).split())


def _tokens(value: str) -> frozenset[str]:
    return frozenset(_canonical_text(value).split())


def _compact(value: str) -> str:
    return "".join(_canonical_text(value).split())


def _character_ngrams(value: str) -> frozenset[str]:
    """Return conservative bigram/trigram keys for typo shortlisting.

    N-grams only nominate candidates; they never affect the final lexical score
    or confidence threshold.  Including bigrams protects adjacent
    transpositions in short titles, while trigrams reduce broad collisions in
    longer titles.
    """

    compact = _compact(value)
    if len(compact) < 2:
        return frozenset()

    output = {
        f"2:{compact[index:index + 2]}"
        for index in range(len(compact) - 1)
    }
    if len(compact) >= 5:
        output.update(
            f"3:{compact[index:index + 3]}"
            for index in range(len(compact) - 2)
        )
    return frozenset(output)


def _normalize_media_type(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _NON_ALPHANUMERIC_RE.sub("", value.casefold()) or None


def _query_anchor_tokens(query: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _tokens(query)
        if len(token) >= 3 and token not in _LEADING_ARTICLES
    )


class CatalogIndex:
    """Immutable metadata index built from one Jellyfin catalog snapshot."""

    __slots__ = (
        "records",
        "issues",
        "raw_item_count",
        "_records_by_id",
        "_variant_index",
        "_token_index",
        "_ngram_index",
        "_media_type_index",
    )

    def __init__(
        self,
        *,
        records: tuple[CatalogIndexRecord, ...],
        issues: tuple[CatalogIndexIssue, ...],
        raw_item_count: int,
    ) -> None:
        self.records = records
        self.issues = issues
        self.raw_item_count = raw_item_count
        self._records_by_id = {
            physical_id: record
            for record in records
            for physical_id in record.physical_item_ids
        }

        variant_index: dict[str, list[str]] = defaultdict(list)
        token_index: dict[str, list[str]] = defaultdict(list)
        ngram_index: dict[str, list[str]] = defaultdict(list)
        media_type_index: dict[str, list[str]] = defaultdict(list)

        for record in records:
            for profile in (record.profile, *record.alias_profiles):
                for value in profile.values:
                    variant_index[value].append(record.item_id)
            for token in record.tokens:
                token_index[token].append(record.item_id)
            for ngram in record.ngrams:
                ngram_index[ngram].append(record.item_id)
            media_type = _normalize_media_type(record.candidate.media_type)
            if media_type is not None:
                media_type_index[media_type].append(record.item_id)

        self._variant_index = {
            key: tuple(values) for key, values in variant_index.items()
        }
        self._token_index = {key: tuple(values) for key, values in token_index.items()}
        self._ngram_index = {key: tuple(values) for key, values in ngram_index.items()}
        self._media_type_index = {
            key: tuple(values) for key, values in media_type_index.items()
        }

    @property
    def logical_group_count(self) -> int:
        """Return the number of indexed entities containing multiple IDs."""

        return sum(record.is_logical_group for record in self.records)

    @property
    def grouped_physical_item_count(self) -> int:
        """Return physical records absorbed into trusted logical groups."""

        return sum(
            len(record.physical_item_ids) - 1
            for record in self.records
            if record.is_logical_group
        )

    @classmethod
    def build(cls, items: Iterable[Mapping[str, Any]]) -> "CatalogIndex":
        """Build a physical-ID-deduplicated, conservatively grouped index.

        The first logical grouping rule is intentionally narrow: multiple
        ``MusicArtist`` records sharing the same trusted MusicBrainz artist ID
        become one logical record.  All physical IDs and payloads remain
        available for future artist expansion and diagnostics.
        """

        records: list[CatalogIndexRecord] = []
        issues: list[CatalogIndexIssue] = []
        seen_ids: set[str] = set()
        logical_group_positions: dict[str, int] = {}
        raw_item_count = 0

        for input_position, item in enumerate(items):
            raw_item_count += 1
            if not isinstance(item, Mapping):
                issues.append(
                    CatalogIndexIssue(
                        input_position=input_position,
                        reason=CatalogIndexIssueReason.INVALID_ITEM,
                    )
                )
                continue

            copied = dict(item)
            item_id = catalog_item_id(copied)
            if item_id is None:
                issues.append(
                    CatalogIndexIssue(
                        input_position=input_position,
                        reason=CatalogIndexIssueReason.MISSING_ID,
                    )
                )
                continue
            if item_id in seen_ids:
                issues.append(
                    CatalogIndexIssue(
                        input_position=input_position,
                        reason=CatalogIndexIssueReason.DUPLICATE_ID,
                        item_id=item_id,
                    )
                )
                continue

            candidate = catalog_item_to_media_candidate(copied, item_id=item_id)
            if candidate is None:
                issues.append(
                    CatalogIndexIssue(
                        input_position=input_position,
                        reason=CatalogIndexIssueReason.MISSING_TITLE,
                        item_id=item_id,
                    )
                )
                continue

            seen_ids.add(item_id)
            logical_group_key = trusted_logical_group_key(
                copied, candidate.media_type
            )
            existing_position = (
                logical_group_positions.get(logical_group_key)
                if logical_group_key is not None
                else None
            )
            if existing_position is not None:
                existing = records[existing_position]
                merged_provider_ids = tuple(
                    sorted(set(existing.provider_ids) | set(candidate.provider_ids))
                )
                merged_physical_ids = existing.physical_item_ids + (item_id,)
                merged_candidate = replace(
                    existing.candidate,
                    provider_ids=merged_provider_ids,
                    physical_keys=merged_physical_ids,
                )
                records[existing_position] = replace(
                    existing,
                    physical_item_ids=merged_physical_ids,
                    physical_items=existing.physical_items + (copied,),
                    provider_ids=merged_provider_ids,
                    candidate=merged_candidate,
                )
                continue

            alias_profiles = tuple(
                build_text_profile(alias) for alias in candidate.title_aliases
            )
            record = CatalogIndexRecord(
                position=len(records),
                item_id=item_id,
                item=copied,
                physical_item_ids=(item_id,),
                physical_items=(copied,),
                provider_ids=candidate.provider_ids,
                logical_group_key=logical_group_key,
                candidate=candidate,
                profile=build_text_profile(candidate.title),
                alias_profiles=alias_profiles,
                tokens=frozenset().union(
                    _tokens(candidate.title),
                    *(_tokens(alias) for alias in candidate.title_aliases),
                ),
                ngrams=frozenset().union(
                    _character_ngrams(candidate.title),
                    *(
                        _character_ngrams(alias)
                        for alias in candidate.title_aliases
                    ),
                ),
            )
            records.append(record)
            if logical_group_key is not None:
                logical_group_positions[logical_group_key] = record.position

        return cls(
            records=tuple(records),
            issues=tuple(issues),
            raw_item_count=raw_item_count,
        )

    def get(self, item_id: str) -> CatalogIndexRecord | None:
        """Return one indexed record by Jellyfin ID."""

        return self._records_by_id.get(item_id)

    def _eligible_ids(self, context: MediaSearchContext) -> tuple[str, ...]:
        media_type = _normalize_media_type(context.media_type)
        if media_type is None:
            return tuple(record.item_id for record in self.records)
        return self._media_type_index.get(media_type, ())

    def search(
        self,
        query: str,
        *,
        context: MediaSearchContext | None = None,
        max_shortlist: int = 200,
        small_type_scan_limit: int = 250,
    ) -> LocalCatalogSearchOutcome:
        """Shortlist local records, then run the existing safe ranking pipeline.

        Exact deterministic variant hits are exhaustive for that tier and are
        preferred.  Otherwise exact anchor tokens and character n-grams nominate
        a bounded fuzzy/phonetic pool.  Very small eligible catalogs may be
        scanned in full when no index signal exists.
        """

        if not isinstance(query, str):
            raise TypeError("query must be a string")
        query = " ".join(query.split())
        if not query:
            raise ValueError("query must not be empty")
        if max_shortlist <= 0:
            raise ValueError("max_shortlist must be positive")
        if small_type_scan_limit < 0:
            raise ValueError("small_type_scan_limit must not be negative")

        active_context = context or MediaSearchContext()
        eligible_ids = self._eligible_ids(active_context)
        eligible = set(eligible_ids)
        evidence: dict[str, _ShortlistEvidence] = {}

        query_profile = build_text_profile(query)
        deterministic_ids: set[str] = set()
        for value in query_profile.values:
            deterministic_ids.update(self._variant_index.get(value, ()))
        deterministic_ids.intersection_update(eligible)

        if deterministic_ids:
            for item_id in deterministic_ids:
                evidence[item_id] = _ShortlistEvidence(
                    methods={CatalogShortlistMethod.DETERMINISTIC_VARIANT}
                )
        else:
            anchor_tokens = _query_anchor_tokens(query)
            anchor_counts: dict[str, int] = defaultdict(int)
            for token in anchor_tokens:
                for item_id in self._token_index.get(token, ()):
                    if item_id in eligible:
                        anchor_counts[item_id] += 1

            for item_id, overlap in anchor_counts.items():
                evidence[item_id] = _ShortlistEvidence(
                    methods={CatalogShortlistMethod.TOKEN_ANCHOR},
                    token_overlap=overlap,
                )

            query_ngrams = _character_ngrams(query)
            ngram_counts: dict[str, int] = defaultdict(int)
            for ngram in query_ngrams:
                for item_id in self._ngram_index.get(ngram, ()):
                    if item_id in eligible:
                        ngram_counts[item_id] += 1

            minimum_overlap = 1 if len(_compact(query)) <= 7 else 2
            for item_id, overlap in ngram_counts.items():
                if overlap < minimum_overlap:
                    continue
                record = self._records_by_id[item_id]
                union_size = len(query_ngrams | record.ngrams)
                similarity = overlap / union_size if union_size else 0.0
                if similarity < 0.12:
                    continue
                item_evidence = evidence.setdefault(
                    item_id,
                    _ShortlistEvidence(methods=set()),
                )
                item_evidence.methods.add(CatalogShortlistMethod.CHARACTER_NGRAM)
                item_evidence.ngram_overlap = overlap
                item_evidence.ngram_similarity = similarity

            if not evidence and len(eligible_ids) <= small_type_scan_limit:
                for item_id in eligible_ids:
                    evidence[item_id] = _ShortlistEvidence(
                        methods={CatalogShortlistMethod.SMALL_TYPE_SCAN}
                    )

        def sort_key(item_id: str) -> tuple[float, ...]:
            item_evidence = evidence[item_id]
            deterministic = (
                CatalogShortlistMethod.DETERMINISTIC_VARIANT
                in item_evidence.methods
            )
            record = self._records_by_id[item_id]
            return (
                -int(deterministic),
                -item_evidence.token_overlap,
                -item_evidence.ngram_similarity,
                -item_evidence.ngram_overlap,
                record.position,
            )

        ordered_ids = sorted(evidence, key=sort_key)[:max_shortlist]
        shortlist = tuple(
            CatalogShortlistEntry(
                record=self._records_by_id[item_id],
                methods=tuple(sorted(evidence[item_id].methods, key=str)),
                token_overlap=evidence[item_id].token_overlap,
                ngram_overlap=evidence[item_id].ngram_overlap,
                ngram_similarity=evidence[item_id].ngram_similarity,
            )
            for item_id in ordered_ids
        )

        ranking = rank_search_candidates(
            query,
            (entry.record.candidate for entry in shortlist),
            active_context,
        )
        decision = decide_search_ranking(ranking)
        return LocalCatalogSearchOutcome(
            query=query,
            context=active_context,
            eligible_record_count=len(eligible_ids),
            shortlist=shortlist,
            ranking=ranking,
            decision=decision,
        )
