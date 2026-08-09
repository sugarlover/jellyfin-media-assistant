"""Versioned metadata-only disk cache for Jellyfin catalog snapshots.

The cache contains only the fields needed by the robust search index. It never
stores connection credentials, headers, media paths, images, or playback state.
Writes use a temporary file in the destination directory followed by
``os.replace`` so readers never observe a partially written cache.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from .catalog_loader import (
    CatalogLoadedPage,
    CatalogLoadStopReason,
    CatalogPageRequest,
    CatalogSnapshot,
    normalize_catalog_media_types,
)


CATALOG_CACHE_SCHEMA_VERSION = 1
DEFAULT_MAX_CACHE_BYTES = 128 * 1024 * 1024

# Raw Jellyfin responses may contain additional harmless metadata. Persist only
# the fields used by current/future search, item expansion, and diagnostics.
_CACHE_ITEM_FIELDS = frozenset(
    {
        "Id",
        "Name",
        "Type",
        "OriginalTitle",
        "SortName",
        "ProductionYear",
        "Album",
        "AlbumId",
        "AlbumArtist",
        "AlbumArtists",
        "Artists",
        "SeriesName",
        "SeriesId",
        "ParentId",
        "IndexNumber",
        "ParentIndexNumber",
        "ProviderIds",
        "RunTimeTicks",
        # JellyHA-transformed equivalents retained for compatibility tests.
        "id",
        "name",
        "type",
        "original_title",
        "sort_name",
        "year",
        "album",
        "album_id",
        "album_artist",
        "artists",
        "artist_name",
        "series_name",
        "series_id",
        "parent_id",
        "index_number",
        "parent_index_number",
        "provider_ids",
        "runtime_ticks",
    }
)


class CatalogCacheError(RuntimeError):
    """Base class for catalog-cache failures."""


class CatalogCacheValidationError(CatalogCacheError):
    """Raised when an existing cache cannot be trusted."""


class CatalogCacheWriteError(CatalogCacheError):
    """Raised when an atomic cache write fails."""


@dataclass(frozen=True, slots=True)
class CatalogCacheDocument:
    """One validated cache document and its catalog snapshot."""

    identity: str
    created_at: float
    snapshot: CatalogSnapshot


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe metadata value or ``None`` when unsupported."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                continue
            safe = _json_safe(nested)
            if safe is not None:
                output[key] = safe
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        output = []
        for nested in value:
            safe = _json_safe(nested)
            if safe is not None:
                output.append(safe)
        return output
    return None


def sanitize_catalog_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Return a metadata-only cache copy of one catalog item."""

    output: dict[str, Any] = {}
    for key in _CACHE_ITEM_FIELDS:
        if key not in item:
            continue
        safe = _json_safe(item[key])
        if safe is not None:
            output[key] = safe
    return output


def sanitize_catalog_snapshot(snapshot: CatalogSnapshot) -> CatalogSnapshot:
    """Return a cache-safe snapshot with the same diagnostics."""

    return CatalogSnapshot(
        requested_types=snapshot.requested_types,
        items=tuple(sanitize_catalog_item(item) for item in snapshot.items),
        pages=snapshot.pages,
        raw_item_count=snapshot.raw_item_count,
        duplicate_item_count=snapshot.duplicate_item_count,
        missing_id_count=snapshot.missing_id_count,
        server_overflow_item_count=snapshot.server_overflow_item_count,
        stop_reason=snapshot.stop_reason,
    )


def catalog_cache_filename(item_types: Sequence[str] | None) -> str:
    """Return a stable filename for one ordered catalog type set."""

    normalized = normalize_catalog_media_types(item_types)
    slug = "-".join(media_type.casefold() for media_type in normalized)
    return f"catalog-{slug}.json"


def _page_to_dict(page: CatalogLoadedPage) -> dict[str, Any]:
    request = page.request
    return {
        "item_types": list(request.item_types),
        "start_index": request.start_index,
        "limit": request.limit,
        "returned_count": page.returned_count,
        "accepted_count": page.accepted_count,
        "total_record_count": page.total_record_count,
    }


def _snapshot_to_dict(snapshot: CatalogSnapshot) -> dict[str, Any]:
    return {
        "requested_types": list(snapshot.requested_types),
        "items": [dict(item) for item in snapshot.items],
        "pages": [_page_to_dict(page) for page in snapshot.pages],
        "raw_item_count": snapshot.raw_item_count,
        "duplicate_item_count": snapshot.duplicate_item_count,
        "missing_id_count": snapshot.missing_id_count,
        "server_overflow_item_count": snapshot.server_overflow_item_count,
        "stop_reason": snapshot.stop_reason.value,
    }


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise CatalogCacheValidationError(f"{name} must be an integer >= {minimum}")
    return value


