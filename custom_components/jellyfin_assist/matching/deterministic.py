"""Deterministic classification and scoring for media-title matches.

This module compares only representations produced by the deterministic
normalization layer. It deliberately performs no edit-distance, keyboard,
phonetic, catalog-alias, context, confidence-threshold, or automatic-selection
logic. Scores express the relative strength of deterministic equivalence
methods; they are not probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .normalization import (
    SharedVariant,
    VariantMethod,
    build_text_profile,
    find_shared_variants,
)


class DeterministicMatchMethod(StrEnum):
    """The strongest deterministic equivalence found for a title pair."""

    EXACT_ORIGINAL = "exact_original"
    UNICODE_CASEFOLD = "unicode_casefold"
    DIACRITIC_FOLD = "diacritic_fold"
    PUNCTUATION_SPACING = "punctuation_spacing"
    NUMBER_EQUIVALENT = "number_equivalent"
    STYLIZED_NUMBER_ALIAS = "stylized_number_alias"
    COMPACT_SPACING = "compact_spacing"
    TITLE_FRAGMENT = "title_fragment"
    ARTICLE_OMISSION_FRAGMENT = "article_omission_fragment"


# These are deliberately centralized and conservative. They establish ordering
# only; future confidence decisions must also consider context, ambiguity, and
# the margin over alternatives.
_METHOD_SCORES: dict[DeterministicMatchMethod, int] = {
    DeterministicMatchMethod.EXACT_ORIGINAL: 100,
    DeterministicMatchMethod.UNICODE_CASEFOLD: 99,
    DeterministicMatchMethod.DIACRITIC_FOLD: 97,
    DeterministicMatchMethod.PUNCTUATION_SPACING: 95,
    DeterministicMatchMethod.NUMBER_EQUIVALENT: 93,
    DeterministicMatchMethod.STYLIZED_NUMBER_ALIAS: 90,
    DeterministicMatchMethod.COMPACT_SPACING: 88,
    DeterministicMatchMethod.TITLE_FRAGMENT: 76,
    DeterministicMatchMethod.ARTICLE_OMISSION_FRAGMENT: 74,
}

_VARIANT_RISK: dict[VariantMethod, DeterministicMatchMethod] = {
    VariantMethod.ORIGINAL: DeterministicMatchMethod.EXACT_ORIGINAL,
    VariantMethod.UNICODE_CASEFOLD: DeterministicMatchMethod.UNICODE_CASEFOLD,
    VariantMethod.DIACRITIC_FOLD: DeterministicMatchMethod.DIACRITIC_FOLD,
    VariantMethod.PUNCTUATION_SPACING: DeterministicMatchMethod.PUNCTUATION_SPACING,
    VariantMethod.NUMBER_WORDS_TO_DIGITS: DeterministicMatchMethod.NUMBER_EQUIVALENT,
    VariantMethod.NUMERIC_ORDINAL_SPACING: DeterministicMatchMethod.NUMBER_EQUIVALENT,
    VariantMethod.NUMERIC_ORDINAL_TO_WORDS: DeterministicMatchMethod.NUMBER_EQUIVALENT,
    VariantMethod.COMPACT_SPACING: DeterministicMatchMethod.COMPACT_SPACING,
}


@dataclass(frozen=True, slots=True)
class DeterministicTitleMatch:
    """A deterministic match between a query and one candidate title."""

    query: str
    candidate_title: str
    method: DeterministicMatchMethod
    score: int
    shared_value: str
    query_methods: tuple[VariantMethod, ...]
    candidate_methods: tuple[VariantMethod, ...]


@dataclass(frozen=True, slots=True)
class TitleCandidate:
    """A candidate identity and display title supplied by a future catalog."""

    key: str
    title: str


@dataclass(frozen=True, slots=True)
class RankedTitleCandidate:
    """One candidate paired with its deterministic title match."""

    candidate: TitleCandidate
    match: DeterministicTitleMatch


@dataclass(frozen=True, slots=True)
class DeterministicRanking:
    """Ranked deterministic matches plus explicit ambiguity diagnostics."""

    query: str
    matches: tuple[RankedTitleCandidate, ...]

    @property
    def top_score(self) -> int | None:
        """Return the highest score, or ``None`` when nothing matched."""

        return self.matches[0].match.score if self.matches else None

    @property
    def top_score_is_unique(self) -> bool:
        """Return whether exactly one candidate owns the highest score."""

        if not self.matches:
            return False
        if len(self.matches) == 1:
            return True
        return self.matches[0].match.score > self.matches[1].match.score

    @property
    def top_margin(self) -> int | None:
        """Return the first-to-second score margin when two matches exist.

        A single matched candidate has no measured competitor, so this returns
        ``None`` rather than implying an infinite or automatically safe margin.
        """

        if len(self.matches) < 2:
            return None
        return self.matches[0].match.score - self.matches[1].match.score


def score_for_method(method: DeterministicMatchMethod) -> int:
    """Return the configured relative score for a deterministic method."""

    return _METHOD_SCORES[method]


def _best_side_method(
    methods: tuple[VariantMethod, ...],
) -> DeterministicMatchMethod:
    """Return the least invasive method known to produce one side's value."""

    return max((_VARIANT_RISK[method] for method in methods), key=score_for_method)


