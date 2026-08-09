"""Small GET-only Jellyfin HTTP client for live catalog validation.

This module is intentionally separate from the future Home Assistant runtime
client.  It uses only Python's standard library so a developer can test the
pure search pipeline directly against a real Jellyfin catalog without Home
Assistant or third-party packages.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


class JellyfinLiveConfigurationError(ValueError):
    """Raised when live-test connection settings are invalid."""


class JellyfinReadOnlyError(RuntimeError):
    """Raised when a read-only Jellyfin request fails."""


@dataclass(frozen=True, slots=True)
class JellyfinReadOnlyApi:
    """Minimal asynchronous Jellyfin API surface restricted to HTTP GET."""

    server_url: str
    api_key: str = field(repr=False)
    verify_ssl: bool = True
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        server_url = self.server_url.strip().rstrip("/")
        api_key = self.api_key.strip()
        parsed = urlparse(server_url)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise JellyfinLiveConfigurationError(
                "JELLYFIN_URL must be a complete http:// or https:// URL"
            )
        if not api_key:
            raise JellyfinLiveConfigurationError("JELLYFIN_API_KEY is required")
        if self.timeout_seconds <= 0:
            raise JellyfinLiveConfigurationError("timeout_seconds must be positive")

        object.__setattr__(self, "server_url", server_url)
        object.__setattr__(self, "api_key", api_key)

    @property
    def _headers(self) -> dict[str, str]:
        """Return Jellyfin authentication headers without exposing them."""

        return {
            "Accept": "application/json",
            "X-Emby-Token": self.api_key,
            "Authorization": (
                'MediaBrowser Client="Jellyfin Media Assistant Live Test", '
                'Device="Developer Workstation", '
                'DeviceId="jellyfin-assist-live-test", '
                'Version="0.1.0", '
                f'Token="{self.api_key}"'
            ),
        }

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self.verify_ssl:
            return None
        return ssl._create_unverified_context()  # noqa: SLF001 - explicit local-test opt-out

    def _sync_get(
        self,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Execute one synchronous GET request for ``asyncio.to_thread``."""

        url = urljoin(self.server_url + "/", endpoint.lstrip("/"))
        if params:
            encoded = urlencode(
                [(key, value) for key, value in params.items() if value is not None],
                doseq=True,
            )
            if encoded:
                url = f"{url}?{encoded}"

        request = Request(url, headers=self._headers, method="GET")
        try:
            with urlopen(  # noqa: S310 - URL is explicit developer configuration
                request,
                timeout=self.timeout_seconds,
                context=self._ssl_context(),
            ) as response:
                payload = response.read()
        except HTTPError as err:
            try:
                body = err.read().decode("utf-8", errors="replace")
            except Exception:  # pragma: no cover - defensive response handling
                body = "<unreadable>"
            raise JellyfinReadOnlyError(
                f"Jellyfin returned HTTP {err.code}: {body[:300]}"
            ) from err
        except URLError as err:
            raise JellyfinReadOnlyError(f"Could not reach Jellyfin: {err.reason}") from err
        except TimeoutError as err:
            raise JellyfinReadOnlyError("Jellyfin request timed out") from err

        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as err:
            raise JellyfinReadOnlyError("Jellyfin returned invalid JSON") from err

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> Any:
        """Provide the JellyHA-compatible request seam, restricted to GET."""

        if method.upper() != "GET":
            raise JellyfinReadOnlyError(
                "Live validation client blocks every non-GET request"
            )
        unexpected = set(kwargs) - {"params"}
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise JellyfinReadOnlyError(f"Unsupported read-only request options: {names}")
        return await asyncio.to_thread(
            self._sync_get,
            endpoint,
            params=kwargs.get("params"),
        )

    async def validate_connection(self) -> dict[str, Any]:
        """Return public server information using a read-only endpoint."""

        result = await self._request("GET", "/System/Info/Public")
        if not isinstance(result, Mapping):
            raise JellyfinReadOnlyError("Jellyfin server information was not an object")
        return dict(result)

    async def get_library_items(
        self,
        user_id: str,
        limit: int = 0,
        item_types: list[str] | None = None,
        library_ids: list[str] | None = None,
        search_term: str | None = None,
        is_played: bool | None = None,
        is_favorite: bool | None = None,
        genre: str | None = None,
        year: int | None = None,
        min_rating: float | None = None,
        season: int | None = None,
        episode: int | None = None,
    ) -> list[dict[str, Any]]:
        """Mirror JellyHA's read-only library search arguments."""

        if library_ids:
            raise JellyfinReadOnlyError(
                "The live validation harness does not use library_ids"
            )

        params: dict[str, Any] = {
            "SortBy": "SortName",
            "SortOrder": "Ascending",
            "Recursive": "true",
            "Fields": (
                "Album,AlbumArtist,Artists,Genres,ParentId,ProductionYear,ProviderIds,"
                "RunTimeTicks,SeriesName,UserData"
            ),
        }
        if item_types:
            params["IncludeItemTypes"] = ",".join(item_types)
        if limit > 0:
            params["Limit"] = str(limit)
        if search_term:
            params["SearchTerm"] = search_term
        if is_played is not None:
            params["IsPlayed"] = str(is_played).lower()
        if is_favorite is not None:
            params["IsFavorite"] = str(is_favorite).lower()
        if genre:
            params["Genres"] = genre
        if year:
            params["Years"] = str(year)
        if min_rating is not None:
            params["MinCommunityRating"] = str(min_rating)
        if season is not None:
            params["ParentIndexNumber"] = str(season)
        if episode is not None:
            params["IndexNumber"] = str(episode)

        result = await self._request(
            "GET",
            f"/Users/{user_id}/Items",
            params=params,
        )
        if not isinstance(result, Mapping):
            raise JellyfinReadOnlyError("Jellyfin item search was not an object")
        items = result.get("Items", [])
        if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
            raise JellyfinReadOnlyError("Jellyfin item search returned invalid Items")
        return [dict(item) for item in items]
