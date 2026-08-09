"""Async, GET-only Jellyfin API client for Home Assistant runtime use."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout

from .configuration import normalize_server_url
from .const import DEFAULT_REQUEST_TIMEOUT_SECONDS, NAME, VERSION




# Kept byte-for-byte equivalent to the field set used by JellyHA 1.2.0 at
# upstream commit 6b8b2f679f922ea3a0d9c3c4b9827ee7053308f9. See
# THIRD_PARTY_NOTICES.md and docs/provenance/jellyha.json.
JELLYHA_GET_ITEM_FIELDS = (
    "Chapters,DateCreated,Genres,MediaSources,MediaStreams,Overview,ParentId,"
    "Path,People,ProviderIds,PrimaryImageAspectRatio,RemoteTrailers,SortName,"
    "Studios,Taglines,TrailerUrls,UserData,SeasonUserData,OfficialRating,"
    "CommunityRating,CumulativeRunTimeTicks,RunTimeTicks,ProductionYear,"
    "PremiereDate,ExternalUrls"
)

JELLYHA_NEXT_UP_FIELDS = (
    "MediaSources,MediaStreams,Overview,RunTimeTicks,OfficialRating,CommunityRating"
)


class JellyfinApiError(RuntimeError):
    """Base class for Jellyfin API failures."""


class JellyfinAuthenticationError(JellyfinApiError):
    """Raised when Jellyfin rejects the configured credentials."""


class JellyfinConnectionError(JellyfinApiError):
    """Raised when Jellyfin cannot be reached."""


class JellyfinInvalidResponseError(JellyfinApiError):
    """Raised when Jellyfin returns an unexpected response."""


@dataclass(frozen=True, slots=True)
class JellyfinConnectionInfo:
    """Validated, non-secret Jellyfin server and user details."""

    server_id: str
    server_name: str
    server_version: str | None
    user_id: str
    user_name: str | None

    @property
    def unique_id(self) -> str:
        """Return the stable config-entry identifier."""

        return f"{self.server_id.casefold()}:{self.user_id.casefold()}"




@dataclass(slots=True)
class JellyfinApiClient:
    """Minimal Home Assistant client restricted to read-only GET requests."""

    session: ClientSession
    server_url: str
    api_key: str = field(repr=False)
    verify_ssl: bool = True
    timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        self.server_url = normalize_server_url(self.server_url)
        self.api_key = self.api_key.strip()
        if not self.api_key:
            raise ValueError("Jellyfin API key is required")
        if not isinstance(self.verify_ssl, bool):
            raise ValueError("verify_ssl must be a boolean")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @property
    def _headers(self) -> dict[str, str]:
        """Return Jellyfin headers without exposing the token in diagnostics."""

        return {
            "Accept": "application/json",
            "X-Emby-Token": self.api_key,
            "Authorization": (
                f'MediaBrowser Client="{NAME}", '
                'Device="Home Assistant", '
                'DeviceId="jellyfin-assist", '
                f'Version="{VERSION}", '
                f'Token="{self.api_key}"'
            ),
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> Any:
        """Execute one JellyHA-compatible request, rejecting every non-GET method."""

        if method.upper() != "GET":
            raise JellyfinApiError("Jellyfin Media Assistant blocks non-GET requests")
        unexpected = set(kwargs) - {"params"}
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise JellyfinApiError(f"Unsupported read-only request options: {names}")

        url = f"{self.server_url}/{endpoint.lstrip('/')}"
        try:
            async with self.session.get(
                url,
                params=kwargs.get("params"),
                headers=self._headers,
                ssl=self.verify_ssl,
                timeout=ClientTimeout(total=self.timeout_seconds),
            ) as response:
                if response.status in {401, 403}:
                    raise JellyfinAuthenticationError(
                        "Jellyfin rejected the API key or user access"
                    )
                if response.status >= 500:
                    raise JellyfinConnectionError(
                        f"Jellyfin returned temporary HTTP {response.status}"
                    )
                if response.status >= 400:
                    body = (await response.text())[:300]
                    raise JellyfinInvalidResponseError(
                        f"Jellyfin returned HTTP {response.status}: {body}"
                    )
                if response.status == 204:
                    return None
                try:
                    return await response.json(content_type=None)
                except (ClientResponseError, json.JSONDecodeError, ValueError) as err:
                    raise JellyfinInvalidResponseError(
                        "Jellyfin returned invalid JSON"
                    ) from err
        except JellyfinApiError:
            raise
        except TimeoutError as err:
            raise JellyfinConnectionError("Jellyfin request timed out") from err
        except ClientError as err:
            raise JellyfinConnectionError("Could not reach Jellyfin") from err

    async def async_get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        """Return one Jellyfin item using the JellyHA get_item field contract."""

        normalized_user_id = user_id.strip()
        normalized_item_id = item_id.strip()
        if not normalized_user_id:
            raise ValueError("Jellyfin user ID is required")
        if not normalized_item_id:
            raise ValueError("Jellyfin item ID is required")

        item = await self._request(
            "GET",
            f"/Users/{quote(normalized_user_id, safe='')}/Items/{quote(normalized_item_id, safe='')}",
            params={"Fields": JELLYHA_GET_ITEM_FIELDS},
        )
        if not isinstance(item, Mapping):
            raise JellyfinInvalidResponseError("Jellyfin item response was not an object")
        return dict(item)

    async def async_get_next_up_episode(
        self,
        user_id: str,
        series_id: str,
    ) -> dict[str, Any] | None:
        """Return the first JellyHA-compatible Next Up episode for one series."""

        normalized_user_id = user_id.strip()
        normalized_series_id = series_id.strip()
        if not normalized_user_id:
            raise ValueError("Jellyfin user ID is required")
        if not normalized_series_id:
            raise ValueError("Jellyfin series ID is required")

        result = await self._request(
            "GET",
            "/Shows/NextUp",
            params={
                "UserId": normalized_user_id,
                "SeriesId": normalized_series_id,
                "Limit": 1,
                "Fields": JELLYHA_NEXT_UP_FIELDS,
            },
        )
        if not isinstance(result, Mapping):
            raise JellyfinInvalidResponseError(
                "Jellyfin Next Up response was not an object"
            )
        items = result.get("Items", [])
        if not isinstance(items, list):
            raise JellyfinInvalidResponseError(
                "Jellyfin Next Up items response was not a list"
            )
        if not items:
            return None
        first = items[0]
        if not isinstance(first, Mapping):
            raise JellyfinInvalidResponseError(
                "Jellyfin Next Up episode was not an object"
            )
        return dict(first)

    async def async_get_items(
        self,
        user_id: str,
        *,
        parent_id: str | None = None,
        artist_ids: str | None = None,
        include_item_types: str | None = None,
        recursive: bool = True,
        season: int | None = None,
        episode: int | None = None,
        search_term: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> dict[str, Any]:
        """Return one read-only Jellyfin /Items query as a copied mapping."""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("Jellyfin user ID is required")

        params: dict[str, str] = {
            "UserId": normalized_user_id,
            "Recursive": "true" if recursive else "false",
        }
        optional_text = {
            "ParentId": parent_id,
            "ArtistIds": artist_ids,
            "IncludeItemTypes": include_item_types,
            "SearchTerm": search_term,
            "SortBy": sort_by,
            "SortOrder": sort_order,
        }
        for key, value in optional_text.items():
            if value is not None and str(value).strip():
                params[key] = str(value).strip()
        if season is not None:
            if season < 0:
                raise ValueError("Season number cannot be negative")
            params["ParentIndexNumber"] = str(season)
        if episode is not None:
            if episode < 0:
                raise ValueError("Episode number cannot be negative")
            params["IndexNumber"] = str(episode)

        result = await self._request("GET", "/Items", params=params)
        if not isinstance(result, Mapping):
            raise JellyfinInvalidResponseError(
                "Jellyfin items response was not an object"
            )
        items = result.get("Items", [])
        if not isinstance(items, list) or any(
            not isinstance(item, Mapping) for item in items
        ):
            raise JellyfinInvalidResponseError(
                "Jellyfin items response did not contain a list of objects"
            )
        copied = dict(result)
        copied["Items"] = [dict(item) for item in items]
        return copied

    def get_image_url(
        self,
        item_id: str,
        image_type: str = "Primary",
        max_height: int = 300,
        quality: int = 90,
    ) -> str:
        """Build the JellyHA-compatible authenticated Jellyfin image URL."""

        return (
            f"{self.server_url}/Items/{item_id}/Images/{image_type}"
            f"?maxHeight={max_height}&quality={quality}&api_key={self.api_key}"
        )

    async def async_validate_connection(self, user_id: str) -> JellyfinConnectionInfo:
        """Validate server reachability, credentials, and the selected user."""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("Jellyfin user ID is required")

        server = await self._request("GET", "/System/Info/Public")
        if not isinstance(server, Mapping):
            raise JellyfinInvalidResponseError(
                "Jellyfin public server information was not an object"
            )

        user = await self._request(
            "GET",
            f"/Users/{quote(normalized_user_id, safe='')}",
        )
        if not isinstance(user, Mapping):
            raise JellyfinInvalidResponseError("Jellyfin user response was not an object")

        returned_user_id = str(user.get("Id") or "").strip()
        if not returned_user_id or returned_user_id.casefold() != normalized_user_id.casefold():
            raise JellyfinInvalidResponseError(
                "Jellyfin returned a different user than requested"
            )

        server_id = str(server.get("Id") or "").strip()
        if not server_id:
            # Older Jellyfin public responses may omit Id. The normalized URL is
            # still deterministic and prevents duplicate entries for one server.
            server_id = self.server_url.casefold()

        return JellyfinConnectionInfo(
            server_id=server_id,
            server_name=str(server.get("ServerName") or "Jellyfin").strip() or "Jellyfin",
            server_version=(
                str(server.get("Version")).strip() if server.get("Version") else None
            ),
            user_id=returned_user_id,
            user_name=(str(user.get("Name")).strip() if user.get("Name") else None),
        )


__all__ = [
    "JellyfinApiClient",
    "JellyfinApiError",
    "JellyfinAuthenticationError",
    "JellyfinConnectionError",
    "JellyfinConnectionInfo",
    "JellyfinInvalidResponseError",
    "JELLYHA_GET_ITEM_FIELDS",
    "JELLYHA_NEXT_UP_FIELDS",
    "normalize_server_url",
]