def _page_from_dict(raw: Any) -> CatalogLoadedPage:
    if not isinstance(raw, Mapping):
        raise CatalogCacheValidationError("cache page must be an object")
    item_types = raw.get("item_types")
    if not isinstance(item_types, list) or any(
        not isinstance(value, str) for value in item_types
    ):
        raise CatalogCacheValidationError("cache page item_types must be strings")
    request = CatalogPageRequest(
        item_types=tuple(item_types),
        start_index=_require_int(raw.get("start_index"), "page start_index"),
        limit=_require_int(raw.get("limit"), "page limit", minimum=1),
    )
    total = raw.get("total_record_count")
    if total is not None:
        total = _require_int(total, "page total_record_count")
    return CatalogLoadedPage(
        request=request,
        returned_count=_require_int(raw.get("returned_count"), "page returned_count"),
        accepted_count=_require_int(raw.get("accepted_count"), "page accepted_count"),
        total_record_count=total,
    )


def _snapshot_from_dict(raw: Any) -> CatalogSnapshot:
    if not isinstance(raw, Mapping):
        raise CatalogCacheValidationError("cache snapshot must be an object")

    raw_types = raw.get("requested_types")
    if not isinstance(raw_types, list):
        raise CatalogCacheValidationError("cache requested_types must be a list")
    requested_types = normalize_catalog_media_types(raw_types)

    raw_items = raw.get("items")
    if not isinstance(raw_items, list) or any(
        not isinstance(item, Mapping) for item in raw_items
    ):
        raise CatalogCacheValidationError("cache items must be objects")
    items = tuple(sanitize_catalog_item(item) for item in raw_items)

    raw_pages = raw.get("pages", [])
    if not isinstance(raw_pages, list):
        raise CatalogCacheValidationError("cache pages must be a list")
    pages = tuple(_page_from_dict(page) for page in raw_pages)

    stop_value = raw.get("stop_reason")
    try:
        stop_reason = CatalogLoadStopReason(stop_value)
    except (TypeError, ValueError) as err:
        raise CatalogCacheValidationError("cache stop_reason is invalid") from err

    return CatalogSnapshot(
        requested_types=requested_types,
        items=items,
        pages=pages,
        raw_item_count=_require_int(raw.get("raw_item_count"), "raw_item_count"),
        duplicate_item_count=_require_int(
            raw.get("duplicate_item_count"), "duplicate_item_count"
        ),
        missing_id_count=_require_int(raw.get("missing_id_count"), "missing_id_count"),
        server_overflow_item_count=_require_int(
            raw.get("server_overflow_item_count"), "server_overflow_item_count"
        ),
        stop_reason=stop_reason,
    )


@dataclass(frozen=True, slots=True)
class CatalogCacheStore:
    """Read and atomically replace one versioned catalog cache file."""

    path: Path
    max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if self.max_cache_bytes <= 0:
            raise ValueError("max_cache_bytes must be positive")

    def load(
        self,
        *,
        expected_identity: str,
        expected_types: Sequence[str] | None,
    ) -> CatalogCacheDocument | None:
        """Load and validate the cache, returning ``None`` when absent."""

        if not self.path.exists():
            return None
        try:
            size = self.path.stat().st_size
            if size > self.max_cache_bytes:
                raise CatalogCacheValidationError("catalog cache exceeds size limit")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except CatalogCacheValidationError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as err:
            raise CatalogCacheValidationError("catalog cache could not be read") from err

        if not isinstance(raw, Mapping):
            raise CatalogCacheValidationError("catalog cache root must be an object")
        if raw.get("schema_version") != CATALOG_CACHE_SCHEMA_VERSION:
            raise CatalogCacheValidationError("catalog cache schema version is unsupported")
        identity = raw.get("identity")
        if not isinstance(identity, str) or identity != expected_identity:
            raise CatalogCacheValidationError("catalog cache identity does not match")
        created_at = raw.get("created_at")
        if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
            raise CatalogCacheValidationError("catalog cache created_at is invalid")
        created_at = float(created_at)
        if not math.isfinite(created_at) or created_at < 0:
            raise CatalogCacheValidationError("catalog cache created_at is invalid")

        snapshot = _snapshot_from_dict(raw.get("snapshot"))
        if snapshot.requested_types != normalize_catalog_media_types(expected_types):
            raise CatalogCacheValidationError("catalog cache media types do not match")
        return CatalogCacheDocument(
            identity=identity,
            created_at=created_at,
            snapshot=snapshot,
        )

    def write(self, document: CatalogCacheDocument) -> None:
        """Atomically write one validated metadata-only cache document."""

        identity = document.identity.strip()
        if not identity:
            raise CatalogCacheWriteError("catalog cache identity must not be empty")
        if not math.isfinite(document.created_at) or document.created_at < 0:
            raise CatalogCacheWriteError("catalog cache created_at is invalid")

        snapshot = sanitize_catalog_snapshot(document.snapshot)
        payload = {
            "schema_version": CATALOG_CACHE_SCHEMA_VERSION,
            "identity": identity,
            "created_at": document.created_at,
            "snapshot": _snapshot_to_dict(snapshot),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > self.max_cache_bytes:
            raise CatalogCacheWriteError("catalog cache exceeds size limit")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            with temp_path.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except OSError as err:
            raise CatalogCacheWriteError("catalog cache could not be written") from err
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
