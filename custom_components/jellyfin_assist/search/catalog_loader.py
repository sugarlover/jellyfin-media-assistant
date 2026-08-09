"""Read-only paginated Jellyfin catalog loading.

The robust matcher should not depend on Jellyfin's literal ``SearchTerm``
behavior.  This module retrieves a metadata-only snapshot in bounded pages and
returns plain mappings that can be passed to :class:`~.catalog_index.CatalogIndex`.

The loader is deliberately Home-Assistant-independent.  It receives an injected
async page fetcher, deduplicates by Jellyfin item ID, preserves first-seen order,
and exposes pagination diagnostics.  It never downloads media or images and
contains no write operation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .items import catalog_item_id


MUSIC_ARTIST_MEDIA_TYPE = "MusicArtist"
DEFAULT_CATALOG_MEDIA_TYPES = (
    "Movie",
    "Series",
    "Episode",
    "Audio",
    "MusicAlbum",
    MUSIC_ARTIST_MEDIA_TYPE,
)
SUPPORTED_CATALOG_MEDIA_TYPES = frozenset(DEFAULT_CATALOG_MEDIA_TYPES)


class CatalogLoadStopReason(StrEnum):
    """Why a catalog snapshot stopped loading."""

    COMPLETE = "complete"
    MAX_ITEMS_REACHED = "max_items_reached"


class CatalogPageResponseError(TypeError):
    """Raised when a page fetcher returns an invalid page payload."""


@dataclass(frozen=True, slots=True)
class CatalogPageRequest:
    """One bounded metadata-page request.

    ``MusicArtist`` uses a separate Jellyfin endpoint and therefore must be the
    only type in its request group.  Other supported item types may be grouped
    into one ``/Users/{user_id}/Items`` request.
    """

    item_types: tuple[str, ...]
    start_index: int
    limit: int

    def __post_init__(self) -> None:
        if not self.item_types:
            raise ValueError("item_types must not be empty")
        normalized = tuple(dict.fromkeys(self.item_types))
        if normalized != self.item_types:
            raise ValueError("item_types must be unique and ordered")
        unsupported = [
            media_type
            for media_type in self.item_types
            if media_type not in SUPPORTED_CATALOG_MEDIA_TYPES
        ]
        if unsupported:
            raise ValueError(f"unsupported catalog media type: {unsupported[0]}")
        if (
            MUSIC_ARTIST_MEDIA_TYPE in self.item_types
            and self.item_types != (MUSIC_ARTIST_MEDIA_TYPE,)
        ):
            raise ValueError("MusicArtist must use its own catalog page request")
        if self.start_index < 0:
            raise ValueError("start_index must not be negative")
        if self.limit <= 0:
            raise ValueError("limit must be positive")


@dataclass(frozen=True, slots=True)
class CatalogPage:
    """One validated page returned by a concrete Jellyfin client."""

    request: CatalogPageRequest
    items: tuple[dict[str, Any], ...]
    total_record_count: int | None

    def __post_init__(self) -> None:
        if any(not isinstance(item, Mapping) for item in self.items):
            raise CatalogPageResponseError("catalog page items must be mappings")
        if self.total_record_count is not None and self.total_record_count < 0:
            raise CatalogPageResponseError(
                "catalog page total_record_count must not be negative"
            )


CatalogPageFetcher = Callable[[CatalogPageRequest], Awaitable[CatalogPage]]


@dataclass(frozen=True, slots=True)
class CatalogLoadedPage:
    """Transparent diagnostics for one completed catalog page request."""

    request: CatalogPageRequest
    returned_count: int
    accepted_count: int
    total_record_count: int | None


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """Deduplicated metadata snapshot suitable for ``CatalogIndex.build``."""

    requested_types: tuple[str, ...]
    items: tuple[dict[str, Any], ...]
    pages: tuple[CatalogLoadedPage, ...]
    raw_item_count: int
    duplicate_item_count: int
    missing_id_count: int
    server_overflow_item_count: int
    stop_reason: CatalogLoadStopReason

    @property
    def truncated(self) -> bool:
        """Return whether a caller-supplied item cap ended the load early."""

        return self.stop_reason is CatalogLoadStopReason.MAX_ITEMS_REACHED



def normalize_catalog_media_types(
    item_types: Sequence[str] | None,
) -> tuple[str, ...]:
    """Validate and deduplicate requested media types while preserving order."""

    source = DEFAULT_CATALOG_MEDIA_TYPES if item_types is None else item_types
    if isinstance(source, (str, bytes)):
        raise TypeError("item_types must be a sequence of media-type strings")

    normalized: list[str] = []
    for value in source:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("catalog media types must be non-empty strings")
        media_type = value.strip()
        if media_type not in SUPPORTED_CATALOG_MEDIA_TYPES:
            raise ValueError(f"unsupported catalog media type: {media_type}")
        if media_type not in normalized:
            normalized.append(media_type)

    if not normalized:
        raise ValueError("at least one catalog media type is required")
    return tuple(normalized)



def catalog_request_groups(item_types: Sequence[str] | None) -> tuple[tuple[str, ...], ...]:
    """Return regular-items and artist request groups in stable order."""

    normalized = normalize_catalog_media_types(item_types)
    regular = tuple(
        media_type
        for media_type in normalized
        if media_type != MUSIC_ARTIST_MEDIA_TYPE
    )
    groups: list[tuple[str, ...]] = []
    if regular:
        groups.append(regular)
    if MUSIC_ARTIST_MEDIA_TYPE in normalized:
        groups.append((MUSIC_ARTIST_MEDIA_TYPE,))
    return tuple(groups)


async def load_catalog_snapshot(
    fetch_page: CatalogPageFetcher,
    *,
    item_types: Sequence[str] | None = None,
    page_size: int = 500,
    max_items: int | None = None,
) -> CatalogSnapshot:
    """Load one metadata-only catalog snapshot through an injected page client.

    Pagination is sequential so diagnostics and item order remain deterministic.
    The loader stops when Jellyfin's reported total is reached, when a short or
    empty page proves completion, or when the optional unique-item cap is met.
    """

    if not callable(fetch_page):
        raise TypeError("fetch_page must be callable")
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if max_items is not None and max_items <= 0:
        raise ValueError("max_items must be positive when supplied")

    normalized_types = normalize_catalog_media_types(item_types)
    groups = catalog_request_groups(normalized_types)
    items: list[dict[str, Any]] = []
    pages: list[CatalogLoadedPage] = []
    seen_ids: set[str] = set()
    raw_item_count = 0
    duplicate_item_count = 0
    missing_id_count = 0
    server_overflow_item_count = 0
    stop_reason = CatalogLoadStopReason.COMPLETE

    for group in groups:
        start_index = 0
        while True:
            request_limit = page_size
            if max_items is not None:
                remaining = max_items - len(items)
                if remaining <= 0:
                    stop_reason = CatalogLoadStopReason.MAX_ITEMS_REACHED
                    break
                request_limit = min(request_limit, remaining)

            request = CatalogPageRequest(
                item_types=group,
                start_index=start_index,
                limit=request_limit,
            )
            page = await fetch_page(request)
            if not isinstance(page, CatalogPage):
                raise CatalogPageResponseError(
                    "catalog page fetcher must return CatalogPage"
                )
            if page.request != request:
                raise CatalogPageResponseError(
                    "catalog page response request does not match the issued request"
                )

            returned_items = page.items[: request.limit]
            server_overflow_item_count += max(0, len(page.items) - len(returned_items))
            raw_item_count += len(returned_items)
            accepted_count = 0

            for raw_item in returned_items:
                copied = dict(raw_item)
                item_id = catalog_item_id(copied)
                if item_id is None:
                    missing_id_count += 1
                    items.append(copied)
                    accepted_count += 1
                elif item_id in seen_ids:
                    duplicate_item_count += 1
                else:
                    seen_ids.add(item_id)
                    items.append(copied)
                    accepted_count += 1

                if max_items is not None and len(items) >= max_items:
                    stop_reason = CatalogLoadStopReason.MAX_ITEMS_REACHED
                    break

            pages.append(
                CatalogLoadedPage(
                    request=request,
                    returned_count=len(returned_items),
                    accepted_count=accepted_count,
                    total_record_count=page.total_record_count,
                )
            )

            if stop_reason is CatalogLoadStopReason.MAX_ITEMS_REACHED:
                break

            returned_count = len(returned_items)
            if returned_count == 0:
                break

            next_start = start_index + returned_count
            if (
                page.total_record_count is not None
                and next_start >= page.total_record_count
            ):
                break
            if returned_count < request.limit:
                break
            start_index = next_start

        if stop_reason is CatalogLoadStopReason.MAX_ITEMS_REACHED:
            break

    return CatalogSnapshot(
        requested_types=normalized_types,
        items=tuple(items),
        pages=tuple(pages),
        raw_item_count=raw_item_count,
        duplicate_item_count=duplicate_item_count,
        missing_id_count=missing_id_count,
        server_overflow_item_count=server_overflow_item_count,
        stop_reason=stop_reason,
    )
