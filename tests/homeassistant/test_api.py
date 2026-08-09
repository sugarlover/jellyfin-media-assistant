"""Tests for the asynchronous GET-only Home Assistant Jellyfin client."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from custom_components.jellyfin_assist.api import (
    JellyfinApiClient,
    JellyfinApiError,
    JellyfinAuthenticationError,
    JellyfinInvalidResponseError,
    JELLYHA_GET_ITEM_FIELDS,
    JELLYHA_NEXT_UP_FIELDS,
    normalize_server_url,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, status: int, payload: Any, text: str = "") -> None:
        self.status = status
        self.payload = payload
        self._text = text

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def json(self, **kwargs: Any) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    async def text(self) -> str:
        return self._text


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return next(self.responses)


def test_normalize_server_url() -> None:
    assert normalize_server_url(" http://jellyfin.local:8096/ ") == "http://jellyfin.local:8096"


@pytest.mark.parametrize(
    "value",
    ["jellyfin.local", "ftp://jellyfin.local", "http://user:pass@host", "http://host/?x=1"],
)
def test_normalize_server_url_rejects_unsafe_or_incomplete_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_server_url(value)


def test_client_blocks_non_get_requests() -> None:
    client = JellyfinApiClient(FakeSession([]), "http://host", "secret")

    with pytest.raises(JellyfinApiError, match="blocks non-GET"):
        run(client._request("POST", "/Items"))


def test_validate_connection_returns_stable_non_secret_identity() -> None:
    session = FakeSession(
        [
            FakeResponse(200, {"Id": "server-1", "ServerName": "Living Room", "Version": "10.11.11"}),
            FakeResponse(200, {"Id": "USER-1", "Name": "Example User"}),
        ]
    )
    client = JellyfinApiClient(session, "http://host:8096", "secret")

    info = run(client.async_validate_connection("user-1"))

    assert info.unique_id == "server-1:user-1"
    assert info.server_name == "Living Room"
    assert info.user_name == "Example User"
    assert all(call["headers"]["X-Emby-Token"] == "secret" for call in session.calls)
    assert session.calls[1]["url"].endswith("/Users/user-1")


def test_authentication_failure_is_distinct() -> None:
    client = JellyfinApiClient(
        FakeSession([FakeResponse(401, None)]),
        "http://host",
        "bad",
    )

    with pytest.raises(JellyfinAuthenticationError):
        run(client.async_validate_connection("user"))


def test_invalid_user_response_is_rejected() -> None:
    client = JellyfinApiClient(
        FakeSession(
            [
                FakeResponse(200, {"Id": "server"}),
                FakeResponse(200, {"Id": "different"}),
            ]
        ),
        "http://host",
        "secret",
    )

    with pytest.raises(JellyfinInvalidResponseError, match="different user"):
        run(client.async_validate_connection("expected"))


def test_get_item_uses_pinned_jellyha_field_contract() -> None:
    session = FakeSession([FakeResponse(200, {"Id": "movie-1", "Name": "Movie"})])
    client = JellyfinApiClient(session, "http://host", "secret")

    item = run(client.async_get_item("user 1", "item/1"))

    assert item == {"Id": "movie-1", "Name": "Movie"}
    assert session.calls[0]["url"].endswith("/Users/user%201/Items/item%2F1")
    assert session.calls[0]["params"] == {"Fields": JELLYHA_GET_ITEM_FIELDS}


def test_get_item_rejects_non_mapping_response() -> None:
    client = JellyfinApiClient(
        FakeSession([FakeResponse(200, ["not", "an", "item"])]),
        "http://host",
        "secret",
    )

    with pytest.raises(JellyfinInvalidResponseError, match="item response"):
        run(client.async_get_item("user", "item"))


def test_get_next_up_episode_uses_pinned_jellyha_contract() -> None:
    episode = {"Id": "episode-1", "Name": "Pilot", "Type": "Episode"}
    session = FakeSession([FakeResponse(200, {"Items": [episode]})])
    client = JellyfinApiClient(session, "http://host", "secret")

    result = run(client.async_get_next_up_episode("user-1", "series-1"))

    assert result == episode
    assert session.calls[0]["url"] == "http://host/Shows/NextUp"
    assert session.calls[0]["params"] == {
        "UserId": "user-1",
        "SeriesId": "series-1",
        "Limit": 1,
        "Fields": JELLYHA_NEXT_UP_FIELDS,
    }


def test_get_next_up_episode_returns_none_for_empty_items() -> None:
    client = JellyfinApiClient(
        FakeSession([FakeResponse(200, {"Items": []})]),
        "http://host",
        "secret",
    )

    assert run(client.async_get_next_up_episode("user-1", "series-1")) is None


def test_get_image_url_matches_jellyha_shape() -> None:
    client = JellyfinApiClient(FakeSession([]), "http://host/", "secret")

    assert client.get_image_url("item-1") == (
        "http://host/Items/item-1/Images/Primary"
        "?maxHeight=300&quality=90&api_key=secret"
    )


def test_get_items_builds_native_direct_library_query_contract() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "Items": [{"Id": "episode-1", "Name": "Pilot"}],
                    "TotalRecordCount": 1,
                },
            )
        ]
    )
    client = JellyfinApiClient(session, "http://host", "secret")

    response = run(
        client.async_get_items(
            " user-1 ",
            parent_id="series-1",
            artist_ids="artist-1,artist-2",
            include_item_types="Episode",
            recursive=True,
            season=2,
            episode=3,
            search_term="Pilot",
            sort_by="ParentIndexNumber,IndexNumber",
            sort_order="Ascending",
        )
    )

    assert response == {
        "Items": [{"Id": "episode-1", "Name": "Pilot"}],
        "TotalRecordCount": 1,
    }
    assert session.calls[0]["url"] == "http://host/Items"
    assert session.calls[0]["params"] == {
        "UserId": "user-1",
        "Recursive": "true",
        "ParentId": "series-1",
        "ArtistIds": "artist-1,artist-2",
        "IncludeItemTypes": "Episode",
        "SearchTerm": "Pilot",
        "SortBy": "ParentIndexNumber,IndexNumber",
        "SortOrder": "Ascending",
        "ParentIndexNumber": "2",
        "IndexNumber": "3",
    }


def test_get_items_rejects_invalid_items_payload() -> None:
    client = JellyfinApiClient(
        FakeSession([FakeResponse(200, {"Items": ["not-an-object"]})]),
        "http://host",
        "secret",
    )

    with pytest.raises(JellyfinInvalidResponseError, match="list of objects"):
        run(client.async_get_items("user-1", include_item_types="Audio"))
