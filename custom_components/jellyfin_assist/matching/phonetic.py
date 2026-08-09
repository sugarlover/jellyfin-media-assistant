"""Conservative phonetic matching for media titles and spoken queries.

This module is the lowest-confidence title-matching tier. It is intended for
speech-recognition variations and genuine sound-alikes that deterministic and
controlled fuzzy matching cannot resolve. Matching is deliberately strict:

* query and candidate must have the same token count;
* every corresponding token must share the same phonetic signature;
* short single-token inputs below three alphanumeric characters are rejected;
* lexical and phonetic scores remain separate for diagnostics;
* this module makes no automatic-selection decision.

The implementation uses a small, documented homophone table plus a conservative
Soundex-style token signature. It has no external dependencies and does not
contact Jellyfin or Home Assistant. Scores are ranking strengths, not
probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Iterable

from .deterministic import TitleCandidate, classify_deterministic_match
from .fuzzy import damerau_levenshtein_distance
from .normalization import VariantMethod, build_text_profile


class PhoneticMatchMethod(StrEnum):
    """The strongest conservative phonetic relationship found."""

    COMMON_HOMOPHONE = "common_homophone"
    TOKEN_SIGNATURE = "token_signature"


_METHOD_SCORES: dict[PhoneticMatchMethod, int] = {
    PhoneticMatchMethod.COMMON_HOMOPHONE: 74,
    PhoneticMatchMethod.TOKEN_SIGNATURE: 70,
}

_SAFE_PHONETIC_VARIANTS = {
    VariantMethod.UNICODE_CASEFOLD,
    VariantMethod.DIACRITIC_FOLD,
    VariantMethod.PUNCTUATION_SPACING,
    VariantMethod.NUMBER_WORDS_TO_DIGITS,
    VariantMethod.NUMERIC_ORDINAL_SPACING,
}

_ALPHANUMERIC_RE = re.compile(r"[^a-z0-9]+")
_MINIMUM_SINGLE_TOKEN_LENGTH = 3
_MINIMUM_TOTAL_LENGTH = 3

# The table is intentionally small and auditable. It covers common ASR
# substitutions without attempting broad semantic synonymy.
_HOMOPHONE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("to", "too", "two"),
    ("for", "fore", "four"),
    ("one", "won"),
    ("see", "sea", "cee"),
    ("right", "rite", "write", "wright"),
    ("night", "knight", "nite"),
    ("no", "know"),
    ("new", "knew"),
    ("by", "buy", "bye"),
    ("there", "their", "theyre"),
    ("son", "sun"),
    ("peace", "piece"),
    ("road", "rode"),
    ("hole", "whole"),
    ("week", "weak"),
    ("break", "brake"),
    ("weather", "whether"),
)

_HOMOPHONE_CANONICAL: dict[str, str] = {
    spelling: f"H{index:02d}"
    for index, group in enumerate(_HOMOPHONE_GROUPS, start=1)
    for spelling in group
}

_SOUNDEX_CODES = {
    **dict.fromkeys("bfpv", "1"),
    **dict.fromkeys("cgjkqsxz", "2"),
    **dict.fromkeys("dt", "3"),
    "l": "4",
    **dict.fromkeys("mn", "5"),
    "r": "6",
}


@dataclass(frozen=True, slots=True)
class PhoneticToken:
    """One normalized token and its conservative phonetic signature."""

    value: str
    signature: str
    homophone_group: str | None = None


@dataclass(frozen=True, slots=True)
class PhoneticProfile:
    """One tokenized representation eligible for phonetic comparison."""

    source_value: str
    tokens: tuple[PhoneticToken, ...]

    @property
    def signature(self) -> tuple[str, ...]:
        return tuple(token.signature for token in self.tokens)

    @property
    def alphanumeric_length(self) -> int:
        return sum(len(token.value) for token in self.tokens)


@dataclass(frozen=True, slots=True)
class PhoneticTitleMatch:
    """One conservative sound-alike title match."""

    query: str
    candidate_title: str
    method: PhoneticMatchMethod
    phonetic_score: int
    lexical_score: int
    lexical_similarity: float
    query_value: str
    candidate_value: str
    query_signature: tuple[str, ...]
    candidate_signature: tuple[str, ...]

    @property
    def score(self) -> int:
        """Return the phonetic ranking strength used by the search pipeline."""

        return self.phonetic_score


@dataclass(frozen=True, slots=True)
class RankedPhoneticCandidate:
    """A catalog title paired with its conservative phonetic match."""

    candidate: TitleCandidate
    match: PhoneticTitleMatch


@dataclass(frozen=True, slots=True)
class PhoneticRanking:
    """Phonetic candidates sorted by phonetic strength."""

    query: str
    matches: tuple[RankedPhoneticCandidate, ...]

    @property
    def top_score(self) -> int | None:
        return self.matches[0].match.phonetic_score if self.matches else None

    @property
    def top_score_is_unique(self) -> bool:
        if not self.matches:
            return False
        if len(self.matches) == 1:
            return True
        return self.matches[0].match.phonetic_score > self.matches[1].match.phonetic_score

    @property
    def top_margin(self) -> int | None:
        if len(self.matches) < 2:
            return None
        return self.matches[0].match.phonetic_score - self.matches[1].match.phonetic_score


def score_for_phonetic_method(method: PhoneticMatchMethod) -> int:
    """Return the centralized ranking strength for a phonetic method."""

    return _METHOD_SCORES[method]


def _normalize_pronunciation_spelling(token: str) -> str:
    """Apply a few high-confidence spelling-to-sound normalizations."""

    value = token
    if value.startswith(("kn", "gn", "pn")) and len(value) > 2:
        value = value[1:]
    elif value.startswith("wr") and len(value) > 2:
        value = value[1:]
    elif value.startswith("ps") and len(value) > 2:
        value = value[1:]

    value = value.replace("tch", "ch")
    value = value.replace("dge", "j")
    value = value.replace("dg", "j")
    value = value.replace("ph", "f")
    value = value.replace("igh", "i")
    value = value.replace("x", "ks")

    if value.endswith("gh") and len(value) > 3:
        value = value[:-2]
    if value.endswith("mb") and len(value) > 3:
        value = value[:-1]
    if value.endswith("e") and len(value) > 3:
        value = value[:-1]

    collapsed: list[str] = []
    for character in value:
        if not collapsed or collapsed[-1] != character:
            collapsed.append(character)
    return "".join(collapsed)


def _soundex_signature(token: str) -> str:
    """Return a four-character Soundex-style signature for one token."""

    prepared = _normalize_pronunciation_spelling(token)
    if not prepared:
        return ""
    if prepared.isdigit():
        return f"N{prepared}"

    first = prepared[0]
    output: list[str] = [first.upper()]
    previous_code = _SOUNDEX_CODES.get(first, "")

    for character in prepared[1:]:
        code = _SOUNDEX_CODES.get(character, "")
        if code:
            if code != previous_code:
                output.append(code)
            previous_code = code
        elif character not in "hw":
            # Vowels and y separate otherwise repeated consonant groups.
            previous_code = ""

        if len(output) == 4:
            break

    return ("".join(output) + "000")[:4]


def _tokenize_profile_value(value: str) -> PhoneticProfile | None:
    raw_tokens = tuple(token for token in value.split() if token)
    if not raw_tokens:
        return None

    tokens: list[PhoneticToken] = []
    for raw_token in raw_tokens:
        token = _ALPHANUMERIC_RE.sub("", raw_token)
        if not token:
            continue
        group = _HOMOPHONE_CANONICAL.get(token)
        signature = group or _soundex_signature(token)
        if not signature:
            return None
        tokens.append(
            PhoneticToken(
                value=token,
                signature=signature,
                homophone_group=group,
            )
        )

    if not tokens:
        return None

    profile = PhoneticProfile(source_value=value, tokens=tuple(tokens))
    if profile.alphanumeric_length < _MINIMUM_TOTAL_LENGTH:
        return None
    if len(profile.tokens) == 1 and len(profile.tokens[0].value) < _MINIMUM_SINGLE_TOKEN_LENGTH:
        return None
    return profile


def build_phonetic_profiles(text: str) -> tuple[PhoneticProfile, ...]:
    """Build deduplicated conservative phonetic profiles for text."""

    profiles: dict[tuple[tuple[str, ...], tuple[str, ...]], PhoneticProfile] = {}
    for variant in build_text_profile(text).variants:
        if not any(method in _SAFE_PHONETIC_VARIANTS for method in variant.methods):
            continue
        profile = _tokenize_profile_value(variant.value)
        if profile is None:
            continue
        key = (
            tuple(token.value for token in profile.tokens),
            profile.signature,
        )
        profiles.setdefault(key, profile)
    return tuple(profiles.values())


def _lexical_similarity(left: str, right: str) -> float:
    denominator = max(len(left), len(right))
    if denominator == 0:
        return 1.0
    distance = damerau_levenshtein_distance(left, right)
    return max(0.0, 1.0 - (distance / denominator))


def _method_for_profiles(
    query_profile: PhoneticProfile,
    candidate_profile: PhoneticProfile,
) -> PhoneticMatchMethod:
    differing_pairs = [
        (left, right)
        for left, right in zip(query_profile.tokens, candidate_profile.tokens)
        if left.value != right.value
    ]
    if differing_pairs and all(
        left.homophone_group is not None
        and left.homophone_group == right.homophone_group
        for left, right in differing_pairs
    ):
        return PhoneticMatchMethod.COMMON_HOMOPHONE
    return PhoneticMatchMethod.TOKEN_SIGNATURE


def classify_phonetic_match(query: str, candidate_title: str) -> PhoneticTitleMatch | None:
    """Return a conservative phonetic match when stronger lexical tiers fail."""

    if classify_deterministic_match(query, candidate_title) is not None:
        return None

    best: tuple[int, float, int, str, str, PhoneticMatchMethod, tuple[str, ...], tuple[str, ...]] | None = None

    for query_profile in build_phonetic_profiles(query):
        for candidate_profile in build_phonetic_profiles(candidate_title):
            if len(query_profile.tokens) != len(candidate_profile.tokens):
                continue
            if query_profile.signature != candidate_profile.signature:
                continue
            if all(
                left.value == right.value
                for left, right in zip(query_profile.tokens, candidate_profile.tokens)
            ):
                continue

            method = _method_for_profiles(query_profile, candidate_profile)
            phonetic_score = score_for_phonetic_method(method)
            similarity = _lexical_similarity(
                query_profile.source_value,
                candidate_profile.source_value,
            )
            lexical_score = round(similarity * 100)
            ordering = (
                phonetic_score,
                similarity,
                -abs(len(query_profile.source_value) - len(candidate_profile.source_value)),
                query_profile.source_value,
                candidate_profile.source_value,
                method,
                query_profile.signature,
                candidate_profile.signature,
            )
            if best is None or ordering > best:
                best = ordering

    if best is None:
        return None

    (
        phonetic_score,
        similarity,
        _negative_length_delta,
        query_value,
        candidate_value,
        method,
        query_signature,
        candidate_signature,
    ) = best
    return PhoneticTitleMatch(
        query=query,
        candidate_title=candidate_title,
        method=method,
        phonetic_score=phonetic_score,
        lexical_score=round(similarity * 100),
        lexical_similarity=similarity,
        query_value=query_value,
        candidate_value=candidate_value,
        query_signature=query_signature,
        candidate_signature=candidate_signature,
    )


def rank_phonetic_candidates(
    query: str,
    candidates: Iterable[TitleCandidate],
) -> PhoneticRanking:
    """Return conservative phonetic candidates ordered strongest-first."""

    ranked: list[tuple[int, RankedPhoneticCandidate]] = []
    for catalog_index, candidate in enumerate(candidates):
        match = classify_phonetic_match(query, candidate.title)
        if match is None:
            continue
        ranked.append(
            (
                catalog_index,
                RankedPhoneticCandidate(candidate=candidate, match=match),
            )
        )

    ranked.sort(
        key=lambda item: (
            -item[1].match.phonetic_score,
            -item[1].match.lexical_score,
            item[0],
        )
    )
    return PhoneticRanking(
        query=query,
        matches=tuple(item[1] for item in ranked),
    )
