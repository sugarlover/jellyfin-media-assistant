"""Controlled lexical fuzzy matching for media titles.

This module handles a deliberately small set of typing and swipe-like errors:
single insertions, deletions, substitutions, adjacent transpositions, repeated
or missing characters, adjacent-key substitutions, and a limited number of
edits in longer titles.

It does not perform phonetic matching, semantic matching, catalog retrieval,
context ranking, or automatic selection. Deterministic equivalence always wins
and is intentionally excluded from this layer. Scores are lexical ranking
strengths, not probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .deterministic import TitleCandidate, classify_deterministic_match
from .normalization import (
    VariantMethod,
    build_text_profile,
    numeric_token_signature,
)


class FuzzyMatchMethod(StrEnum):
    """The strongest controlled lexical error pattern found for a title pair."""

    ADJACENT_TRANSPOSITION = "adjacent_transposition"
    ADJACENT_KEY_SUBSTITUTION = "adjacent_key_substitution"
    SINGLE_EDIT = "single_edit"
    LIMITED_MULTI_EDIT = "limited_multi_edit"


_METHOD_BASE_SCORES: dict[FuzzyMatchMethod, int] = {
    FuzzyMatchMethod.ADJACENT_TRANSPOSITION: 84,
    FuzzyMatchMethod.ADJACENT_KEY_SUBSTITUTION: 83,
    FuzzyMatchMethod.SINGLE_EDIT: 80,
    FuzzyMatchMethod.LIMITED_MULTI_EDIT: 76,
}

_SAFE_FUZZY_VARIANTS = {
    VariantMethod.UNICODE_CASEFOLD,
    VariantMethod.DIACRITIC_FOLD,
    VariantMethod.PUNCTUATION_SPACING,
    VariantMethod.NUMBER_WORDS_TO_DIGITS,
    VariantMethod.NUMERIC_ORDINAL_SPACING,
    VariantMethod.NUMERIC_ORDINAL_TO_WORDS,
}

_MINIMUM_ALPHANUMERIC_LENGTH = 5
_MINIMUM_SIMILARITY = 0.80


@dataclass(frozen=True, slots=True)
class FuzzyTitleMatch:
    """One controlled lexical match between a query and candidate title."""

    query: str
    candidate_title: str
    method: FuzzyMatchMethod
    lexical_score: int
    edit_distance: int
    similarity: float
    query_value: str
    candidate_value: str

    @property
    def score(self) -> int:
        """Compatibility alias for callers that rank by a generic score."""

        return self.lexical_score


@dataclass(frozen=True, slots=True)
class RankedFuzzyCandidate:
    """A catalog title paired with its controlled fuzzy match."""

    candidate: TitleCandidate
    match: FuzzyTitleMatch


@dataclass(frozen=True, slots=True)
class FuzzyRanking:
    """Controlled fuzzy candidates sorted by lexical strength."""

    query: str
    matches: tuple[RankedFuzzyCandidate, ...]

    @property
    def top_score(self) -> int | None:
        """Return the strongest lexical score, if anything matched."""

        return self.matches[0].match.lexical_score if self.matches else None

    @property
    def top_score_is_unique(self) -> bool:
        """Return whether exactly one candidate owns the highest score."""

        if not self.matches:
            return False
        if len(self.matches) == 1:
            return True
        return self.matches[0].match.lexical_score > self.matches[1].match.lexical_score

    @property
    def top_margin(self) -> int | None:
        """Return the first-to-second lexical-score margin when measurable."""

        if len(self.matches) < 2:
            return None
        return self.matches[0].match.lexical_score - self.matches[1].match.lexical_score


@dataclass(frozen=True, slots=True)
class _ComparableValue:
    value: str
    token_count: int
    alphanumeric_length: int
    numeric_signature: tuple[str, ...]


_QWERTY_ROWS: tuple[tuple[str, float], ...] = (
    ("1234567890", 0.0),
    ("qwertyuiop", 0.25),
    ("asdfghjkl", 0.50),
    ("zxcvbnm", 0.75),
)


def _keyboard_coordinates() -> dict[str, tuple[float, int]]:
    coordinates: dict[str, tuple[float, int]] = {}
    for row_index, (characters, offset) in enumerate(_QWERTY_ROWS):
        for column, character in enumerate(characters):
            coordinates[character] = (column + offset, row_index)
    return coordinates


_KEYBOARD_COORDINATES = _keyboard_coordinates()


def _are_adjacent_keys(left: str, right: str) -> bool:
    if left == right:
        return False
    left_coordinate = _KEYBOARD_COORDINATES.get(left)
    right_coordinate = _KEYBOARD_COORDINATES.get(right)
    if left_coordinate is None or right_coordinate is None:
        return False
    horizontal = abs(left_coordinate[0] - right_coordinate[0])
    vertical = abs(left_coordinate[1] - right_coordinate[1])
    return horizontal <= 1.1 and vertical <= 1


def _alphanumeric_length(value: str) -> int:
    return sum(character.isalnum() for character in value)


def _comparable_values(text: str) -> tuple[_ComparableValue, ...]:
    """Return conservative normalized forms eligible for edit comparison.

    Compact-spacing representations are excluded. Exact joined/separated-word
    equivalence already belongs to the deterministic layer; combining a word-
    boundary change with a typo is riskier and is deferred until it has its own
    explicit method and threshold.
    """

    values: dict[str, _ComparableValue] = {}
    for variant in build_text_profile(text).variants:
        if not any(method in _SAFE_FUZZY_VARIANTS for method in variant.methods):
            continue
        value = variant.value
        if not value:
            continue
        comparable = _ComparableValue(
            value=value,
            token_count=len(value.split()),
            alphanumeric_length=_alphanumeric_length(value),
            numeric_signature=numeric_token_signature(value),
        )
        values.setdefault(value, comparable)
    return tuple(values.values())


def damerau_levenshtein_distance(left: str, right: str) -> int:
    """Return optimal-string-alignment edit distance.

    Allowed operations are insertion, deletion, substitution, and one adjacent
    transposition. This restricted Damerau-Levenshtein form is sufficient for
    the controlled typing errors recognized by this layer.
    """

    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous_previous: list[int] | None = None
    previous = list(range(len(right) + 1))

    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            substitution_cost = 0 if left_character == right_character else 1
            value = min(
                current[right_index - 1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + substitution_cost,
            )

            if (
                previous_previous is not None
                and left_index > 1
                and right_index > 1
                and left_character == right[right_index - 2]
                and left[left_index - 2] == right_character
            ):
                value = min(value, previous_previous[right_index - 2] + 1)

            current.append(value)

        previous_previous, previous = previous, current

    return previous[-1]


def _is_single_adjacent_transposition(left: str, right: str) -> bool:
    if len(left) != len(right) or left == right:
        return False
    differences = [index for index, pair in enumerate(zip(left, right)) if pair[0] != pair[1]]
    if len(differences) != 2:
        return False
    first, second = differences
    return (
        second == first + 1
        and left[first] == right[second]
        and left[second] == right[first]
    )


def _is_single_adjacent_key_substitution(left: str, right: str) -> bool:
    if len(left) != len(right) or left == right:
        return False
    differences = [(a, b) for a, b in zip(left, right) if a != b]
    if len(differences) != 1:
        return False
    return _are_adjacent_keys(*differences[0])


def _maximum_allowed_edits(alphanumeric_length: int) -> int:
    """Return a conservative length-aware edit ceiling."""

    if alphanumeric_length < _MINIMUM_ALPHANUMERIC_LENGTH:
        return 0
    if alphanumeric_length <= 7:
        return 1
    if alphanumeric_length <= 19:
        return 2
    return 3


def score_for_fuzzy_match(method: FuzzyMatchMethod, edit_distance: int) -> int:
    """Return the centralized lexical strength for a fuzzy method."""

    if edit_distance < 1:
        raise ValueError("A fuzzy match must contain at least one edit")
    base = _METHOD_BASE_SCORES[method]
    if method is FuzzyMatchMethod.LIMITED_MULTI_EDIT:
        return max(1, base - max(0, edit_distance - 2) * 3)
    return base


def _classify_pair(
    query_value: _ComparableValue,
    candidate_value: _ComparableValue,
) -> tuple[FuzzyMatchMethod, int, float, int] | None:
    if query_value.token_count != candidate_value.token_count:
        return None

    # Never fuzzy-correct one recognized number into another. A misspelled
    # number word such as "thirteeth" has no numeric signature and may be
    # compared with the catalog alias "thirteenth"; correctly spelled or
    # explicit values such as "thirtieth"/"30th" and "13th" must agree.
    if (
        query_value.numeric_signature
        and candidate_value.numeric_signature
        and query_value.numeric_signature != candidate_value.numeric_signature
    ):
        return None

    minimum_length = min(
        query_value.alphanumeric_length,
        candidate_value.alphanumeric_length,
    )
    maximum_length = max(
        query_value.alphanumeric_length,
        candidate_value.alphanumeric_length,
    )
    maximum_edits = _maximum_allowed_edits(minimum_length)
    if maximum_edits == 0:
        return None
    if abs(query_value.alphanumeric_length - candidate_value.alphanumeric_length) > maximum_edits:
        return None

    distance = damerau_levenshtein_distance(query_value.value, candidate_value.value)
    if distance == 0 or distance > maximum_edits:
        return None

    denominator = max(len(query_value.value), len(candidate_value.value))
    similarity = 1.0 - (distance / denominator)
    if similarity < _MINIMUM_SIMILARITY:
        return None

    if _is_single_adjacent_transposition(query_value.value, candidate_value.value):
        method = FuzzyMatchMethod.ADJACENT_TRANSPOSITION
    elif _is_single_adjacent_key_substitution(query_value.value, candidate_value.value):
        method = FuzzyMatchMethod.ADJACENT_KEY_SUBSTITUTION
    elif distance == 1:
        method = FuzzyMatchMethod.SINGLE_EDIT
    else:
        method = FuzzyMatchMethod.LIMITED_MULTI_EDIT

    score = score_for_fuzzy_match(method, distance)
    return method, distance, similarity, score


def classify_fuzzy_match(query: str, candidate_title: str) -> FuzzyTitleMatch | None:
    """Classify one conservative lexical-error match, if any.

    Deterministic equivalence is intentionally returned as ``None`` because it
    belongs to the stronger deterministic layer.
    """

    if classify_deterministic_match(query, candidate_title) is not None:
        return None

    best: tuple[int, int, float, str, str, FuzzyMatchMethod] | None = None
    for query_value in _comparable_values(query):
        for candidate_value in _comparable_values(candidate_title):
            classified = _classify_pair(query_value, candidate_value)
            if classified is None:
                continue
            method, distance, similarity, score = classified
            ordering = (
                score,
                -distance,
                similarity,
                query_value.value,
                candidate_value.value,
                method,
            )
            if best is None or ordering > best:
                best = ordering

    if best is None:
        return None

    score, negative_distance, similarity, query_value, candidate_value, method = best
    return FuzzyTitleMatch(
        query=query,
        candidate_title=candidate_title,
        method=method,
        lexical_score=score,
        edit_distance=-negative_distance,
        similarity=similarity,
        query_value=query_value,
        candidate_value=candidate_value,
    )


def rank_fuzzy_candidates(
    query: str,
    candidates: Iterable[TitleCandidate],
) -> FuzzyRanking:
    """Return controlled fuzzy candidates ordered strongest-first.

    Catalog order is retained for otherwise tied results so this layer never
    invents a winner from candidate identity or alphabetic ordering.
    """

    matches: list[tuple[int, RankedFuzzyCandidate]] = []
    for catalog_index, candidate in enumerate(candidates):
        match = classify_fuzzy_match(query, candidate.title)
        if match is None:
            continue
        matches.append(
            (
                catalog_index,
                RankedFuzzyCandidate(candidate=candidate, match=match),
            )
        )

    matches.sort(
        key=lambda item: (
            -item[1].match.lexical_score,
            item[1].match.edit_distance,
            -item[1].match.similarity,
            item[0],
        )
    )
    return FuzzyRanking(
        query=query,
        matches=tuple(item[1] for item in matches),
    )
