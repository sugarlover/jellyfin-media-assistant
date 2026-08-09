"""Home-Assistant-independent request validation and search execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    ATTR_ALBUM,
    ATTR_ARTIST,
    ATTR_MEDIA_TYPE,
    ATTR_QUERY,
    ATTR_SERIES,
    ATTR_YEAR,
    MAX_CONTEXT_LENGTH,
    MAX_QUERY_LENGTH,
    MAX_YEAR,
    MIN_YEAR,
)
from .matching import MediaSearchContext
from .search import (
    SUPPORTED_CATALOG_MEDIA_TYPES,
    CatalogUnavailableError,
    serialize_search_action_response,
)
from .runtime import JellyfinAssistRuntime


class SearchActionValidationError(ValueError):
    """Raised when a search action request is malformed."""


@dataclass(frozen=True, slots=True)
class SearchActionRequest:
    """Validated user-facing search inputs."""

    query: str
    media_type: str | None = None
    artist: str | None = None
    album: str | None = None
    series: str | None = None
    year: int | None = None

    @property
    def context(self) -> MediaSearchContext:
        """Return matcher context for this request."""

        return MediaSearchContext(
            media_type=self.media_type,
            artist=self.artist,
            album=self.album,
            series=self.series,
            year=self.year,
        )


def _optional_text(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SearchActionValidationError(f"{key} must be text")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_CONTEXT_LENGTH:
        raise SearchActionValidationError(f"{key} is too long")
    return normalized


def parse_search_action_request(data: Mapping[str, Any]) -> SearchActionRequest:
    """Validate one action mapping without depending on Home Assistant."""

    if not isinstance(data, Mapping):
        raise SearchActionValidationError("search action data must be a mapping")

    raw_query = data.get(ATTR_QUERY)
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise SearchActionValidationError("query is required")
    query = raw_query.strip()
    if len(query) > MAX_QUERY_LENGTH:
        raise SearchActionValidationError("query is too long")

    media_type = _optional_text(data, ATTR_MEDIA_TYPE)
    if media_type is not None and media_type not in SUPPORTED_CATALOG_MEDIA_TYPES:
        raise SearchActionValidationError(
            f"unsupported media_type: {media_type}"
        )

    raw_year = data.get(ATTR_YEAR)
    year: int | None = None
    if raw_year not in (None, ""):
        if isinstance(raw_year, bool):
            raise SearchActionValidationError("year must be an integer")
        try:
            year = int(raw_year)
        except (TypeError, ValueError) as err:
            raise SearchActionValidationError("year must be an integer") from err
        if not MIN_YEAR <= year <= MAX_YEAR:
            raise SearchActionValidationError(
                f"year must be between {MIN_YEAR} and {MAX_YEAR}"
            )

    return SearchActionRequest(
        query=query,
        media_type=media_type,
        artist=_optional_text(data, ATTR_ARTIST),
        album=_optional_text(data, ATTR_ALBUM),
        series=_optional_text(data, ATTR_SERIES),
        year=year,
    )


def execute_search_action(
    runtime: JellyfinAssistRuntime,
    request: SearchActionRequest,
) -> dict[str, Any]:
    """Execute and serialize one search against the loaded in-memory catalog."""

    if not isinstance(runtime, JellyfinAssistRuntime):
        raise TypeError("runtime must be JellyfinAssistRuntime")
    if not isinstance(request, SearchActionRequest):
        raise TypeError("request must be SearchActionRequest")

    managed = runtime.catalog_manager.search(
        request.query,
        context=request.context,
    )
    return serialize_search_action_response(managed)


__all__ = [
    "CatalogUnavailableError",
    "SearchActionRequest",
    "SearchActionValidationError",
    "execute_search_action",
    "parse_search_action_request",
]
