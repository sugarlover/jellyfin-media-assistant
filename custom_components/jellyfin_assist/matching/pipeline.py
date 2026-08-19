"""Tiered title ranking and confidence decisions for media search.

This module combines deterministic, controlled fuzzy, and conservative
phonetic layers without contacting Jellyfin or Home Assistant. Matching is
tiered: deterministic equivalence is evaluated first, fuzzy matching second,
and phonetic matching only when neither stronger tier survives the hard
media-type constraint. Metadata can rank plausible title matches but cannot create one.

The output keeps lexical score, phonetic score, context score, match family,
match method, evidence, thresholds, and alternatives separate for future
diagnostics.
Scores are ranking strengths, not probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .context import (
    ContextEvidence,
    ContextField,
    ContextRelation,
    MediaCandidate,
    MediaSearchContext,
    evaluate_media_context,
)
from .decision import MatchDecisionStatus, threshold_for_method
from .deterministic import (
    DeterministicMatchMethod,
    DeterministicTitleMatch,
    classify_article_omission_fragment_match,
    classify_deterministic_match,
    classify_title_fragment_match,
    score_for_method,
)
from .fuzzy import FuzzyMatchMethod, FuzzyTitleMatch, classify_fuzzy_match
from .phonetic import (
    PhoneticMatchMethod,
    PhoneticTitleMatch,
    classify_phonetic_match,
)
from .normalization import spoken_title_signature


class LexicalMatchFamily(StrEnum):
    """The risk tier that produced a title match."""

    DETERMINISTIC = "deterministic"
    FUZZY = "fuzzy"
    PHONETIC = "phonetic"


@dataclass(frozen=True, slots=True)
class UnifiedTitleMatch:
    """One deterministic, fuzzy, or phonetic match in a diagnostic shape."""

    query: str
    candidate_title: str
    family: LexicalMatchFamily
    method: DeterministicMatchMethod | FuzzyMatchMethod | PhoneticMatchMethod
    lexical_score: int
    phonetic_score: int = 0
    deterministic: DeterministicTitleMatch | None = None
    fuzzy: FuzzyTitleMatch | None = None
    phonetic: PhoneticTitleMatch | None = None
    matched_alias: str | None = None

    @property
    def score(self) -> int:
        """Compatibility alias for generic ranking callers."""

        return self.phonetic_score if self.is_phonetic else self.lexical_score

    @property
    def is_deterministic(self) -> bool:
        return self.family is LexicalMatchFamily.DETERMINISTIC

    @property
    def is_fuzzy(self) -> bool:
        return self.family is LexicalMatchFamily.FUZZY

    @property
    def is_phonetic(self) -> bool:
        return self.family is LexicalMatchFamily.PHONETIC


@dataclass(frozen=True, slots=True)
class RankedSearchCandidate:
    """A catalog candidate with separate lexical and context scores."""

    candidate: MediaCandidate
    title_match: UnifiedTitleMatch
    context_score: int
    total_score: int
    evidence: tuple[ContextEvidence, ...]

    @property
    def contradiction_count(self) -> int:
        """Return the number of explicitly supplied metadata conflicts."""

        return sum(item.relation is ContextRelation.MISMATCH for item in self.evidence)

    @property
    def has_context_contradiction(self) -> bool:
        return self.contradiction_count > 0


@dataclass(frozen=True, slots=True)
class RejectedSearchCandidate:
    """A lexical match rejected by a hard media-type constraint."""

    candidate: MediaCandidate
    title_match: UnifiedTitleMatch
    reason: str
    evidence: tuple[ContextEvidence, ...]


@dataclass(frozen=True, slots=True)
class SearchRanking:
    """The active title tier, ranked matches, and hard rejections."""

    query: str
    context: MediaSearchContext
    active_family: LexicalMatchFamily | None
    matches: tuple[RankedSearchCandidate, ...]
    rejected: tuple[RejectedSearchCandidate, ...]

    @property
    def top_score(self) -> int | None:
        return self.matches[0].total_score if self.matches else None

    @property
    def top_score_is_unique(self) -> bool:
        if not self.matches:
            return False
        if len(self.matches) == 1:
            return True
        return self.matches[0].total_score > self.matches[1].total_score

    @property
    def top_margin(self) -> int | None:
        if len(self.matches) < 2:
            return None
        return self.matches[0].total_score - self.matches[1].total_score


@dataclass(frozen=True, slots=True)
class FuzzyConfidenceThreshold:
    """Minimum evidence required for one controlled fuzzy method."""

    minimum_total_score: int
    minimum_margin: int
    minimum_similarity: float
    minimum_single_context_score: int = 0


_FUZZY_THRESHOLDS: dict[FuzzyMatchMethod, FuzzyConfidenceThreshold] = {
    FuzzyMatchMethod.ADJACENT_TRANSPOSITION: FuzzyConfidenceThreshold(
        minimum_total_score=84,
        minimum_margin=8,
        minimum_similarity=0.82,
    ),
    FuzzyMatchMethod.ADJACENT_KEY_SUBSTITUTION: FuzzyConfidenceThreshold(
        minimum_total_score=83,
        minimum_margin=8,
        minimum_similarity=0.82,
    ),
    FuzzyMatchMethod.SINGLE_EDIT: FuzzyConfidenceThreshold(
        minimum_total_score=80,
        minimum_margin=10,
        minimum_similarity=0.84,
    ),
    FuzzyMatchMethod.LIMITED_MULTI_EDIT: FuzzyConfidenceThreshold(
        minimum_total_score=83,
        minimum_margin=12,
        minimum_similarity=0.82,
        minimum_single_context_score=7,
    ),
}


@dataclass(frozen=True, slots=True)
class PhoneticConfidenceThreshold:
    """Minimum evidence required for one phonetic method."""

    minimum_total_score: int
    minimum_margin: int
    minimum_single_context_score: int


_PHONETIC_THRESHOLDS: dict[PhoneticMatchMethod, PhoneticConfidenceThreshold] = {
    PhoneticMatchMethod.COMMON_HOMOPHONE: PhoneticConfidenceThreshold(
        minimum_total_score=82,
        minimum_margin=14,
        minimum_single_context_score=15,
    ),
    PhoneticMatchMethod.TOKEN_SIGNATURE: PhoneticConfidenceThreshold(
        minimum_total_score=78,
        minimum_margin=14,
        minimum_single_context_score=15,
    ),
}


class SearchDecisionReason(StrEnum):
    """Stable machine-readable reasons for a unified search decision."""

    UNIQUE_CONFIDENT_MATCH = "unique_confident_match"
    NO_MATCHING_CANDIDATES = "no_matching_candidates"
    TOP_SCORE_TIED = "top_score_tied"
    INSUFFICIENT_MARGIN = "insufficient_margin"
    TOP_CONTEXT_CONTRADICTION = "top_context_contradiction"
    SCORE_BELOW_THRESHOLD = "score_below_threshold"
    FUZZY_SIMILARITY_BELOW_THRESHOLD = "fuzzy_similarity_below_threshold"
    FUZZY_SINGLETON_NEEDS_CONTEXT = "fuzzy_singleton_needs_context"
    PHONETIC_SINGLETON_NEEDS_CONTEXT = "phonetic_singleton_needs_context"
    AUDIO_SPOKEN_TITLE_COLLISION = "audio_spoken_title_collision"


@dataclass(frozen=True, slots=True)
class SearchDecision:
    """A conservative selection decision over a tiered search ranking."""

    query: str
    status: MatchDecisionStatus
    reason: SearchDecisionReason
    active_family: LexicalMatchFamily | None
    selected: RankedSearchCandidate | None
    alternatives: tuple[RankedSearchCandidate, ...]
    rejected: tuple[RejectedSearchCandidate, ...]
    required_minimum_score: int | None
    required_margin: int | None
    required_minimum_similarity: float | None
    observed_margin: int | None

    @property
    def automatic_selection_allowed(self) -> bool:
        return self.status is MatchDecisionStatus.MATCHED and self.selected is not None

    @property
    def selection_required(self) -> bool:
        return self.status is MatchDecisionStatus.AMBIGUOUS


def threshold_for_fuzzy_method(method: FuzzyMatchMethod) -> FuzzyConfidenceThreshold:
    """Return the centralized threshold for a fuzzy match method."""

    return _FUZZY_THRESHOLDS[method]


def threshold_for_phonetic_method(
    method: PhoneticMatchMethod,
) -> PhoneticConfidenceThreshold:
    """Return the centralized threshold for a phonetic match method."""

    return _PHONETIC_THRESHOLDS[method]


def _classify_deterministic_or_alias(
    query: str,
    candidate_title: str,
    title_aliases: tuple[str, ...],
) -> UnifiedTitleMatch | None:
    deterministic = classify_deterministic_match(query, candidate_title)
    if deterministic is not None:
        return UnifiedTitleMatch(
            query=query,
            candidate_title=candidate_title,
            family=LexicalMatchFamily.DETERMINISTIC,
            method=deterministic.method,
            lexical_score=deterministic.score,
            deterministic=deterministic,
        )

    alias_matches = []
    for alias in title_aliases:
        alias_match = classify_deterministic_match(query, alias)
        if alias_match is None:
            continue
        alias_matches.append((alias_match.score, alias, alias_match))
    if not alias_matches:
        return None

    _score, alias, alias_match = max(alias_matches, key=lambda item: item[0])
    wrapped = DeterministicTitleMatch(
        query=alias_match.query,
        candidate_title=candidate_title,
        method=DeterministicMatchMethod.STYLIZED_NUMBER_ALIAS,
        score=score_for_method(DeterministicMatchMethod.STYLIZED_NUMBER_ALIAS),
        shared_value=alias_match.shared_value,
        query_methods=alias_match.query_methods,
        candidate_methods=alias_match.candidate_methods,
    )
    return UnifiedTitleMatch(
        query=query,
        candidate_title=candidate_title,
        family=LexicalMatchFamily.DETERMINISTIC,
        method=wrapped.method,
        lexical_score=wrapped.score,
        deterministic=wrapped,
        matched_alias=alias,
    )


def classify_lexical_match(
    query: str,
    candidate_title: str,
    *,
    title_aliases: tuple[str, ...] = (),
) -> UnifiedTitleMatch | None:
    """Return deterministic, alias, fuzzy, then conservative phonetic match."""

    deterministic = _classify_deterministic_or_alias(
        query,
        candidate_title,
        title_aliases,
    )
    if deterministic is not None:
        return deterministic

    fragment = classify_title_fragment_match(query, candidate_title)
    if fragment is not None:
        return UnifiedTitleMatch(
            query=query,
            candidate_title=candidate_title,
            family=LexicalMatchFamily.DETERMINISTIC,
            method=fragment.method,
            lexical_score=fragment.score,
            deterministic=fragment,
        )

    article_omission = classify_article_omission_fragment_match(
        query,
        candidate_title,
    )
    if article_omission is not None:
        return UnifiedTitleMatch(
            query=query,
            candidate_title=candidate_title,
            family=LexicalMatchFamily.DETERMINISTIC,
            method=article_omission.method,
            lexical_score=article_omission.score,
            deterministic=article_omission,
        )

    fuzzy = classify_fuzzy_match(query, candidate_title)
    if fuzzy is not None:
        return UnifiedTitleMatch(
            query=query,
            candidate_title=candidate_title,
            family=LexicalMatchFamily.FUZZY,
            method=fuzzy.method,
            lexical_score=fuzzy.lexical_score,
            fuzzy=fuzzy,
        )

    phonetic = classify_phonetic_match(query, candidate_title)
    if phonetic is None:
        return None
    return UnifiedTitleMatch(
        query=query,
        candidate_title=candidate_title,
        family=LexicalMatchFamily.PHONETIC,
        method=phonetic.method,
        lexical_score=phonetic.lexical_score,
        phonetic_score=phonetic.phonetic_score,
        phonetic=phonetic,
    )


def _has_media_type_mismatch(evidence: tuple[ContextEvidence, ...]) -> bool:
    return any(
        item.field is ContextField.MEDIA_TYPE
        and item.relation is ContextRelation.MISMATCH
        for item in evidence
    )


def _rank_family(
    query: str,
    candidates: Iterable[tuple[int, MediaCandidate, UnifiedTitleMatch]],
    context: MediaSearchContext,
) -> tuple[list[tuple[int, RankedSearchCandidate]], list[RejectedSearchCandidate]]:
    ranked: list[tuple[int, RankedSearchCandidate]] = []
    rejected: list[RejectedSearchCandidate] = []

    for catalog_index, candidate, title_match in candidates:
        evidence = evaluate_media_context(context, candidate)
        if _has_media_type_mismatch(evidence):
            rejected.append(
                RejectedSearchCandidate(
                    candidate=candidate,
                    title_match=title_match,
                    reason="media_type_mismatch",
                    evidence=evidence,
                )
            )
            continue

        context_score = sum(item.adjustment for item in evidence)
        ranked.append(
            (
                catalog_index,
                RankedSearchCandidate(
                    candidate=candidate,
                    title_match=title_match,
                    context_score=context_score,
                    total_score=title_match.score + context_score,
                    evidence=evidence,
                ),
            )
        )

    ranked.sort(
        key=lambda item: (
            -item[1].total_score,
            -item[1].title_match.score,
            -item[1].title_match.lexical_score,
            item[0],
        )
    )
    return ranked, rejected


def rank_search_candidates(
    query: str,
    candidates: Iterable[MediaCandidate],
    context: MediaSearchContext | None = None,
) -> SearchRanking:
    """Rank candidates through deterministic, fuzzy, then phonetic tiers.

    A lower-confidence tier is only active when no stronger title match survives
    a known media-type contradiction. Context can rank plausible title matches
    but cannot promote a lower tier over an available stronger tier.
    """

    active_context = context or MediaSearchContext()
    catalog = tuple(candidates)

    deterministic_candidates: list[tuple[int, MediaCandidate, UnifiedTitleMatch]] = []
    fuzzy_eligible: list[tuple[int, MediaCandidate]] = []

    for catalog_index, candidate in enumerate(catalog):
        deterministic = _classify_deterministic_or_alias(
            query,
            candidate.title,
            candidate.title_aliases,
        )
        if deterministic is not None:
            deterministic_candidates.append(
                (catalog_index, candidate, deterministic)
            )
        else:
            fuzzy_eligible.append((catalog_index, candidate))

    deterministic_ranked, deterministic_rejected = _rank_family(
        query,
        deterministic_candidates,
        active_context,
    )
    if deterministic_ranked:
        return SearchRanking(
            query=query,
            context=active_context,
            active_family=LexicalMatchFamily.DETERMINISTIC,
            matches=tuple(item[1] for item in deterministic_ranked),
            rejected=tuple(deterministic_rejected),
        )

    fragment_candidates: list[tuple[int, MediaCandidate, UnifiedTitleMatch]] = []
    fuzzy_after_fragment: list[tuple[int, MediaCandidate]] = []
    for catalog_index, candidate in fuzzy_eligible:
        fragment = classify_title_fragment_match(query, candidate.title)
        if fragment is None:
            fuzzy_after_fragment.append((catalog_index, candidate))
            continue
        fragment_candidates.append(
            (
                catalog_index,
                candidate,
                UnifiedTitleMatch(
                    query=query,
                    candidate_title=candidate.title,
                    family=LexicalMatchFamily.DETERMINISTIC,
                    method=fragment.method,
                    lexical_score=fragment.score,
                    deterministic=fragment,
                ),
            )
        )

    fragment_ranked, fragment_rejected = _rank_family(
        query,
        fragment_candidates,
        active_context,
    )
    if fragment_ranked:
        return SearchRanking(
            query=query,
            context=active_context,
            active_family=LexicalMatchFamily.DETERMINISTIC,
            matches=tuple(item[1] for item in fragment_ranked),
            rejected=tuple(deterministic_rejected + fragment_rejected),
        )

    article_omission_candidates: list[
        tuple[int, MediaCandidate, UnifiedTitleMatch]
    ] = []
    fuzzy_after_article_omission: list[tuple[int, MediaCandidate]] = []
    for catalog_index, candidate in fuzzy_after_fragment:
        article_omission = classify_article_omission_fragment_match(
            query,
            candidate.title,
        )
        if article_omission is None:
            fuzzy_after_article_omission.append((catalog_index, candidate))
            continue
        article_omission_candidates.append(
            (
                catalog_index,
                candidate,
                UnifiedTitleMatch(
                    query=query,
                    candidate_title=candidate.title,
                    family=LexicalMatchFamily.DETERMINISTIC,
                    method=article_omission.method,
                    lexical_score=article_omission.score,
                    deterministic=article_omission,
                ),
            )
        )

    article_omission_ranked, article_omission_rejected = _rank_family(
        query,
        article_omission_candidates,
        active_context,
    )
    if article_omission_ranked:
        return SearchRanking(
            query=query,
            context=active_context,
            active_family=LexicalMatchFamily.DETERMINISTIC,
            matches=tuple(item[1] for item in article_omission_ranked),
            rejected=tuple(
                deterministic_rejected
                + fragment_rejected
                + article_omission_rejected
            ),
        )

    fuzzy_candidates: list[tuple[int, MediaCandidate, UnifiedTitleMatch]] = []
    phonetic_eligible: list[tuple[int, MediaCandidate]] = []
    for catalog_index, candidate in fuzzy_after_article_omission:
        fuzzy = classify_fuzzy_match(query, candidate.title)
        if fuzzy is None:
            phonetic_eligible.append((catalog_index, candidate))
            continue
        fuzzy_candidates.append(
            (
                catalog_index,
                candidate,
                UnifiedTitleMatch(
                    query=query,
                    candidate_title=candidate.title,
                    family=LexicalMatchFamily.FUZZY,
                    method=fuzzy.method,
                    lexical_score=fuzzy.lexical_score,
                    fuzzy=fuzzy,
                ),
            )
        )

    fuzzy_ranked, fuzzy_rejected = _rank_family(
        query,
        fuzzy_candidates,
        active_context,
    )
    if fuzzy_ranked:
        return SearchRanking(
            query=query,
            context=active_context,
            active_family=LexicalMatchFamily.FUZZY,
            matches=tuple(item[1] for item in fuzzy_ranked),
            rejected=tuple(
                deterministic_rejected
                + fragment_rejected
                + article_omission_rejected
                + fuzzy_rejected
            ),
        )

    phonetic_candidates: list[tuple[int, MediaCandidate, UnifiedTitleMatch]] = []
    for catalog_index, candidate in phonetic_eligible:
        phonetic = classify_phonetic_match(query, candidate.title)
        if phonetic is None:
            continue
        phonetic_candidates.append(
            (
                catalog_index,
                candidate,
                UnifiedTitleMatch(
                    query=query,
                    candidate_title=candidate.title,
                    family=LexicalMatchFamily.PHONETIC,
                    method=phonetic.method,
                    lexical_score=phonetic.lexical_score,
                    phonetic_score=phonetic.phonetic_score,
                    phonetic=phonetic,
                ),
            )
        )

    phonetic_ranked, phonetic_rejected = _rank_family(
        query,
        phonetic_candidates,
        active_context,
    )
    return SearchRanking(
        query=query,
        context=active_context,
        active_family=(LexicalMatchFamily.PHONETIC if phonetic_ranked else None),
        matches=tuple(item[1] for item in phonetic_ranked),
        rejected=tuple(
            deterministic_rejected
            + fragment_rejected
            + article_omission_rejected
            + fuzzy_rejected
            + phonetic_rejected
        ),
    )


_AUDIO_DISAMBIGUATING_FIELDS = frozenset(
    {ContextField.ARTIST, ContextField.ALBUM, ContextField.YEAR}
)


def _is_audio_media_type(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    normalized = "".join(
        character for character in value.casefold() if character.isalnum()
    )
    return normalized == "audio"


def _evidence_by_field(
    candidate: RankedSearchCandidate,
) -> dict[ContextField, ContextEvidence]:
    return {item.field: item for item in candidate.evidence}


def _audio_spoken_title_collision(
    ranking: SearchRanking,
) -> tuple[RankedSearchCandidate, ...]:
    """Return unresolved audio records that sound like the top title.

    This is a safety decision over candidates that already matched through the
    normal tiered pipeline.  Speech equivalence never creates candidates.  A
    supplied artist, album, or year may resolve the collision only when it
    positively matches the top record and explicitly contradicts every rival.
    """

    if len(ranking.matches) < 2:
        return ()

    top = ranking.matches[0]
    if not _is_audio_media_type(top.candidate.media_type):
        return ()

    top_signature = spoken_title_signature(top.candidate.title)
    colliding = tuple(
        candidate
        for candidate in ranking.matches
        if _is_audio_media_type(candidate.candidate.media_type)
        and spoken_title_signature(candidate.candidate.title) == top_signature
    )
    if len(colliding) < 2:
        return ()

    top_evidence = _evidence_by_field(top)
    for rival in colliding[1:]:
        rival_evidence = _evidence_by_field(rival)
        separated = any(
            top_evidence.get(field) is not None
            and top_evidence[field].relation is ContextRelation.MATCH
            and rival_evidence.get(field) is not None
            and rival_evidence[field].relation is ContextRelation.MISMATCH
            for field in _AUDIO_DISAMBIGUATING_FIELDS
        )
        if not separated:
            return colliding

    return ()


def _decision(
    ranking: SearchRanking,
    *,
    status: MatchDecisionStatus,
    reason: SearchDecisionReason,
    selected: RankedSearchCandidate | None,
    alternatives: tuple[RankedSearchCandidate, ...],
    minimum_score: int | None,
    minimum_margin: int | None,
    minimum_similarity: float | None,
    observed_margin: int | None,
) -> SearchDecision:
    return SearchDecision(
        query=ranking.query,
        status=status,
        reason=reason,
        active_family=ranking.active_family,
        selected=selected,
        alternatives=alternatives,
        rejected=ranking.rejected,
        required_minimum_score=minimum_score,
        required_margin=minimum_margin,
        required_minimum_similarity=minimum_similarity,
        observed_margin=observed_margin,
    )


def decide_search_ranking(ranking: SearchRanking) -> SearchDecision:
    """Return a conservative decision for deterministic, fuzzy, or phonetic results."""

    if not ranking.matches:
        return _decision(
            ranking,
            status=MatchDecisionStatus.NOT_FOUND,
            reason=SearchDecisionReason.NO_MATCHING_CANDIDATES,
            selected=None,
            alternatives=(),
            minimum_score=None,
            minimum_margin=None,
            minimum_similarity=None,
            observed_margin=None,
        )

    top = ranking.matches[0]
    observed_margin = ranking.top_margin

    if top.title_match.is_deterministic:
        assert isinstance(top.title_match.method, DeterministicMatchMethod)
        threshold = threshold_for_method(top.title_match.method)
        minimum_score = threshold.minimum_total_score
        minimum_margin = threshold.minimum_margin
        minimum_similarity = None
        minimum_single_context_score = 0
        singleton_context_reason = SearchDecisionReason.FUZZY_SINGLETON_NEEDS_CONTEXT
    elif top.title_match.is_fuzzy:
        assert isinstance(top.title_match.method, FuzzyMatchMethod)
        fuzzy_threshold = threshold_for_fuzzy_method(top.title_match.method)
        minimum_score = fuzzy_threshold.minimum_total_score
        minimum_margin = fuzzy_threshold.minimum_margin
        minimum_similarity = fuzzy_threshold.minimum_similarity
        minimum_single_context_score = fuzzy_threshold.minimum_single_context_score
        singleton_context_reason = SearchDecisionReason.FUZZY_SINGLETON_NEEDS_CONTEXT
    else:
        assert top.title_match.is_phonetic
        assert isinstance(top.title_match.method, PhoneticMatchMethod)
        phonetic_threshold = threshold_for_phonetic_method(top.title_match.method)
        minimum_score = phonetic_threshold.minimum_total_score
        minimum_margin = phonetic_threshold.minimum_margin
        minimum_similarity = None
        minimum_single_context_score = phonetic_threshold.minimum_single_context_score
        singleton_context_reason = SearchDecisionReason.PHONETIC_SINGLETON_NEEDS_CONTEXT

    if top.has_context_contradiction:
        status = (
            MatchDecisionStatus.AMBIGUOUS
            if len(ranking.matches) > 1
            else MatchDecisionStatus.NOT_FOUND
        )
        return _decision(
            ranking,
            status=status,
            reason=SearchDecisionReason.TOP_CONTEXT_CONTRADICTION,
            selected=None,
            alternatives=ranking.matches,
            minimum_score=minimum_score,
            minimum_margin=minimum_margin,
            minimum_similarity=minimum_similarity,
            observed_margin=observed_margin,
        )

    if top.total_score < minimum_score:
        return _decision(
            ranking,
            status=MatchDecisionStatus.NOT_FOUND,
            reason=SearchDecisionReason.SCORE_BELOW_THRESHOLD,
            selected=None,
            alternatives=ranking.matches,
            minimum_score=minimum_score,
            minimum_margin=minimum_margin,
            minimum_similarity=minimum_similarity,
            observed_margin=observed_margin,
        )

    if top.title_match.is_fuzzy:
        assert top.title_match.fuzzy is not None
        assert minimum_similarity is not None
        if top.title_match.fuzzy.similarity < minimum_similarity:
            return _decision(
                ranking,
                status=MatchDecisionStatus.NOT_FOUND,
                reason=SearchDecisionReason.FUZZY_SIMILARITY_BELOW_THRESHOLD,
                selected=None,
                alternatives=ranking.matches,
                minimum_score=minimum_score,
                minimum_margin=minimum_margin,
                minimum_similarity=minimum_similarity,
                observed_margin=observed_margin,
            )

    spoken_collision = _audio_spoken_title_collision(ranking)
    if spoken_collision and observed_margin is not None and observed_margin > 0:
        return _decision(
            ranking,
            status=MatchDecisionStatus.AMBIGUOUS,
            reason=SearchDecisionReason.AUDIO_SPOKEN_TITLE_COLLISION,
            selected=None,
            alternatives=spoken_collision,
            minimum_score=minimum_score,
            minimum_margin=minimum_margin,
            minimum_similarity=minimum_similarity,
            observed_margin=observed_margin,
        )

    if len(ranking.matches) == 1:
        if top.context_score < minimum_single_context_score:
            return _decision(
                ranking,
                status=MatchDecisionStatus.NOT_FOUND,
                reason=singleton_context_reason,
                selected=None,
                alternatives=ranking.matches,
                minimum_score=minimum_score,
                minimum_margin=minimum_margin,
                minimum_similarity=minimum_similarity,
                observed_margin=None,
            )
        return _decision(
            ranking,
            status=MatchDecisionStatus.MATCHED,
            reason=SearchDecisionReason.UNIQUE_CONFIDENT_MATCH,
            selected=top,
            alternatives=(),
            minimum_score=minimum_score,
            minimum_margin=minimum_margin,
            minimum_similarity=minimum_similarity,
            observed_margin=None,
        )

    assert observed_margin is not None
    if observed_margin == 0:
        return _decision(
            ranking,
            status=MatchDecisionStatus.AMBIGUOUS,
            reason=SearchDecisionReason.TOP_SCORE_TIED,
            selected=None,
            alternatives=ranking.matches,
            minimum_score=minimum_score,
            minimum_margin=minimum_margin,
            minimum_similarity=minimum_similarity,
            observed_margin=observed_margin,
        )

    if observed_margin < minimum_margin:
        return _decision(
            ranking,
            status=MatchDecisionStatus.AMBIGUOUS,
            reason=SearchDecisionReason.INSUFFICIENT_MARGIN,
            selected=None,
            alternatives=ranking.matches,
            minimum_score=minimum_score,
            minimum_margin=minimum_margin,
            minimum_similarity=minimum_similarity,
            observed_margin=observed_margin,
        )

    return _decision(
        ranking,
        status=MatchDecisionStatus.MATCHED,
        reason=SearchDecisionReason.UNIQUE_CONFIDENT_MATCH,
        selected=top,
        alternatives=ranking.matches[1:],
        minimum_score=minimum_score,
        minimum_margin=minimum_margin,
        minimum_similarity=minimum_similarity,
        observed_margin=observed_margin,
    )
