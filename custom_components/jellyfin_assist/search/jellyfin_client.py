"""Concrete Jellyfin catalog client compatible with the current JellyHA API.

The pure retrieval pipeline accepts any asynchronous callable that receives a
:class:`~.retrieval.CatalogSearchRequest`.  This module supplies the first
concrete implementation of that callable without importing Home Assistant.

``JellyfinCatalogClient`` can be built directly from an API object and user ID,
or from the coordinator shape used by the installed JellyHA integration.  It
translates requests into the existing ``get_library_items`` call and preserves
JellyHA's special ``MusicArtist`` endpoint behavior.

The adapter deliberately returns raw Jellyfin mappings.  Local ranking already
understands raw and transformed item shapes, and leaving transformation to a
later Home Assistant action avoids signed-URL and Home Assistant dependencies in
this layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .catalog_loader import (
    MUSIC_ARTIST_MEDIA_TYPE,
    CatalogPage,
    CatalogPageRequest,
)
from .retrieval import CatalogSearchRequest


class JellyfinCatalogConfigurationError(ValueError):
    """Raised when an API object, coordinator, or user ID is unavailable."""


class JellyfinCatalogResponseError(TypeError):
    """Raised when the Jellyfin-compatible API returns an invalid payload."""


def _coerce_item_sequence(value: Any, *, source: str) -> tuple[dict[str, Any], ...]:
    """Validate and copy one sequence of Jellyfin item mappings."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise JellyfinCatalogResponseError(
            f"{source} must return a sequence of item mappings"
        )
    if any(not isinstance(item, Mapping) for item in value):
        raise JellyfinCatalogResponseError(
            f"{source} returned a non-mapping item"
        )
    return tuple(dict(item) for item in value)


def _coordinator_entry(coordinator: Any) -> Any:
    """Return the JellyHA config entry from either supported attribute name."""

    for attribute in ("entry", "config_entry"):
        entry = getattr(coordinator, attribute, None)
        if entry is not None:
            return entry
    raise JellyfinCatalogConfigurationError(
        "coordinator does not expose entry or config_entry"
    )