def _method_for_shared_variant(shared: SharedVariant) -> DeterministicMatchMethod:
    """Classify a shared value by the weaker of its two best derivations.

    A profile can record several methods for the same value when later
    transformations are no-ops. We therefore choose the least invasive known
    derivation independently for each side, then classify the pair by whichever
    side required the more invasive transformation.
    """

    left_method = _best_side_method(shared.left_methods)
    right_method = _best_side_method(shared.right_methods)
    return min((left_method, right_method), key=score_for_method)


def classify_deterministic_match(
    query: str,
    candidate_title: str,
) -> DeterministicTitleMatch | None:
    """Return the strongest deterministic match for a title pair, if any."""

    query_profile = build_text_profile(query)
    candidate_profile = build_text_profile(candidate_title)

    if query_profile.original == candidate_profile.original:
        return DeterministicTitleMatch(
            query=query_profile.original,
            candidate_title=candidate_profile.original,
            method=DeterministicMatchMethod.EXACT_ORIGINAL,
            score=score_for_method(DeterministicMatchMethod.EXACT_ORIGINAL),
            shared_value=query_profile.original,
            query_methods=(VariantMethod.ORIGINAL,),
            candidate_methods=(VariantMethod.ORIGINAL,),
        )

    shared_variants = find_shared_variants(query_profile, candidate_profile)
    if not shared_variants:
        return None

    classified = [
        (
            score_for_method(method := _method_for_shared_variant(shared)),
            score_for_method(_best_side_method(shared.right_methods)),
            score_for_method(_best_side_method(shared.left_methods)),
            method,
            shared,
        )
        for shared in shared_variants
    ]
    score, _candidate_score, _query_score, method, shared = max(
        classified,
        key=lambda item: item[:3],
    )

    return DeterministicTitleMatch(
        query=query_profile.original,
        candidate_title=candidate_profile.original,
        method=method,
        score=score,
        shared_value=shared.value,
        query_methods=shared.left_methods,
        candidate_methods=shared.right_methods,
    )



def _fragment_tokens(value: str) -> tuple[str, ...]:
    """Return normalized whole-word tokens for deterministic containment.

    Text profiles already provide case, diacritic, punctuation, and numeric
    variants.  Compact-spacing variants are intentionally excluded by callers
    because fragment matching must respect token boundaries.
    """

    return tuple(value.split())


def _contains_token_sequence(
    candidate_tokens: tuple[str, ...],
    query_tokens: tuple[str, ...],
) -> bool:
    """Return whether ``query_tokens`` occur contiguously in the candidate."""

    if not query_tokens or len(query_tokens) >= len(candidate_tokens):
        return False
    width = len(query_tokens)
    return any(
        candidate_tokens[index : index + width] == query_tokens
        for index in range(len(candidate_tokens) - width + 1)
    )


_OMISSIBLE_ARTICLES = frozenset({"a", "an", "the"})


def _contains_token_sequence_with_one_internal_article_omission(
    candidate_tokens: tuple[str, ...],
    query_tokens: tuple[str, ...],
) -> tuple[str, ...] | None:
    """Return the matched candidate span when one internal article is omitted.

    This is intentionally narrower than stop-word removal. The candidate may
    contain exactly one additional ``a``, ``an``, or ``the`` inside the matched
    span, and every other token must match the query exactly and in order. The
    omitted article must have matched tokens on both sides, so ``Thing`` does
    not become equivalent to ``The Thing`` merely because the catalog contains
    no exact ``Thing`` title.
    """

    if len(query_tokens) < 3:
        return None

    span_width = len(query_tokens) + 1
    if span_width > len(candidate_tokens):
        return None

    for start in range(len(candidate_tokens) - span_width + 1):
        span = candidate_tokens[start : start + span_width]
        for omitted_index in range(1, len(span) - 1):
            if span[omitted_index] not in _OMISSIBLE_ARTICLES:
                continue
            if span[:omitted_index] + span[omitted_index + 1 :] == query_tokens:
                return span
    return None


