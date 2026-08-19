"""Conservative confidence decisions for deterministic media matches.

This module converts a context-ranked candidate list into one of three explicit
outcomes: a unique automatic match, an ambiguous set that requires selection,
or no acceptable deterministic match.

The decision policy is deliberately isolated from Jellyfin retrieval, Home
Assistant action registration, playback, and queue handling. Scores are ranking
strengths rather than probabilities. Automatic selection requires both an
acceptable top candidate and, when alternatives exist, a method-specific score
margin over the runner-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .context import ContextRanking, RankedMediaCandidate, RejectedMediaCandidate
from .deterministic import DeterministicMatchMethod


class MatchDecisionStatus(StrEnum):
    """The safe action permitted by the deterministic matcher."""

    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


class MatchDecisionReason(StrEnum):
    """A stable, machine-readable explanation for a decision."""

    UNIQUE_CONFIDENT_MATCH = "unique_confident_match"
    NO_MATCHING_CANDIDATES = "no_matching_candidates"
    TOP_SCORE_TIED = "top_score_tied"
    INSUFFICIENT_MARGIN = "insufficient_margin"
    TOP_CONTEXT_CONTRADICTION = "top_context_contradiction"
    SCORE_BELOW_THRESHOLD = "score_below_threshold"


@dataclass(frozen=True, slots=True)
class ConfidenceThreshold:
    """Minimum score and separation required for one match method."""

    minimum_total_score: int
    minimum_margin: int
    allow_single_candidate: bool = True


# These thresholds are intentionally centralized and conservative. A singleton
# deterministic match can be accepted, but competing candidates must be
# separated by a larger margin as the normalization method becomes more
# invasive. They are calibration values, not percentages.
_METHOD_THRESHOLDS: dict[DeterministicMatchMethod, ConfidenceThreshold] = {
    DeterministicMatchMethod.EXACT_ORIGINAL: ConfidenceThreshold(
        minimum_total_score=100,
        minimum_margin=3,
    ),
    DeterministicMatchMethod.UNICODE_CASEFOLD: ConfidenceThreshold(
        minimum_total_score=99,
        minimum_margin=3,
    ),
    DeterministicMatchMethod.DIACRITIC_FOLD: ConfidenceThreshold(
        minimum_total_score=97,
        minimum_margin=4,
    ),
    DeterministicMatchMethod.PUNCTUATION_SPACING: ConfidenceThreshold(
        minimum_total_score=95,
        minimum_margin=4,
    ),
    DeterministicMatchMethod.NUMBER_EQUIVALENT: ConfidenceThreshold(
        minimum_total_score=93,
        minimum_margin=4,
    ),
    DeterministicMatchMethod.STYLIZED_NUMBER_ALIAS: ConfidenceThreshold(
        minimum_total_score=90,
        minimum_margin=6,
    ),
    DeterministicMatchMethod.COMPACT_SPACING: ConfidenceThreshold(
        minimum_total_score=88,
        minimum_margin=6,
    ),
    DeterministicMatchMethod.TITLE_FRAGMENT: ConfidenceThreshold(
        minimum_total_score=76,
        minimum_margin=10,
    ),
    DeterministicMatchMethod.ARTICLE_OMISSION_FRAGMENT: ConfidenceThreshold(
        minimum_total_score=74,
        minimum_margin=12,
    ),
}


@dataclass(frozen=True, slots=True)
class MatchDecision:
    """One transparent confidence decision over context-ranked candidates."""

    query: str
    status: MatchDecisionStatus
    reason: MatchDecisionReason
    selected: RankedMediaCandidate | None
    alternatives: tuple[RankedMediaCandidate, ...]
    rejected: tuple[RejectedMediaCandidate, ...]
    required_minimum_score: int | None
    required_margin: int | None
    observed_margin: int | None

    @property
    def automatic_selection_allowed(self) -> bool:
        """Return whether the caller may safely use ``selected`` directly."""

        return self.status is MatchDecisionStatus.MATCHED and self.selected is not None

    @property
    def selection_required(self) -> bool:
        """Return whether the ranked alternatives must be shown to the user."""

        return self.status is MatchDecisionStatus.AMBIGUOUS


def threshold_for_method(
    method: DeterministicMatchMethod,
) -> ConfidenceThreshold:
    """Return the centralized confidence threshold for a match method."""

    return _METHOD_THRESHOLDS[method]


def _decision(
    ranking: ContextRanking,
    *,
    status: MatchDecisionStatus,
    reason: MatchDecisionReason,
    selected: RankedMediaCandidate | None,
    alternatives: tuple[RankedMediaCandidate, ...],
    threshold: ConfidenceThreshold | None,
    observed_margin: int | None,
) -> MatchDecision:
    return MatchDecision(
        query=ranking.query,
        status=status,
        reason=reason,
        selected=selected,
        alternatives=alternatives,
        rejected=ranking.rejected,
        required_minimum_score=(
            threshold.minimum_total_score if threshold is not None else None
        ),
        required_margin=(threshold.minimum_margin if threshold is not None else None),
        observed_margin=observed_margin,
    )


def decide_context_ranking(ranking: ContextRanking) -> MatchDecision:
    """Return a conservative deterministic decision for a context ranking.

    Decision order is intentional:

    1. No viable title matches is ``not_found``.
    2. A top candidate with explicit metadata contradictions is never selected.
    3. A top score below its method's floor is rejected.
    4. A single acceptable deterministic candidate may be selected.
    5. Ties and insufficient first-to-second margins require user selection.
    6. Only a sufficiently separated top candidate is selected automatically.
    """

    if not ranking.matches:
        return _decision(
            ranking,
            status=MatchDecisionStatus.NOT_FOUND,
            reason=MatchDecisionReason.NO_MATCHING_CANDIDATES,
            selected=None,
            alternatives=(),
            threshold=None,
            observed_margin=None,
        )

    top = ranking.matches[0]
    threshold = threshold_for_method(top.title_match.method)
    observed_margin = ranking.top_margin

    if top.has_context_contradiction:
        status = (
            MatchDecisionStatus.AMBIGUOUS
            if len(ranking.matches) > 1
            else MatchDecisionStatus.NOT_FOUND
        )
        return _decision(
            ranking,
            status=status,
            reason=MatchDecisionReason.TOP_CONTEXT_CONTRADICTION,
            selected=None,
            alternatives=ranking.matches,
            threshold=threshold,
            observed_margin=observed_margin,
        )

    if top.total_score < threshold.minimum_total_score:
        return _decision(
            ranking,
            status=MatchDecisionStatus.NOT_FOUND,
            reason=MatchDecisionReason.SCORE_BELOW_THRESHOLD,
            selected=None,
            alternatives=ranking.matches,
            threshold=threshold,
            observed_margin=observed_margin,
        )

    if len(ranking.matches) == 1:
        if threshold.allow_single_candidate:
            return _decision(
                ranking,
                status=MatchDecisionStatus.MATCHED,
                reason=MatchDecisionReason.UNIQUE_CONFIDENT_MATCH,
                selected=top,
                alternatives=(),
                threshold=threshold,
                observed_margin=None,
            )
        return _decision(
            ranking,
            status=MatchDecisionStatus.NOT_FOUND,
            reason=MatchDecisionReason.SCORE_BELOW_THRESHOLD,
            selected=None,
            alternatives=ranking.matches,
            threshold=threshold,
            observed_margin=None,
        )

    assert observed_margin is not None
    if observed_margin == 0:
        return _decision(
            ranking,
            status=MatchDecisionStatus.AMBIGUOUS,
            reason=MatchDecisionReason.TOP_SCORE_TIED,
            selected=None,
            alternatives=ranking.matches,
            threshold=threshold,
            observed_margin=observed_margin,
        )

    if observed_margin < threshold.minimum_margin:
        return _decision(
            ranking,
            status=MatchDecisionStatus.AMBIGUOUS,
            reason=MatchDecisionReason.INSUFFICIENT_MARGIN,
            selected=None,
            alternatives=ranking.matches,
            threshold=threshold,
            observed_margin=observed_margin,
        )

    return _decision(
        ranking,
        status=MatchDecisionStatus.MATCHED,
        reason=MatchDecisionReason.UNIQUE_CONFIDENT_MATCH,
        selected=top,
        alternatives=ranking.matches[1:],
        threshold=threshold,
        observed_margin=observed_margin,
    )
