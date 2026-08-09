"""Pure catalog-query planning and candidate-pool aggregation.

This module does not call Home Assistant or Jellyfin.  It converts one user
query into a small, ordered set of deterministic Jellyfin ``SearchTerm``
attempts and combines the returned batches into a bounded, deduplicated
candidate pool for the ranking pipeline.

The planner intentionally emits only reversible or clearly labeled variants.
Fuzzy and phonetic spellings are not sent to the server.  Those lower-confidence
methods are reserved for local comparison after catalog candidates are fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
import re
import unicodedata

from ..matching.normalization import VariantMethod, build_text_profile


_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)
_LEADING_ARTICLES = frozenset({"a", "an", "the"})


class CatalogQueryMethod(StrEnum):
    """Reason a server-side catalog query was attempted."""

    ORIGINAL = "original"
    UNICODE_COMPATIBILITY = "unicode_compatibility"
    DIACRITIC_FOLD = "diacritic_fold"
    PUNCTUATION_SPACING = "punctuation_spacing"
    NUMBER_EQUIVALENT = "number_equivalent"
    COMPACT_SPACING = "compact_spacing"
    HYPHENATED_SPACING = "hyphenated_spacing"
    JOINED_WORD_SPLIT = "joined_word_split"


_METHOD_PRIORITY = {
    CatalogQueryMethod.ORIGINAL: 0,
    CatalogQueryMethod.UNICODE_COMPATIBILITY: 1,
    CatalogQueryMethod.DIACRITIC_FOLD: 2,
    CatalogQueryMethod.PUNCTUATION_SPACING: 3,
    CatalogQueryMethod.NUMBER_EQUIVALENT: 4,
    CatalogQueryMethod.COMPACT_SPACING: 5,
    CatalogQueryMethod.HYPHENATED_SPACING: 6,
    CatalogQueryMethod.JOINED_WORD_SPLIT: 7,
}


@dataclass(frozen=True, slots=True)
class CatalogQueryAttempt:
    """One ordered Jellyfin catalog search attempt.

    ``fallback_only`` attempts are intentionally deferred until all primary
    deterministic attempts return no items.  This keeps joined-word recovery
    from slowing ordinary one-word searches that Jellyfin already resolves.
    """

    index: int
    term: str
    methods: tuple[CatalogQueryMethod, ...]
    fallback_only: bool = False


@dataclass(frozen=True, slots=True)
class CatalogQueryPlan:
    """Bounded plan used by a later Jellyfin adapter."""

    original_query: str
    attempts: tuple[CatalogQueryAttempt, ...]
    per_attempt_limit: int
    max_unique_candidates: int

    @property
    def attempted_terms(self) -> tuple[str, ...]:
        """Return search terms in execution order."""

        return tuple(attempt.term for attempt in self.attempts)


@dataclass(frozen=True, slots=True)
class CatalogAttemptResult:
    """Items returned for one planned attempt.

    ``items`` deliberately retains generic mappings so this pure module can be
    used with raw Jellyfin dictionaries or already transformed JellyHA items.
    """

    attempt: CatalogQueryAttempt
    items: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class CatalogCandidateSource:
    """Where one catalog candidate appeared."""

    attempt_index: int
    term: str
    result_position: int


@dataclass(frozen=True, slots=True)
class CatalogCandidate:
    """One unique catalog item and every query attempt that returned it."""

    item_id: str
    item: Mapping[str, Any]
    sources: tuple[CatalogCandidateSource, ...]


@dataclass(frozen=True, slots=True)
class CatalogCandidatePool:
    """Bounded, deduplicated catalog candidates plus retrieval diagnostics."""

    candidates: tuple[CatalogCandidate, ...]
    raw_item_count: int
    duplicate_item_count: int
    invalid_item_count: int
    dropped_unique_count: int
    max_unique_candidates: int

    @property
    def truncated(self) -> bool:
        """Whether unique candidates were dropped because the pool was full."""

        return self.dropped_unique_count > 0


@dataclass(slots=True)
class _MutableCandidate:
    item_id: str
    item: Mapping[str, Any]
    sources: list[CatalogCandidateSource]


def _collapse_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _query_dedupe_key(value: str) -> str:
    """Deduplicate case-only variants without hiding compatibility changes.

    NFKC is intentionally *not* applied here.  A full-width original query and
    its ASCII compatibility form must remain separate server attempts.
    """

    return _collapse_whitespace(value).casefold()


def _methods_for_variant(methods: Iterable[VariantMethod]) -> tuple[CatalogQueryMethod, ...]:
    mapped: set[CatalogQueryMethod] = set()
    method_set = set(methods)

    if VariantMethod.DIACRITIC_FOLD in method_set:
        mapped.add(CatalogQueryMethod.DIACRITIC_FOLD)
    if VariantMethod.PUNCTUATION_SPACING in method_set:
        mapped.add(CatalogQueryMethod.PUNCTUATION_SPACING)
    if (
        VariantMethod.NUMBER_WORDS_TO_DIGITS in method_set
        or VariantMethod.NUMERIC_ORDINAL_SPACING in method_set
    ):
        mapped.add(CatalogQueryMethod.NUMBER_EQUIVALENT)
    if VariantMethod.COMPACT_SPACING in method_set:
        mapped.add(CatalogQueryMethod.COMPACT_SPACING)

    return tuple(sorted(mapped, key=_METHOD_PRIORITY.__getitem__))


def _is_unicode_compatibility_variant(original: str, candidate: str) -> bool:
    compatibility = _collapse_whitespace(unicodedata.normalize("NFKC", original).casefold())
    return candidate == compatibility and _query_dedupe_key(candidate) != _query_dedupe_key(original)


def _compact_variant_is_safe(profile_original: str, value: str) -> bool:
    """Allow only compact attempts that are likely useful and bounded.

    Compact forms are useful for ``3 AM``/``3AM`` and two-token stylized titles
    such as ``Run Around``/``Runaround``.  Long phrases and article-led titles
    are not compacted into low-value server searches.
    """

    normalized = unicodedata.normalize("NFKC", profile_original).casefold()
    words = _WORD_RE.findall(normalized)
    if words and words[0] in _LEADING_ARTICLES:
        return False

    if any(char.isdigit() for char in value):
        return 2 <= len(value) <= 24

    if len(words) != 2:
        return False
    if min(map(len, words)) < 3:
        return False
    return 6 <= len(value) <= 24


def _candidate_priority(methods: tuple[CatalogQueryMethod, ...]) -> tuple[int, int]:
    if not methods:
        return (99, 99)
    return (min(_METHOD_PRIORITY[method] for method in methods), len(methods))


def _alternating_split_positions(length: int, minimum_part_length: int = 3) -> tuple[int, ...]:
    """Return bounded split positions alternating from both token edges.

    Short-prefix and short-suffix boundaries are tried early.  This puts
    ``run around``, ``spider man``, and ``super man`` near the front without a
    language-specific dictionary or an unbounded combinatorial search.
    """

    first = minimum_part_length
    last = length - minimum_part_length
    if first > last:
        return ()

    positions: list[int] = []
    while first <= last:
        positions.append(first)
        if last != first:
            positions.append(last)
        first += 1
        last -= 1
    return tuple(positions)



def _hyphenated_spacing_variants(original: str) -> tuple[str, ...]:
    """Return a cautious hyphenated fallback for a plain two-word query.

    Jellyfin 10.11 may treat title hyphens as significant during ``SearchTerm``
    retrieval.  A spoken or typed query such as ``run around`` therefore needs
    a deferred ``run-around`` attempt even though the local matcher already
    understands the forms as equivalent.

    This fallback is intentionally limited to two ordinary words, excludes
    leading articles, and requires useful token lengths.  It is marked
    ``fallback_only`` by the plan, so it is never sent when an earlier normal
    attempt already returned candidates.
    """

    normalized = _collapse_whitespace(unicodedata.normalize("NFKC", original).casefold())
    words = _WORD_RE.findall(normalized)
    if len(words) != 2:
        return ()
    if normalized != " ".join(words):
        return ()
    if words[0] in _LEADING_ARTICLES:
        return ()
    if min(map(len, words)) < 3:
        return ()
    hyphenated = "-".join(words)
    if not 6 <= len(hyphenated) <= 24:
        return ()
    return (hyphenated,)

def _joined_word_split_variants(original: str) -> tuple[str, ...]:
    """Generate cautious two-token fallbacks for one joined query token.

    Alphabetic tokens emit paired spaced and hyphenated forms for each bounded
    split position and require at least three letters on both sides.  The
    spaced form is attempted first because it is natural speech input; the
    hyphenated form follows immediately because Jellyfin may treat title
    hyphens as significant.  Mixed letter/digit tokens
    only split at an explicit character-class boundary, such as ``3am`` to
    ``3 am``.  These variants are retrieval fallbacks, not automatic matches;
    the local ranking and confidence layers still decide whether a returned
    item is safe.
    """

    token = unicodedata.normalize("NFKC", original).casefold()
    if not token or _collapse_whitespace(token) != token or not token.isalnum():
        return ()
    if not 3 <= len(token) <= 24:
        return ()

    boundary_positions = tuple(
        index
        for index in range(1, len(token))
        if token[index - 1].isdigit() != token[index].isdigit()
    )
    if boundary_positions:
        return tuple(f"{token[:index]} {token[index:]}" for index in boundary_positions)

    if not token.isalpha():
        return ()

    variants: list[str] = []
    for index in _alternating_split_positions(len(token)):
        left = token[:index]
        right = token[index:]
        # Jellyfin 10.11 may treat a title hyphen as significant during
        # SearchTerm retrieval.  Try the human-readable spaced form first,
        # then the equivalent hyphenated form before considering another
        # split boundary.  Retrieval stops after the first successful
        # fallback, so later speculative boundaries are normally never sent.
        variants.extend((f"{left} {right}", f"{left}-{right}"))
    return tuple(variants)


def plan_catalog_queries(
    query: str,
    *,
    max_attempts: int = 6,
    per_attempt_limit: int = 20,
    max_unique_candidates: int = 60,
) -> CatalogQueryPlan:
    """Create an ordered, deduplicated Jellyfin search plan.

    The original query is always first.  Remaining attempts are deterministic
    normalization variants ordered from lower to higher transformation risk.

    Raises:
        TypeError: If ``query`` is not a string.
        ValueError: If the query is empty or any limit is not positive.
    """

    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if per_attempt_limit <= 0:
        raise ValueError("per_attempt_limit must be positive")
    if max_unique_candidates <= 0:
        raise ValueError("max_unique_candidates must be positive")

    profile = build_text_profile(query)
    original = profile.original

    pending: list[tuple[int, str, tuple[CatalogQueryMethod, ...]]] = []
    for sequence, variant in enumerate(profile.variants):
        if variant.value == original:
            continue

        methods = _methods_for_variant(variant.methods)
        if _is_unicode_compatibility_variant(original, variant.value):
            methods = tuple(
                sorted(
                    set(methods) | {CatalogQueryMethod.UNICODE_COMPATIBILITY},
                    key=_METHOD_PRIORITY.__getitem__,
                )
            )

        if not methods:
            continue
        if (
            CatalogQueryMethod.COMPACT_SPACING in methods
            and not _compact_variant_is_safe(original, variant.value)
        ):
            continue

        pending.append((sequence, variant.value, methods))

    fallback_sequence = len(profile.variants)
    for offset, hyphenated_variant in enumerate(_hyphenated_spacing_variants(original)):
        pending.append(
            (
                fallback_sequence + offset,
                hyphenated_variant,
                (CatalogQueryMethod.HYPHENATED_SPACING,),
            )
        )

    split_sequence = fallback_sequence + len(_hyphenated_spacing_variants(original))
    for offset, split_variant in enumerate(_joined_word_split_variants(original)):
        pending.append(
            (
                split_sequence + offset,
                split_variant,
                (CatalogQueryMethod.JOINED_WORD_SPLIT,),
            )
        )

    pending.sort(key=lambda item: (_candidate_priority(item[2]), item[0]))

    attempts: list[CatalogQueryAttempt] = [
        CatalogQueryAttempt(
            index=0,
            term=original,
            methods=(CatalogQueryMethod.ORIGINAL,),
        )
    ]
    seen = {_query_dedupe_key(original)}

    for _, term, methods in pending:
        key = _query_dedupe_key(term)
        if key in seen:
            continue
        seen.add(key)
        attempts.append(
            CatalogQueryAttempt(
                index=len(attempts),
                term=term,
                methods=methods,
                fallback_only=bool(
                    {
                        CatalogQueryMethod.HYPHENATED_SPACING,
                        CatalogQueryMethod.JOINED_WORD_SPLIT,
                    }
                    & set(methods)
                ),
            )
        )
        if len(attempts) >= max_attempts:
            break

    return CatalogQueryPlan(
        original_query=original,
        attempts=tuple(attempts),
        per_attempt_limit=per_attempt_limit,
        max_unique_candidates=max_unique_candidates,
    )


def _extract_item_id(item: Mapping[str, Any]) -> str | None:
    for key in ("id", "Id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def aggregate_catalog_results(
    plan: CatalogQueryPlan,
    results: Sequence[CatalogAttemptResult],
) -> CatalogCandidatePool:
    """Combine attempt results into a bounded ID-deduplicated candidate pool.

    First appearance determines candidate order and canonical item payload.
    Later duplicate appearances are retained as source diagnostics.
    Results may be partial—for example, when a future adapter stops early after
    reaching the candidate cap.
    """

    planned_by_index = {attempt.index: attempt for attempt in plan.attempts}
    candidates: dict[str, _MutableCandidate] = {}
    raw_item_count = 0
    duplicate_item_count = 0
    invalid_item_count = 0
    dropped_unique_ids: set[str] = set()

    for batch in results:
        planned = planned_by_index.get(batch.attempt.index)
        if planned is None or planned != batch.attempt:
            raise ValueError("result attempt does not belong to the supplied plan")

        for position, item in enumerate(batch.items):
            raw_item_count += 1
            item_id = _extract_item_id(item)
            if item_id is None:
                invalid_item_count += 1
                continue

            source = CatalogCandidateSource(
                attempt_index=batch.attempt.index,
                term=batch.attempt.term,
                result_position=position,
            )
            existing = candidates.get(item_id)
            if existing is not None:
                duplicate_item_count += 1
                existing.sources.append(source)
                continue

            if len(candidates) >= plan.max_unique_candidates:
                dropped_unique_ids.add(item_id)
                continue

            candidates[item_id] = _MutableCandidate(
                item_id=item_id,
                item=dict(item),
                sources=[source],
            )

    frozen = tuple(
        CatalogCandidate(
            item_id=candidate.item_id,
            item=candidate.item,
            sources=tuple(candidate.sources),
        )
        for candidate in candidates.values()
    )
    return CatalogCandidatePool(
        candidates=frozen,
        raw_item_count=raw_item_count,
        duplicate_item_count=duplicate_item_count,
        invalid_item_count=invalid_item_count,
        dropped_unique_count=len(dropped_unique_ids),
        max_unique_candidates=plan.max_unique_candidates,
    )
