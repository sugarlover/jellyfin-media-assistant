"""Async Jellyfin API client for Home Assistant runtime use."""

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
    "MediaSources,MediaStreams,Overview,RunTimeTicks,OfficialRating,CommunityRating,"
    "UserData,SeasonUserData"
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
    user_id: str = ""
    user_token: str = field(repr=False, default="")

    def __post_init__(self) -> None:
        self.server_url = normalize_server_url(self.server_url)
        self.api_key = self.api_key.strip()
        if not self.api_key:
            raise ValueError("Jellyfin API key is required")
        if not isinstance(self.verify_ssl, bool):
            raise ValueError("verify_ssl must be a boolean")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.user_token = self.user_token.strip()

    def __repr__(self) -> str:
        """Redacted representation: the API key and user token are never shown."""

        return (
            f"{type(self).__name__}("
            f"server_url={self.server_url!r}, "
            f"user_id={self.user_id!r}, "
            f"verify_ssl={self.verify_ssl!r}, "
            f"api_key=[REDACTED], "
            f"user_token=[REDACTED])"
        )

    __str__ = __repr__

    @property
    def _headers(self) -> dict[str, str]:
        """Return Jellyfin headers without exposing the token in diagnostics.

        A user-bound access token (minted via ``POST /Users/AuthenticateByName``)
        is sent in preference to the bare server API key so the session resolves
        to a real user. Without a token the API key is used (read-only reads
        still work; position persistence would not).
        """

        token = self.user_token.strip() or self.api_key
        return {
            "Accept": "application/json",
            "X-Emby-Token": token,
            "Authorization": (
                f'MediaBrowser Client="{NAME}", '
                'Device="Home Assistant", '
                'DeviceId="jellyfin-assist", '
                f'Version="{VERSION}", '
                f'Token="{token}"'
            ),
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> Any:
        """Execute one JellyHA-compatible request.

        All methods are restricted to GET except the single allowed
        write endpoint: POST /Users/{userId}/PlayingItems/{itemId}/Progress.
        """

        normalized_method = method.upper()
        if normalized_method == "POST":
            # The only permitted write: user-scoped playback progress.
            expected = (
                f"/Users/{quote(self.user_id, safe='')}"
                f"/PlayingItems/{quote(kwargs.get('_item_id', ''), safe='')}"
                "/Progress"
            )
            endpoint_path = endpoint.lstrip("/")
            if not endpoint_path.startswith(expected.lstrip("/")):
                raise JellyfinApiError(
                    "Jellyfin Media Assistant blocks non-GET requests"
                )
            unexpected = set(kwargs) - {"params", "_item_id", "_async_auth_refresh"}
            if unexpected:
                names = ", ".join(sorted(unexpected))
                raise JellyfinApiError(
                    f"Unsupported write request options: {names}"
                )
            url = f"{self.server_url}/{endpoint_path}"
            params = kwargs.get("params") or {}
            _async_auth_refresh = kwargs.get("_async_auth_refresh")
            refresh_attempts = 0
            while True:
                try:
                    async with self.session.post(
                        url,
                        params=params,
                        headers=self._headers,
                        ssl=self.verify_ssl,
                        timeout=ClientTimeout(total=self.timeout_seconds),
                    ) as response:
                        if response.status == 401 and (
                            _async_auth_refresh is not None and refresh_attempts == 0
                        ):
                            # The stored user token expired; mint a fresh one and
                            # retry once before surfacing an auth failure.
                            refresh_attempts += 1
                            await _async_auth_refresh()
                            continue
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
                        except (
                            ClientResponseError,
                            json.JSONDecodeError,
                            ValueError,
                        ) as err:
                            raise JellyfinInvalidResponseError(
                                "Jellyfin returned invalid JSON"
                            ) from err
                except JellyfinApiError:
                    raise
                except TimeoutError as err:
                    raise JellyfinConnectionError(
                        "Jellyfin request timed out"
                    ) from err
                except ClientError as err:
                    raise JellyfinConnectionError(
                        "Could not reach Jellyfin"
                    ) from err

        if normalized_method != "GET":
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

    async def async_post_playing_items(
        self,
        *,
        item_id: str,
        position_ticks: int,
        is_paused: bool,
        device_id: str = "jellyfin-assist",
        _async_auth_refresh: Any = None,
    ) -> None:
        """Report playback position via the real progress route.

        POST /Users/{userId}/PlayingItems/{itemId}/Progress?positionTicks=…&isPaused=…
        (response is 204 No Content).

        :param _async_auth_refresh: optional zero-arg async callable that mints a
            fresh ``user_token`` and updates :attr:`self`; invoked once on a 401.
        """

        normalized_item_id = item_id.strip()
        if not normalized_item_id:
            raise ValueError("Jellyfin item ID is required")
        if position_ticks < 0:
            raise ValueError("PositionTicks cannot be negative")

        await self._request(
            "POST",
            f"/Users/{quote(self.user_id, safe='')}"
            f"/PlayingItems/{quote(normalized_item_id, safe='')}/Progress",
            params={
                "positionTicks": str(position_ticks),
                "isPaused": "true" if is_paused else "false",
            },
            _item_id=normalized_item_id,
            _async_auth_refresh=_async_auth_refresh,
        )

    async def async_get_user_access_token(
        self,
        user_id: str,
        pwp: str,
        *,
        user_name: str | None = None,
    ) -> str:
        """Mint a user-bound device/access token for this user.

        POST /Users/AuthenticateByName with ``{"UserName": <user name>, "Pw":
        <password>}``. Jellyfin answers with the per-user access token and the
        resolved user in the response **JSON body**
        (``{"AccessToken": ..., "User": {"Id": ...}}``). The returned user id
        is verified (case-insensitive) against the configured user id.
        Unlike the bare server API key, this token binds a real user, so the
        playback-progress session resolves to a user and ``SaveUserData``
        runs server-side.
        """

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("Jellyfin user ID is required")
        if not pwp.strip():
            raise ValueError("Jellyfin user password is required")
        normalized_user_name = (
            str(user_name).strip() if user_name is not None else ""
        )
        if not normalized_user_name:
            raise JellyfinInvalidResponseError(
                "Jellyfin user name is required to authenticate; "
                "re-run the connection validation"
            )

        # Authenticate is a distinct POST that is NOT the playing-items route, so
        # it cannot go through ``_request`` (whose guard allows only that route).
        # It is authenticated with the server API key; the returned token is what
        # later requests send.
        url = f"{self.server_url}/Users/AuthenticateByName"
        headers = {
            "Accept": "application/json",
            "Authorization": (
                f'MediaBrowser Client="{NAME}", '
                'Device="Home Assistant", '
                'DeviceId="jellyfin-assist", '
                f'Version="{VERSION}", '
                f'Token="{self.api_key}"'
            ),
        }
        try:
            async with self.session.post(
                url,
                json={"UserName": normalized_user_name, "Pw": pwp},
                headers=headers,
                ssl=self.verify_ssl,
                timeout=ClientTimeout(total=self.timeout_seconds),
            ) as response:
                if response.status in {401, 403}:
                    raise JellyfinAuthenticationError(
                        "Jellyfin rejected the user password"
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
                try:
                    payload = await response.json(content_type=None)
                except (
                    ClientResponseError,
                    json.JSONDecodeError,
                    ValueError,
                ) as err:
                    raise JellyfinInvalidResponseError(
                        "Jellyfin returned invalid JSON"
                    ) from err
                if not isinstance(payload, Mapping):
                    raise JellyfinInvalidResponseError(
                        "Jellyfin authentication response was not an object"
                    )
                access_token = str(
                    payload.get("AccessToken") or ""
                ).strip()
                if not access_token:
                    raise JellyfinInvalidResponseError(
                        "Jellyfin did not return an access token"
                    )
                returned_user_id = str(
                    (payload.get("User") or {}).get("Id") or ""
                ).strip()
                if (
                    not returned_user_id
                    or returned_user_id.casefold() != normalized_user_id.casefold()
                ):
                    raise JellyfinInvalidResponseError(
                        "Jellyfin returned a different user than requested"
                    )
                return access_token
        except JellyfinApiError:
            raise
        except TimeoutError as err:
            raise JellyfinConnectionError("Jellyfin request timed out") from err
        except ClientError as err:
            raise JellyfinConnectionError("Could not reach Jellyfin") from err

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
