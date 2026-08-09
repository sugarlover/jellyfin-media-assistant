"""Stable Home Assistant action-response serialization for robust search.

The search engine intentionally remains Home-Assistant-independent until the
integration registration step.  This module is the contract boundary between
internal immutable dataclasses and the plain JSON-safe mapping that a future
``jellyfin_assist.search`` action will return.

The top-level ``items`` field preserves the existing resolver convention:

* one item for a confident match,
* ranked items for an ambiguous result, and
* an empty list for no match.

All richer diagnostics are additive so existing resolver/orchestrator/playback
and queue contracts can remain unchanged during shadow testing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import math
from typing import Any

from ..matching.context import ContextEvidence, MediaSearchContext
from ..matching.pipeline import RankedSearchCandidate, RejectedSearchCandidate
from ..matching.normalization import build_text_profile
from .catalog_index import CatalogIndexRecord, CatalogShortlistEntry
from .catalog_manager import CatalogManagerDiagnostics, ManagedCatalogSearchOutcome
from .items import first_artist, first_nonempty, first_year


SEARCH_RESPONSE_SCHEMA_VERSION = 1
DEFAULT_RESPONSE_ITEM_LIMIT = 5
DEFAULT_DIAGNOSTIC_LIMIT = 10
_TICKS_PER_MINUTE = 600_000_000


@dataclass(frozen=True, slots=True)
class SearchResponseOptions:
    """Bounded output controls for one action response."""

    item_limit: int = DEFAULT_RESPONSE_ITEM_LIMIT
    diagnostic_limit: int = DEFAULT_DIAGNOSTIC_LIMIT

    def __post_init__(self) -> None:
        if self.item_limit <= 0:
            raise ValueError("item_limit must be positive")
        if self.diagnostic_limit <= 0:
            raise ValueError("diagnostic_limit must be positive")


def _json_safe(value: Any) -> Any:
    """Return recursively JSON-safe data with enums represented by values."""

    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe(nested) for nested in value]
    return str(value)


def _first_value(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _first_bool(item: Mapping[str, Any], *keys: str) -> bool | None:
    value = _first_value(item, *keys)
    if isinstance(value, bool):
        return value
    return None


def _first_sequence(item: Mapping[str, Any], *keys: str) -> list[Any]:
    value = _first_value(item, *keys)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _runtime_minutes(item: Mapping[str, Any]) -> int | None:
    direct = _first_value(item, "runtime_minutes")
    if isinstance(direct, int) and not isinstance(direct, bool):
        return direct
    ticks = _first_value(item, "RunTimeTicks", "runtime_ticks")
    if isinstance(ticks, int) and not isinstance(ticks, bool) and ticks > 0:
        return int(ticks / _TICKS_PER_MINUTE)
    return None


def _user_data(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("UserData")
    return value if isinstance(value, Mapping) else {}


def serialize_catalog_record(record: CatalogIndexRecord) -> dict[str, Any]:
    """Return a resolver-compatible metadata item for one logical record."""

    raw = record.item
    user_data = _user_data(raw)
    media_type = first_nonempty(raw, "type", "Type") or record.candidate.media_type
    year = first_year(raw)
    index_number = _first_value(raw, "index_number", "IndexNumber")
    parent_index_number = _first_value(
        raw, "parent_index_number", "ParentIndexNumber"
    )
    normalized_media_type = (
        "".join(character for character in media_type.casefold() if character.isalnum())
        if isinstance(media_type, str)
        else ""
    )
    is_audio = normalized_media_type == "audio"

    if is_audio:
        season_number = None
        season_name = None
        episode_number = None
        disc_number = parent_index_number
        track_number = index_number
    else:
        season_number = parent_index_number
        season_name = first_nonempty(raw, "season_name", "SeasonName")
        if season_name is None and season_number is not None:
            season_name = f"Season {season_number}"
        episode_number = index_number
        disc_number = None
        track_number = None

    album_artist = first_nonempty(raw, "album_artist", "AlbumArtist")
    artist_name = first_artist(raw) or record.candidate.artist
    provider_ids = dict(record.provider_ids)
    physical_ids = list(record.physical_item_ids)

    return {
        "id": record.item_id,
        "name": record.candidate.title,
        "type": media_type,
        "year": year,
        "runtime_minutes": _runtime_minutes(raw),
        "genres": _first_sequence(raw, "genres", "Genres"),
        "rating": _first_value(raw, "rating", "CommunityRating"),
        "description": first_nonempty(raw, "description", "Overview") or "",
        "series_name": first_nonempty(raw, "series_name", "SeriesName")
        or record.candidate.series
        or "",
        "series_id": first_nonempty(raw, "series_id", "SeriesId") or "",
        "season_name": season_name or "",
        "season_number": season_number,
        "index_number": index_number,
        "episode_number": episode_number,
        "disc_number": disc_number,
        "track_number": track_number,
        "artist_name": artist_name or "",
        "album_artist": album_artist or "",
        "album": first_nonempty(raw, "album", "Album")
        or record.candidate.album
        or "",
        "is_played": _first_bool(raw, "is_played")
        if _first_bool(raw, "is_played") is not None
        else user_data.get("Played"),
        "is_favorite": _first_bool(raw, "is_favorite")
        if _first_bool(raw, "is_favorite") is not None
        else user_data.get("IsFavorite"),
        "official_rating": _first_value(raw, "official_rating", "OfficialRating"),
        "community_rating": _first_value(
            raw, "community_rating", "CommunityRating", "rating"
        ),
        "provider_ids": provider_ids,
        "physical_ids": physical_ids,
        "is_logical_group": record.is_logical_group,
    }


def _context_to_dict(context: MediaSearchContext) -> dict[str, Any]:
    return {
        "media_type": context.media_type,
        "artist": context.artist,
        "album": context.album,
        "series": context.series,
        "year": context.year,
    }


def _evidence_to_dict(evidence: ContextEvidence) -> dict[str, Any]:
    return {
        "field": evidence.field.value,
        "requested": evidence.requested,
        "candidate": evidence.candidate,
        "relation": evidence.relation.value,
        "adjustment": evidence.adjustment,
        "method": evidence.method.value if evidence.method is not None else None,
    }


def _match_to_dict(candidate: RankedSearchCandidate) -> dict[str, Any]:
    match = candidate.title_match
    details: dict[str, Any] = {
        "family": match.family.value,
        "method": match.method.value,
        "lexical_score": match.lexical_score,
        "phonetic_score": match.phonetic_score,
        "context_score": candidate.context_score,
        "total_score": candidate.total_score,
        "matched_alias": match.matched_alias,
    }
    if match.deterministic is not None:
        details["deterministic"] = {
            "shared_value": match.deterministic.shared_value,
            "query_methods": [
                method.value for method in match.deterministic.query_methods
            ],
            "candidate_methods": [
                method.value for method in match.deterministic.candidate_methods
            ],
        }
    if match.fuzzy is not None:
        details["fuzzy"] = {
            "edit_distance": match.fuzzy.edit_distance,
            "similarity": match.fuzzy.similarity,
            "query_value": match.fuzzy.query_value,
            "candidate_value": match.fuzzy.candidate_value,
        }
    if match.phonetic is not None:
        details["phonetic"] = {
            "lexical_similarity": match.phonetic.lexical_similarity,
            "query_value": match.phonetic.query_value,
            "candidate_value": match.phonetic.candidate_value,
            "query_signature": list(match.phonetic.query_signature),
            "candidate_signature": list(match.phonetic.candidate_signature),
        }
    return details


def _shortlist_map(
    entries: Sequence[CatalogShortlistEntry],
) -> dict[str, CatalogShortlistEntry]:
    return {entry.record.item_id: entry for entry in entries}


def _ranked_candidate_to_dict(
    ranked: RankedSearchCandidate,
    *,
    rank: int,
    record: CatalogIndexRecord | None,
    shortlist_entry: CatalogShortlistEntry | None,
) -> dict[str, Any]:
    item = (
        serialize_catalog_record(record)
        if record is not None
        else {
            "id": ranked.candidate.key,
            "name": ranked.candidate.title,
            "type": ranked.candidate.media_type,
            "year": ranked.candidate.year,
            "artist_name": ranked.candidate.artist or "",
            "album": ranked.candidate.album or "",
            "series_name": ranked.candidate.series or "",
            "provider_ids": dict(ranked.candidate.provider_ids),
            "physical_ids": list(
                ranked.candidate.physical_keys or (ranked.candidate.key,)
            ),
        }
    )
    return {
        "rank": rank,
        "item": item,
        "match": _match_to_dict(ranked),
        "context_evidence": [
            _evidence_to_dict(evidence) for evidence in ranked.evidence
        ],
        "shortlisted_by": [
            method.value for method in shortlist_entry.methods
        ]
        if shortlist_entry is not None
        else [],
    }


def _rejected_to_dict(rejected: RejectedSearchCandidate) -> dict[str, Any]:
    return {
        "id": rejected.candidate.key,
        "name": rejected.candidate.title,
        "type": rejected.candidate.media_type,
        "reason": rejected.reason,
        "match": {
            "family": rejected.title_match.family.value,
            "method": rejected.title_match.method.value,
            "lexical_score": rejected.title_match.lexical_score,
            "phonetic_score": rejected.title_match.phonetic_score,
        },
        "context_evidence": [
            _evidence_to_dict(evidence) for evidence in rejected.evidence
        ],
    }


def _catalog_diagnostics_to_dict(
    diagnostics: CatalogManagerDiagnostics,
) -> dict[str, Any]:
    return {
        "available": diagnostics.available,
        "source": diagnostics.source.value,
        "refresh_in_progress": diagnostics.refresh_in_progress,
        "requested_types": list(diagnostics.requested_types),
        "catalog_created_at": diagnostics.catalog_created_at,
        "cache_age_seconds": diagnostics.cache_age_seconds,
        "page_count": diagnostics.page_count,
        "snapshot_item_count": diagnostics.snapshot_item_count,
        "raw_item_count": diagnostics.raw_item_count,
        "indexed_record_count": diagnostics.indexed_record_count,
        "logical_group_count": diagnostics.logical_group_count,
        "grouped_physical_item_count": diagnostics.grouped_physical_item_count,
        "index_issue_count": diagnostics.index_issue_count,
        "duplicate_item_count": diagnostics.duplicate_item_count,
        "timing_ms": {
            "cache_load": diagnostics.last_cache_load_duration_ms,
            "refresh": diagnostics.last_refresh_duration_ms,
            "index_build": diagnostics.last_index_build_duration_ms,
            "cache_write": diagnostics.last_cache_write_duration_ms,
            "search": diagnostics.last_search_duration_ms,
        },
        "search_count": diagnostics.search_count,
        "last_error": diagnostics.last_error,
    }


def serialize_search_action_response(
    managed: ManagedCatalogSearchOutcome,
    *,
    options: SearchResponseOptions | None = None,
) -> dict[str, Any]:
    """Serialize one managed local search into the stable action contract."""

    if not isinstance(managed, ManagedCatalogSearchOutcome):
        raise TypeError("managed must be ManagedCatalogSearchOutcome")
    settings = options or SearchResponseOptions()
    outcome = managed.outcome
    decision = outcome.decision
    shortlist_by_id = _shortlist_map(outcome.shortlist)
    records_by_id = {
        entry.record.item_id: entry.record for entry in outcome.shortlist
    }

    if decision.automatic_selection_allowed and decision.selected is not None:
        visible_ranked = (decision.selected,)
    elif decision.selection_required:
        visible_ranked = decision.alternatives[: settings.item_limit]
    else:
        visible_ranked = ()

    visible_details = [
        _ranked_candidate_to_dict(
            ranked,
            rank=index + 1,
            record=records_by_id.get(ranked.candidate.key),
            shortlist_entry=shortlist_by_id.get(ranked.candidate.key),
        )
        for index, ranked in enumerate(visible_ranked)
    ]
    items = [detail["item"] for detail in visible_details]
    selected_item = items[0] if decision.automatic_selection_allowed and items else None
    selected_detail = (
        visible_details[0]
        if decision.automatic_selection_allowed and visible_details
        else None
    )

    all_ranked = outcome.ranking.matches[: settings.diagnostic_limit]
    ranked_diagnostics = [
        _ranked_candidate_to_dict(
            ranked,
            rank=index + 1,
            record=records_by_id.get(ranked.candidate.key),
            shortlist_entry=shortlist_by_id.get(ranked.candidate.key),
        )
        for index, ranked in enumerate(all_ranked)
    ]
    profile = build_text_profile(outcome.query)

    response = {
        "schema_version": SEARCH_RESPONSE_SCHEMA_VERSION,
        "query": outcome.query,
        "context": _context_to_dict(outcome.context),
        "items": items,
        "item": selected_item,
        "selected": selected_item,
        "jellyfin_id": selected_item.get("id") if selected_item else None,
        "decision": {
            "status": decision.status.value,
            "reason": decision.reason.value,
            "automatic_selection_allowed": decision.automatic_selection_allowed,
            "selection_required": decision.selection_required,
            "active_family": (
                decision.active_family.value
                if decision.active_family is not None
                else None
            ),
            "required_minimum_score": decision.required_minimum_score,
            "required_margin": decision.required_margin,
            "required_minimum_similarity": decision.required_minimum_similarity,
            "observed_margin": decision.observed_margin,
        },
        "match": selected_detail["match"] if selected_detail else None,
        "alternatives": visible_details if decision.selection_required else [],
        "catalog": _catalog_diagnostics_to_dict(managed.diagnostics),
        "diagnostics": {
            "original_query": outcome.query,
            "attempted_variants": [
                {
                    "value": variant.value,
                    "methods": [method.value for method in variant.methods],
                }
                for variant in profile.variants
            ],
            "eligible_record_count": outcome.eligible_record_count,
            "shortlist_count": len(outcome.shortlist),
            "ranked_candidate_count": len(outcome.ranking.matches),
            "returned_item_count": len(items),
            "ranked_candidates": ranked_diagnostics,
            "rejected_count": len(outcome.ranking.rejected),
            "rejected": [
                _rejected_to_dict(rejected)
                for rejected in outcome.ranking.rejected[: settings.diagnostic_limit]
            ],
            "search_duration_ms": managed.search_duration_ms,
        },
    }
    return _json_safe(response)


__all__ = [
    "DEFAULT_DIAGNOSTIC_LIMIT",
    "DEFAULT_RESPONSE_ITEM_LIMIT",
    "SEARCH_RESPONSE_SCHEMA_VERSION",
    "SearchResponseOptions",
    "serialize_catalog_record",
    "serialize_search_action_response",
]