@dataclass(frozen=True, slots=True)
class JellyfinCatalogClient:
    """Translate pure catalog requests into the current JellyHA API surface."""

    api: Any
    user_id: str

    def __post_init__(self) -> None:
        if self.api is None:
            raise JellyfinCatalogConfigurationError("catalog API is not available")
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise JellyfinCatalogConfigurationError("Jellyfin user_id is required")
        object.__setattr__(self, "user_id", self.user_id.strip())

    @classmethod
    def from_jellyha_coordinator(cls, coordinator: Any) -> "JellyfinCatalogClient":
        """Build the client from the coordinator contract used by JellyHA.

        Current JellyHA library coordinators expose the API as ``_api`` and the
        selected Jellyfin user under ``entry.data['user_id']``.  A
        ``config_entry`` fallback is accepted because other JellyHA code paths
        use that name.
        """

        api = getattr(coordinator, "_api", None)
        if api is None:
            raise JellyfinCatalogConfigurationError(
                "coordinator Jellyfin API is not initialized"
            )

        entry = _coordinator_entry(coordinator)
        data = getattr(entry, "data", None)
        if not isinstance(data, Mapping):
            raise JellyfinCatalogConfigurationError(
                "coordinator config entry does not expose mapping data"
            )

        user_id = data.get("user_id")
        return cls(api=api, user_id=user_id)


    async def fetch_catalog_page(
        self,
        request: CatalogPageRequest,
    ) -> CatalogPage:
        """Fetch one metadata-only page for the local catalog index.

        This uses the same read-only ``_request`` seam exposed by JellyHA and
        the standalone validation client.  Regular library types share the
        user-items endpoint; album artists use Jellyfin's dedicated endpoint.
        """

        method = getattr(self.api, "_request", None)
        if not callable(method):
            raise JellyfinCatalogConfigurationError(
                "catalog API does not provide the read-only request method"
            )

        if request.item_types == (MUSIC_ARTIST_MEDIA_TYPE,):
            endpoint = "/Artists/AlbumArtists"
            params = {
                "UserId": self.user_id,
                "SortBy": "SortName",
                "SortOrder": "Ascending",
                "StartIndex": str(request.start_index),
                "Limit": str(request.limit),
                "Fields": "ProviderIds,SortName",
            }
        else:
            endpoint = f"/Users/{self.user_id}/Items"
            params = {
                "SortBy": "SortName",
                "SortOrder": "Ascending",
                "Recursive": "true",
                "IncludeItemTypes": ",".join(request.item_types),
                "StartIndex": str(request.start_index),
                "Limit": str(request.limit),
                "Fields": (
                    "Album,AlbumArtist,Artists,IndexNumber,OriginalTitle,"
                    "ParentId,ParentIndexNumber,ProductionYear,ProviderIds,SeriesId,"
                    "SeriesName,SortName"
                ),
            }

        response = await method("GET", endpoint, params=params)
        if not isinstance(response, Mapping):
            raise JellyfinCatalogResponseError(
                "catalog page endpoint must return a mapping response"
            )

        copied_items = list(
            _coerce_item_sequence(
                response.get("Items", ()),
                source="catalog page Items",
            )
        )
        if request.item_types == (MUSIC_ARTIST_MEDIA_TYPE,):
            for item in copied_items:
                item.setdefault("Type", MUSIC_ARTIST_MEDIA_TYPE)

        total = response.get("TotalRecordCount")
        if total is not None and not isinstance(total, int):
            raise JellyfinCatalogResponseError(
                "catalog page TotalRecordCount must be an integer"
            )

        return CatalogPage(
            request=request,
            items=tuple(copied_items),
            total_record_count=total,
        )

    async def __call__(
        self,
        request: CatalogSearchRequest,
    ) -> tuple[dict[str, Any], ...]:
        """Execute one concrete Jellyfin catalog request."""

        if request.filters.media_type == MUSIC_ARTIST_MEDIA_TYPE:
            return await self._search_music_artists(request)
        return await self._search_library_items(request)

    async def _search_library_items(
        self,
        request: CatalogSearchRequest,
    ) -> tuple[dict[str, Any], ...]:
        method = getattr(self.api, "get_library_items", None)
        if not callable(method):
            raise JellyfinCatalogConfigurationError(
                "catalog API does not provide get_library_items"
            )

        media_type = request.filters.media_type
        items = await method(
            user_id=self.user_id,
            limit=request.limit,
            search_term=request.term,
            item_types=[media_type] if media_type else None,
            is_played=request.filters.is_played,
            is_favorite=request.filters.is_favorite,
            genre=request.filters.genre,
            year=request.filters.year,
            min_rating=request.filters.min_rating,
            season=request.filters.season,
            episode=request.filters.episode,
        )
        return _coerce_item_sequence(items, source="get_library_items")

    async def _search_music_artists(
        self,
        request: CatalogSearchRequest,
    ) -> tuple[dict[str, Any], ...]:
        method = getattr(self.api, "_request", None)
        if not callable(method):
            raise JellyfinCatalogConfigurationError(
                "catalog API does not provide the JellyHA artist request method"
            )

        params = {
            "SortBy": "SortName",
            "SortOrder": "Ascending",
            "Recursive": "true",
            "Fields": "PrimaryImageAspectRatio,ProviderIds",
            "Limit": str(request.limit),
        }
        if request.term:
            # Preserve the parameter spelling used by the installed JellyHA
            # action and Jellyfin's /Artists/AlbumArtists endpoint.
            params["searchTerm"] = request.term

        response = await method(
            "GET",
            "/Artists/AlbumArtists",
            params=params,
        )
        if not isinstance(response, Mapping):
            raise JellyfinCatalogResponseError(
                "artist endpoint must return a mapping response"
            )
        return _coerce_item_sequence(
            response.get("Items", ()),
            source="artist endpoint Items",
        )
