"""Context-aware ranking for catalog-backed media-title matches.

Title matching remains the authority for candidate creation.  Explicit artist,
album, series, year, and media-type context can only rank candidates that the
title pipeline already found.  Text context accepts deterministic equivalence,
safe whole-token fragments, and the same controlled lexical typo patterns used
for titles.  It never performs arbitrary substring, semantic, or phonetic
matching.

Title and context scores remain separate in every result.  A known media-type
contradiction is hard rejected, while unrelated artist/album/series metadata is
kept as visible negative evidence so it cannot be silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Iterable

from .deterministic import (
    DeterministicMatchMethod,
    DeterministicTitleMatch,
    classify_deterministic_match,
    classify_title_fragment_match,
)
from .fuzzy import FuzzyMatchMethod, FuzzyTitleMatch, classify_fuzzy_match
from .normalization import VariantMethod, build_text_profile


class ContextField(StrEnum):
    """Metadata fields that can influence candidate ranking."""

    MEDIA_TYPE = "media_type"
    ARTIST = "artist"
    ALBUM = "album"
    SERIES = "series"
    YEAR = "year"


class ContextRelation(StrEnum):
    """How candidate metadata relates to explicitly supplied context."""

    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class MediaSearchContext:
    """Optional context supplied with a media search request."""

    media_type: str | None = None
    artist: str | None = None
    album: str | None = None
    series: str | None = None
    year: int | str | None = None


@dataclass(frozen=True, slots=True)
class MediaCandidate:
    """A catalog candidate with fields relevant to ranking."""

    key: str
    title: str
    media_type: str | None = None
    artist: str | None = None
    album: str | None = None
    series: str | None = None
    year: int | str | None = None
    title_aliases: tuple[str, ...] = ()
    provider_ids: tuple[tuple[str, str], ...] = ()
    physical_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextEvidence:
    """One transparent metadata comparison and its score adjustment."""

    field: ContextField
    requested: str
    candidate: str | None
    relation: ContextRelation
    adjustment: int
    method: DeterministicMatchMethod | FuzzyMatchMethod | None = None


@dataclass(frozen=True, slots=True)
class RankedMediaCandidate:
    """A title match plus separate context and combined ranking scores."""

    candidate: MediaCandidate
    title_match: DeterministicTitleMatch
    context_score: int
    total_score: int
    evidence: tuple[ContextEvidence, ...]

    @property
    def contradiction_count(self) -> int:
        """Return the number of explicitly supplied fields that conflict."""

        return sum(
            item.relation is ContextRelation.MISMATCH for item in self.evidence
        )

    @property
    def has_context_contradiction(self) -> bool:
        """Return whether any supplied non-type metadata conflicts."""

        return self.contradiction_count > 0


@dataclass(frozen=True, slots=True)
class RejectedMediaCandidate:
    """A title-matching candidate rejected by a hard context constraint."""

    candidate: MediaCandidate
    title_match: DeterministicTitleMatch
    reason: str
    evidence: tuple[ContextEvidence, ...]


@dataclass(frozen=True, slots=True)
class ContextRanking:
    """Context-ranked candidates and hard-rejection diagnostics."""

    query: str
    context: MediaSearchContext
    matches: tuple[RankedMediaCandidate, ...]
    rejected: tuple[RejectedMediaCandidate, ...]

    @property
    def top_score(self) -> int | None:
        """Return the highest combined score, if anything matched."""

        return self.matches[0].total_score if self.matches else None

    @property
    def top_score_is_unique(self) -> bool:
        """Return whether exactly one candidate owns the highest score."""

        if not self.matches:
            return False
        if len(self.matches) == 1:
            return True
        return self.matches[0].total_score > self.matches[1].total_score

    @property
    def top_margin(self) -> int | None:
        """Return the first-to-second combined-score margin when measurable."""

        if len(self.matches) < 2:
            return None
        return self.matches[0].total_score - self.matches[1].total_score


_MEDIA_TYPE_MATCH_BONUS = 8
_TEXT_FIELD_BONUS: dict[ContextField, int] = {
    ContextField.ARTIST: 10,
    ContextField.ALBUM: 7,
    ContextField.SERIES: 10,
}
_TEXT_FIELD_MISMATCH: dict[ContextField, int] = {
    ContextField.ARTIST: -12,
    ContextField.ALBUM: -9,
    ContextField.SERIES: -12,
}
_YEAR_MATCH_BONUS = 7
_YEAR_MISMATCH = -10

_NON_ALPHANUMERIC_RE = re.compile(r"[^a-z0-9]+")
_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _display(value: int | str | None) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _normalize_media_type(value: str) -> str:
    """Normalize type spelling without introducing semantic aliases."""

    return _NON_ALPHANUMERIC_RE.sub("", value.casefold())


def _normalize_year(value: int | str) -> str | None:
    """Return a four-digit year when the supplied value contains one."""

    text = str(value).strip()
    match = _YEAR_RE.search(text)
    return match.group(1) if match else None


def _context_bonus(
    base_bonus: int,
    method: DeterministicMatchMethod,
) -> int:
    """Slightly discount more invasive deterministic context equivalence."""

    discounts = {
        DeterministicMatchMethod.EXACT_ORIGINAL: 0,
        DeterministicMatchMethod.UNICODE_CASEFOLD: 0,
        DeterministicMatchMethod.DIACRITIC_FOLD: 1,
        DeterministicMatchMethod.PUNCTUATION_SPACING: 1,
        DeterministicMatchMethod.NUMBER_EQUIVALENT: 2,
        DeterministicMatchMethod.STYLIZED_NUMBER_ALIAS: 2,
        DeterministicMatchMethod.COMPACT_SPACING: 2,
        DeterministicMatchMethod.TITLE_FRAGMENT: 3,
    }
    return max(1, base_bonus - discounts[method])


def _compare_media_type(
    requested: str,
    candidate: str | None,
) -> ContextEvidence:
    candidate_display = _display(candidate)
    if candidate_display is None:
        return ContextEvidence(
            field=ContextField.MEDIA_TYPE,
            requested=requested,
            candidate=None,
            relation=ContextRelation.MISSING,
            adjustment=0,
        )

    matches = _normalize_media_type(requested) == _normalize_media_type(candidate_display)
    return ContextEvidence(
        field=ContextField.MEDIA_TYPE,
        requested=requested,
        candidate=candidate_display,
        relation=ContextRelation.MATCH if matches else ContextRelation.MISMATCH,
        adjustment=_MEDIA_TYPE_MATCH_BONUS if matches else 0,
    )


_FUZZY_CONTEXT_DISCOUNTS: dict[FuzzyMatchMethod, int] = {
    FuzzyMatchMethod.ADJACENT_TRANSPOSITION: 3,
    FuzzyMatchMethod.ADJACENT_KEY_SUBSTITUTION: 3,
    FuzzyMatchMethod.SINGLE_EDIT: 4,
    FuzzyMatchMethod.LIMITED_MULTI_EDIT: 6,
}


def _context_fuzzy_bonus(
    base_bonus: int,
    method: FuzzyMatchMethod,
) -> int:
    """Return a conservative positive signal for controlled context typos."""

    return max(1, base_bonus - _FUZZY_CONTEXT_DISCOUNTS[method])


def _token_sequences(value: str) -> tuple[tuple[str, ...], ...]:
    """Return safe normalized token sequences for context-window matching.

    Context may be incomplete and misspelled at the same time, such as
    ``dave mathews`` for ``Dave Matthews Band``.  The normal fuzzy matcher
    compares complete strings, so this helper exposes same-width contiguous
    token windows without falling back to unsafe arbitrary substrings.
    """

    output: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for variant in build_text_profile(value).variants:
        if VariantMethod.COMPACT_SPACING in variant.methods:
            continue
        tokens = tuple(variant.value.split())
        if not tokens or tokens in seen:
            continue
        seen.add(tokens)
        output.append(tokens)
    return tuple(output)


def _best_fuzzy_context_match(
    requested: str,
    candidate: str,
) -> FuzzyTitleMatch | None:
    """Return full-field or contiguous-window controlled fuzzy evidence."""

    matches: list[FuzzyTitleMatch] = []
    full_match = classify_fuzzy_match(requested, candidate)
    if full_match is not None:
        matches.append(full_match)

    for requested_tokens in _token_sequences(requested):
        for candidate_tokens in _token_sequences(candidate):
            requested_count = len(requested_tokens)
            candidate_count = len(candidate_tokens)
            if requested_count == candidate_count:
                continue

            if requested_count < candidate_count:
                requested_value = " ".join(requested_tokens)
                for index in range(candidate_count - requested_count + 1):
                    candidate_value = " ".join(
                        candidate_tokens[index : index + requested_count]
                    )
                    match = classify_fuzzy_match(requested_value, candidate_value)
                    if match is not None:
                        matches.append(match)
            else:
                candidate_value = " ".join(candidate_tokens)
                for index in range(requested_count - candidate_count + 1):
                    requested_value = " ".join(
                        requested_tokens[index : index + candidate_count]
                    )
                    match = classify_fuzzy_match(requested_value, candidate_value)
                    if match is not None:
                        matches.append(match)

    if not matches:
        return None
    return max(
        matches,
        key=lambda match: (
            match.lexical_score,
            match.similarity,
            -match.edit_distance,
        ),
    )


def _compare_text_field(
    field: ContextField,
    requested: str,
    candidate: str | None,
) -> ContextEvidence:
    candidate_display = _display(candidate)
    if candidate_display is None:
        return ContextEvidence(
            field=field,
            requested=requested,
            candidate=None,
            relation=ContextRelation.MISSING,
            adjustment=0,
        )

    deterministic = classify_deterministic_match(requested, candidate_display)
    if deterministic is not None:
        return ContextEvidence(
            field=field,
            requested=requested,
            candidate=candidate_display,
            relation=ContextRelation.MATCH,
            adjustment=_context_bonus(
                _TEXT_FIELD_BONUS[field], deterministic.method
            ),
            method=deterministic.method,
        )

    # Context is supporting evidence, so safe whole-token containment may run
    # in either direction.  This accepts ``Dave Matthews`` for
    # ``Dave Matthews Band`` and harmless extra qualifiers in the request.
    fragment = classify_title_fragment_match(requested, candidate_display)
    if fragment is None:
        fragment = classify_title_fragment_match(candidate_display, requested)
    if fragment is not None:
        return ContextEvidence(
            field=field,
            requested=requested,
            candidate=candidate_display,
            relation=ContextRelation.MATCH,
            adjustment=_context_bonus(_TEXT_FIELD_BONUS[field], fragment.method),
            method=fragment.method,
        )

    fuzzy = _best_fuzzy_context_match(requested, candidate_display)
    if fuzzy is not None:
        return ContextEvidence(
            field=field,
            requested=requested,
            candidate=candidate_display,
            relation=ContextRelation.MATCH,
            adjustment=_context_fuzzy_bonus(
                _TEXT_FIELD_BONUS[field], fuzzy.method
            ),
            method=fuzzy.method,
        )

    return ContextEvidence(
        field=field,
        requested=requested,
        candidate=candidate_display,
        relation=ContextRelation.MISMATCH,
        adjustment=_TEXT_FIELD_MISMATCH[field],
    )


def _compare_year(
    requested: int | str,
    candidate: int | str | None,
) -> ContextEvidence:
    requested_display = _display(requested)
    assert requested_display is not None
    requested_year = _normalize_year(requested)

    candidate_display = _display(candidate)
    if candidate_display is None:
        return ContextEvidence(
            field=ContextField.YEAR,
            requested=requested_display,
            candidate=None,
            relation=ContextRelation.MISSING,
            adjustment=0,
        )

    candidate_year = _normalize_year(candidate)
    matches = (
        requested_year is not None
        and candidate_year is not None
        and requested_year == candidate_year
    )
    return ContextEvidence(
        field=ContextField.YEAR,
        requested=requested_display,
        candidate=candidate_display,
        relation=ContextRelation.MATCH if matches else ContextRelation.MISMATCH,
        adjustment=_YEAR_MATCH_BONUS if matches else _YEAR_MISMATCH,
    )


def evaluate_media_context(
    context: MediaSearchContext,
    candidate: MediaCandidate,
) -> tuple[ContextEvidence, ...]:
    """Compare explicit search context with one catalog candidate.

    This public helper keeps context evidence reusable by later lexical layers
    without allowing metadata to create a title match on its own.
    """

    evidence: list[ContextEvidence] = []

    if _display(context.media_type) is not None:
        evidence.append(_compare_media_type(str(context.media_type).strip(), candidate.media_type))
    if _display(context.artist) is not None:
        evidence.append(
            _compare_text_field(
                ContextField.ARTIST,
                str(context.artist).strip(),
                candidate.artist,
            )
        )
    if _display(context.album) is not None:
        evidence.append(
            _compare_text_field(
                ContextField.ALBUM,
                str(context.album).strip(),
                candidate.album,
            )
        )
    if _display(context.series) is not None:
        evidence.append(
            _compare_text_field(
                ContextField.SERIES,
                str(context.series).strip(),
                candidate.series,
            )
        )
    if _display(context.year) is not None:
        assert context.year is not None
        evidence.append(_compare_year(context.year, candidate.year))

    return tuple(evidence)


def rank_context_candidates(
    query: str,
    candidates: Iterable[MediaCandidate],
    context: MediaSearchContext | None = None,
) -> ContextRanking:
    """Rank deterministic title matches using explicit catalog context.

    Candidates whose titles do not deterministically match are outside this
    stage and are omitted.  A supplied media type is a hard constraint when the
    candidate has a known, contradictory type.  Missing candidate metadata is
    retained with a neutral adjustment so incomplete libraries are not treated
    as definitely wrong.
    """

    active_context = context or MediaSearchContext()
    ranked: list[RankedMediaCandidate] = []
    rejected: list[RejectedMediaCandidate] = []

    for candidate in candidates:
        title_match = classify_deterministic_match(query, candidate.title)
        if title_match is None:
            continue

        evidence = evaluate_media_context(active_context, candidate)
        type_mismatch = next(
            (
                item
                for item in evidence
                if item.field is ContextField.MEDIA_TYPE
                and item.relation is ContextRelation.MISMATCH
            ),
            None,
        )
        if type_mismatch is not None:
            rejected.append(
                RejectedMediaCandidate(
                    candidate=candidate,
                    title_match=title_match,
                    reason="media_type_mismatch",
                    evidence=evidence,
                )
            )
            continue

        context_score = sum(item.adjustment for item in evidence)
        ranked.append(
            RankedMediaCandidate(
                candidate=candidate,
                title_match=title_match,
                context_score=context_score,
                total_score=title_match.score + context_score,
                evidence=evidence,
            )
        )

    # Stable sorting preserves catalog order when both combined and title
    # scores tie, rather than manufacturing a winner from an unrelated field.
    ranked.sort(
        key=lambda item: (item.total_score, item.title_match.score),
        reverse=True,
    )
    return ContextRanking(
        query=query,
        context=active_context,
        matches=tuple(ranked),
        rejected=tuple(rejected),
    )