def classify_title_fragment_match(
    query: str,
    candidate_title: str,
) -> DeterministicTitleMatch | None:
    """Return a safe whole-token title-fragment match, if one exists.

    This is deliberately narrower than substring matching: ``planet`` may
    match ``Planet Terror``, while ``plan`` does not match ``Planet``.  At
    least three alphanumeric characters are required, and the candidate must
    contain more tokens than the query so full-title equivalence remains the
    responsibility of :func:`classify_deterministic_match`.
    """

    query_profile = build_text_profile(query)
    candidate_profile = build_text_profile(candidate_title)
    matches: list[tuple[int, int, str, tuple[VariantMethod, ...], tuple[VariantMethod, ...]]] = []

    for query_variant in query_profile.variants:
        if query_variant.methods == (VariantMethod.COMPACT_SPACING,):
            continue
        query_tokens = _fragment_tokens(query_variant.value)
        if sum(len(token) for token in query_tokens) < 3:
            continue

        for candidate_variant in candidate_profile.variants:
            if candidate_variant.methods == (VariantMethod.COMPACT_SPACING,):
                continue
            candidate_tokens = _fragment_tokens(candidate_variant.value)
            if not _contains_token_sequence(candidate_tokens, query_tokens):
                continue

            query_strength = score_for_method(_best_side_method(query_variant.methods))
            candidate_strength = score_for_method(
                _best_side_method(candidate_variant.methods)
            )
            matches.append(
                (
                    min(query_strength, candidate_strength),
                    candidate_strength,
                    " ".join(query_tokens),
                    query_variant.methods,
                    candidate_variant.methods,
                )
            )

    if not matches:
        return None

    _pair_strength, _candidate_strength, shared_value, query_methods, candidate_methods = max(
        matches, key=lambda item: item[:2]
    )
    method = DeterministicMatchMethod.TITLE_FRAGMENT
    return DeterministicTitleMatch(
        query=query_profile.original,
        candidate_title=candidate_profile.original,
        method=method,
        score=score_for_method(method),
        shared_value=shared_value,
        query_methods=query_methods,
        candidate_methods=candidate_methods,
    )


def classify_article_omission_fragment_match(
    query: str,
    candidate_title: str,
) -> DeterministicTitleMatch | None:
    """Return a conservative fragment match with one omitted internal article.

    The normal title-fragment classifier remains stronger and should be tried
    first. This fallback exists for speech-to-text omissions such as
    ``The Anatomy of tongue in cheek`` versus
    ``The Anatomy of the Tongue In Cheek (Gold Edition)``. It does not remove
    articles globally and does not permit missing content words, reordered
    words, or leading/trailing article differences.
    """

    query_profile = build_text_profile(query)
    candidate_profile = build_text_profile(candidate_title)
    matches: list[
        tuple[
            int,
            int,
            str,
            tuple[VariantMethod, ...],
            tuple[VariantMethod, ...],
        ]
    ] = []

    for query_variant in query_profile.variants:
        if query_variant.methods == (VariantMethod.COMPACT_SPACING,):
            continue
        query_tokens = _fragment_tokens(query_variant.value)
        if sum(len(token) for token in query_tokens) < 3:
            continue
        if sum(token not in _OMISSIBLE_ARTICLES for token in query_tokens) < 2:
            continue

        for candidate_variant in candidate_profile.variants:
            if candidate_variant.methods == (VariantMethod.COMPACT_SPACING,):
                continue
            candidate_tokens = _fragment_tokens(candidate_variant.value)
            span = _contains_token_sequence_with_one_internal_article_omission(
                candidate_tokens,
                query_tokens,
            )
            if span is None:
                continue

            query_strength = score_for_method(_best_side_method(query_variant.methods))
            candidate_strength = score_for_method(
                _best_side_method(candidate_variant.methods)
            )
            matches.append(
                (
                    min(query_strength, candidate_strength),
                    candidate_strength,
                    " ".join(span),
                    query_variant.methods,
                    candidate_variant.methods,
                )
            )

    if not matches:
        return None

    (
        _pair_strength,
        _candidate_strength,
        shared_value,
        query_methods,
        candidate_methods,
    ) = max(matches, key=lambda item: item[:2])
    method = DeterministicMatchMethod.ARTICLE_OMISSION_FRAGMENT
    return DeterministicTitleMatch(
        query=query_profile.original,
        candidate_title=candidate_profile.original,
        method=method,
        score=score_for_method(method),
        shared_value=shared_value,
        query_methods=query_methods,
        candidate_methods=candidate_methods,
    )

def rank_deterministic_candidates(
    query: str,
    candidates: Iterable[TitleCandidate],
) -> DeterministicRanking:
    """Score and rank candidates while preserving input order for ties.

    Preserving tie order is intentional: this stage must not manufacture a
    winner through alphabetical sorting or another unrelated tiebreaker.
    """

    ranked: list[RankedTitleCandidate] = []

    for candidate in candidates:
        match = classify_deterministic_match(query, candidate.title)
        if match is None:
            continue
        ranked.append(RankedTitleCandidate(candidate=candidate, match=match))

    ranked.sort(key=lambda item: item.match.score, reverse=True)
    return DeterministicRanking(query=query, matches=tuple(ranked))
