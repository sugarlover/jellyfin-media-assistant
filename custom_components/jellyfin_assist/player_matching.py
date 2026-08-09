"""Safe matching and trailing recovery for Home Assistant media players."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

_PLAYER_PREFIX_RE = re.compile(r"^(?:the\s+)+", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_PLAYER_RE = re.compile(r"\b(on|to|for)\s+", re.IGNORECASE)
_PLAYER_HINT_TOKENS = frozenset(
    {
        "tv",
        "television",
        "speaker",
        "speakers",
        "player",
        "screen",
        "display",
        "chromecast",
        "cast",
        "room",
    }
)


@dataclass(frozen=True, slots=True)
class PlayerCandidate:
    """One allowed Home Assistant playback target and its spoken names."""

    entity_id: str
    name: str
    aliases: tuple[str, ...] = ()

    def spoken_names(self) -> tuple[str, ...]:
        """Return stable, de-duplicated names used for matching."""

        values = [self.name, *self.aliases, self.entity_id]
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            cleaned = str(value).strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
        return tuple(result)

    def preferred_response_name(self) -> str:
        """Return the clearest stable spoken name for an explicit entity ID."""

        canonical = normalize_player_text(self.name)
        entity_fallback = humanize_player_entity_id(self.entity_id)
        entity_normalized = normalize_player_text(entity_fallback)
        for alias in self.aliases:
            cleaned = str(alias).strip()
            if not cleaned or cleaned.startswith("media_player."):
                continue
            normalized = normalize_player_text(cleaned)
            if normalized and normalized not in {canonical, entity_normalized}:
                return cleaned

        # Home Assistant intent slots commonly resolve a spoken player alias to an
        # entity ID before Jellyfin Media Assistant sees the request.  When the HA
        # friendly name differs from the entity-derived household name (for example
        # media_player.attic_tv -> "Main TV"), prefer the stable entity-derived
        # name so the confirmation reflects the target the user actually requested.
        if entity_normalized and entity_normalized != canonical:
            return entity_fallback
        return self.name


@dataclass(frozen=True, slots=True)
class PlayerMatch:
    """One player-resolution decision with user-facing diagnostics."""

    status: str
    original_text: str
    entity_id: str | None = None
    matched_name: str | None = None
    matched_alias: str | None = None
    method: str | None = None
    confidence: float | None = None
    candidates: tuple[dict[str, Any], ...] = ()

    @property
    def matched(self) -> bool:
        return self.status == "matched" and self.entity_id is not None

    def as_dict(self) -> dict[str, Any]:
        """Serialize diagnostics without exposing implementation objects."""

        return {
            "status": self.status,
            "original_player_text": self.original_text or None,
            "matched_entity_id": self.entity_id,
            "matched_name": self.matched_name,
            "matched_alias": self.matched_alias,
            "match_method": self.method,
            "confidence": self.confidence,
            "candidates": [dict(candidate) for candidate in self.candidates],
        }


@dataclass(frozen=True, slots=True)
class TrailingPlayerRecovery:
    """A request-field cleanup produced by resolving a trailing player phrase."""

    fields: dict[str, Any]
    match: PlayerMatch | None = None
    field_name: str | None = None
    original_player_text: str | None = None
    player_phrase_detected: bool = False

    @property
    def recovered(self) -> bool:
        return self.match is not None and self.match.matched


def humanize_player_entity_id(entity_id: str) -> str:
    """Convert a media_player entity ID into a clean user-facing fallback name."""

    raw = str(entity_id).removeprefix("media_player.").replace("_", " ").strip()
    words = []
    for token in raw.split():
        lower = token.casefold()
        if lower == "tv":
            words.append("TV")
        else:
            words.append(token[:1].upper() + token[1:])
    return " ".join(words)


def normalize_player_text(value: str) -> str:
    """Normalize case, punctuation, spacing, and harmless TV initial variants."""

    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.casefold().strip()
    text = _PLAYER_PREFIX_RE.sub("", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    tokens = [token for token in _WHITESPACE_RE.split(text) if token]

    # Speech-to-text often emits the common acronym as "T V" or "T. V.".
    collapsed: list[str] = []
    index = 0
    while index < len(tokens):
        if index + 1 < len(tokens) and tokens[index] == "t" and tokens[index + 1] == "v":
            collapsed.append("tv")
            index += 2
            continue
        collapsed.append(tokens[index])
        index += 1
    return " ".join(collapsed)


def compact_player_text(value: str) -> str:
    """Return a spacing-insensitive player-name representation."""

    return normalize_player_text(value).replace(" ", "")


def _candidate_payload(
    candidate: PlayerCandidate,
    *,
    alias: str,
    score: float,
    method: str,
) -> dict[str, Any]:
    return {
        "entity_id": candidate.entity_id,
        "name": candidate.name,
        "alias": alias,
        "confidence": round(score, 1),
        "match_method": method,
    }


def _decision_from_hits(
    original: str,
    hits: Mapping[str, tuple[PlayerCandidate, str, float, str]],
    *,
    ambiguity_margin: float = 0.0,
) -> PlayerMatch:
    ordered = sorted(hits.values(), key=lambda value: (-value[2], value[0].entity_id))
    if not ordered:
        return PlayerMatch(status="not_found", original_text=original)

    best = ordered[0]
    close = [value for value in ordered if best[2] - value[2] <= ambiguity_margin]
    if len(close) > 1:
        return PlayerMatch(
            status="ambiguous",
            original_text=original,
            candidates=tuple(
                _candidate_payload(candidate, alias=alias, score=score, method=method)
                for candidate, alias, score, method in close[:5]
            ),
        )

    candidate, alias, score, method = best
    return PlayerMatch(
        status="matched",
        original_text=original,
        entity_id=candidate.entity_id,
        matched_name=candidate.name,
        matched_alias=alias,
        method=method,
        confidence=round(score, 1),
    )


def resolve_player_text(
    player_text: str,
    candidates: Sequence[PlayerCandidate],
    *,
    allow_fuzzy: bool,
) -> PlayerMatch:
    """Resolve a spoken player name using safe ordered matching tiers."""

    original = str(player_text).strip()
    if not original:
        return PlayerMatch(status="not_found", original_text=original)

    normalized = normalize_player_text(original)
    compact = compact_player_text(original)
    if not normalized:
        return PlayerMatch(status="not_found", original_text=original)

    # Entity IDs are explicit and never fuzzy matched.
    entity_hits = {
        candidate.entity_id: (
            candidate,
            candidate.preferred_response_name(),
            100.0,
            "entity_id",
        )
        for candidate in candidates
        if original.casefold() == candidate.entity_id.casefold()
    }
    if entity_hits:
        return _decision_from_hits(original, entity_hits)

    exact_hits: dict[str, tuple[PlayerCandidate, str, float, str]] = {}
    compact_hits: dict[str, tuple[PlayerCandidate, str, float, str]] = {}
    for candidate in candidates:
        for alias in candidate.spoken_names():
            alias_normalized = normalize_player_text(alias)
            if normalized == alias_normalized:
                exact_hits[candidate.entity_id] = (candidate, alias, 100.0, "normalized_exact")
                break
            if compact == compact_player_text(alias):
                compact_hits[candidate.entity_id] = (candidate, alias, 99.0, "compact_exact")
    if exact_hits:
        return _decision_from_hits(original, exact_hits)
    if compact_hits:
        return _decision_from_hits(original, compact_hits)

    if not allow_fuzzy:
        return PlayerMatch(status="not_found", original_text=original)

    input_tokens = tuple(normalized.split())
    token_hits: dict[str, tuple[PlayerCandidate, str, float, str]] = {}
    if compact and len(compact) >= 4 and input_tokens:
        input_set = set(input_tokens)
        for candidate in candidates:
            best: tuple[PlayerCandidate, str, float, str] | None = None
            for alias in candidate.spoken_names():
                alias_tokens = tuple(normalize_player_text(alias).split())
                alias_set = set(alias_tokens)
                if not alias_tokens or not input_set.issubset(alias_set):
                    continue
                coverage = len(input_set) / len(alias_set)
                if coverage < 0.5:
                    continue
                score = 90.0 + min(5.0, coverage * 5.0)
                value = (candidate, alias, score, "token_subset")
                if best is None or value[2] > best[2]:
                    best = value
            if best is not None:
                token_hits[candidate.entity_id] = best
    if token_hits:
        return _decision_from_hits(original, token_hits, ambiguity_margin=2.0)

    if len(compact) < 6:
        return PlayerMatch(status="not_found", original_text=original)

    fuzzy_hits: dict[str, tuple[PlayerCandidate, str, float, str]] = {}
    threshold = 90.0 if len(compact) >= 8 else 93.0
    for candidate in candidates:
        best: tuple[PlayerCandidate, str, float, str] | None = None
        for alias in candidate.spoken_names():
            alias_compact = compact_player_text(alias)
            if len(alias_compact) < 4:
                continue
            score = SequenceMatcher(None, compact, alias_compact).ratio() * 100.0
            value = (candidate, alias, score, "fuzzy_alias")
            if best is None or value[2] > best[2]:
                best = value
        if best is not None and best[2] >= threshold:
            fuzzy_hits[candidate.entity_id] = best
    if fuzzy_hits:
        return _decision_from_hits(original, fuzzy_hits, ambiguity_margin=6.0)

    return PlayerMatch(status="not_found", original_text=original)


def _looks_like_player_phrase(
    text: str,
    candidates: Sequence[PlayerCandidate],
) -> bool:
    normalized = normalize_player_text(text)
    tokens = set(normalized.split())
    if tokens & _PLAYER_HINT_TOKENS:
        return True
    compact = normalized.replace(" ", "")
    if len(compact) < 5:
        return False
    for candidate in candidates:
        for alias in candidate.spoken_names():
            if SequenceMatcher(None, compact, compact_player_text(alias)).ratio() >= 0.88:
                return True
    return False


def recover_trailing_player(
    fields: Mapping[str, Any],
    candidates: Sequence[PlayerCandidate],
    *,
    allow_fuzzy: bool,
    field_order: Sequence[str] = ("artist", "album", "series", "query"),
) -> TrailingPlayerRecovery:
    """Recover ``on/to/for <player>`` swallowed by a wildcard media slot."""

    cleaned = dict(fields)
    for field_name in field_order:
        raw_value = cleaned.get(field_name)
        if raw_value in (None, ""):
            continue
        text = str(raw_value).strip()
        matches = list(_TRAILING_PLAYER_RE.finditer(text))
        for suffix_match in reversed(matches):
            head = text[: suffix_match.start()].strip()
            player_text = text[suffix_match.end() :].strip()
            if not head or not player_text:
                continue
            match = resolve_player_text(
                player_text,
                candidates,
                allow_fuzzy=allow_fuzzy,
            )
            if match.matched or match.status == "ambiguous":
                # A bare partial suffix such as "Room on Fire" must not resolve
                # to a player named "Fire TV". Token-subset matches are accepted
                # here only when the suffix itself contains a player noun.
                if (
                    match.method == "token_subset"
                    and not (set(normalize_player_text(player_text).split()) & _PLAYER_HINT_TOKENS)
                ):
                    continue
                cleaned[field_name] = head
                return TrailingPlayerRecovery(
                    fields=cleaned,
                    match=match,
                    field_name=field_name,
                    original_player_text=player_text,
                    player_phrase_detected=True,
                )
            if _looks_like_player_phrase(player_text, candidates):
                cleaned[field_name] = head
                return TrailingPlayerRecovery(
                    fields=cleaned,
                    match=match,
                    field_name=field_name,
                    original_player_text=player_text,
                    player_phrase_detected=True,
                )
    return TrailingPlayerRecovery(fields=cleaned)


__all__ = [
    "PlayerCandidate",
    "PlayerMatch",
    "TrailingPlayerRecovery",
    "compact_player_text",
    "humanize_player_entity_id",
    "normalize_player_text",
    "recover_trailing_player",
    "resolve_player_text",
]
