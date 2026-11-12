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
    def __init__(self, status: int, payload: Any, text: str = "", headers: Any = None) -> None:
        self.status = status
        self.payload = payload
        self._text = text
        self.headers = headers or {}

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
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return next(self.responses)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "POST", "url": url, **kwargs})
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


def test_whole_series_api_query_preserves_episode_metadata() -> None:
    episodes = [
        {"Id": "s1e1", "ParentIndexNumber": 1, "IndexNumber": 1},
        {"Id": "s2e1", "ParentIndexNumber": 2, "IndexNumber": 1},
    ]
    session = FakeSession([
        FakeResponse(200, {"Items": episodes, "TotalRecordCount": 2})
    ])
    client = JellyfinApiClient(session, "http://host", "secret")

    result = run(client.async_get_items(
        "user-1",
        parent_id="series-1",
        include_item_types="Episode",
        recursive=True,
        sort_by="ParentIndexNumber,IndexNumber",
        sort_order="Ascending",
    ))

    assert result["Items"] == episodes
    assert result["TotalRecordCount"] == 2
    assert session.calls[0]["url"] == "http://host/Items"

    params = session.calls[0]["params"]
    assert params["ParentId"] == "series-1"
    assert params["IncludeItemTypes"] == "Episode"
    assert params["Recursive"] == "true"
    assert params["SortBy"] == "ParentIndexNumber,IndexNumber"
    assert params["SortOrder"] == "Ascending"
    assert "ParentIndexNumber" not in params
    assert "IndexNumber" not in params


def test_post_playing_items_uses_real_progress_route_and_params() -> None:
    session = FakeSession([FakeResponse(204, None)])
    client = JellyfinApiClient(
        session, "http://host", "secret", user_id="user-1", user_token="usertoken"
    )

    result = run(
        client.async_post_playing_items(
            item_id="item/1",
            position_ticks=10510625055,
            is_paused=True,
        )
    )

    # 204 No Content is treated as success and returns None.
    assert result is None
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == (
        "http://host/Users/user-1/PlayingItems/item%2F1/Progress"
    )
    # Query params, not a JSON body: positionTicks + isPaused.
    assert call["params"] == {
        "positionTicks": "10510625055",
        "isPaused": "true",
    }
    assert "json" not in call


def test_post_playing_items_is_paused_false_encodes_false() -> None:
    session = FakeSession([FakeResponse(204, None)])
    client = JellyfinApiClient(
        session, "http://host", "secret", user_id="user-1", user_token="usertoken"
    )

    run(
        client.async_post_playing_items(
            item_id="item-1",
            position_ticks=500000000,
            is_paused=False,
        )
    )

    assert session.calls[0]["params"] == {
        "positionTicks": "500000000",
        "isPaused": "false",
    }


def test_post_playing_items_rejects_wrong_route() -> None:
    client = JellyfinApiClient(
        FakeSession([]), "http://host", "secret", user_id="user-1"
    )

    with pytest.raises(JellyfinApiError, match="blocks non-GET"):
        run(client._request("POST", "/Users/user-1/PlayingItems", params={}))


def test_post_playing_items_rejects_unexpected_options() -> None:
    client = JellyfinApiClient(
        FakeSession([]), "http://host", "secret", user_id="user-1"
    )

    with pytest.raises(JellyfinApiError, match="Unsupported write"):
        run(
            client._request(
                "POST",
                "/Users/user-1/PlayingItems/item-1/Progress",
                params={},
                _item_id="item-1",
                json={"x": 1},
            )
        )


def test_headers_prefer_user_token_over_api_key() -> None:
    client = JellyfinApiClient(
        FakeSession([]), "http://host", "secret", user_token="usertoken"
    )

    headers = client._headers
    assert headers["X-Emby-Token"] == "usertoken"
    assert 'Token="usertoken"' in headers["Authorization"]


def test_headers_fall_back_to_api_key_without_token() -> None:
    client = JellyfinApiClient(FakeSession([]), "http://host", "secret")

    headers = client._headers
    assert headers["X-Emby-Token"] == "secret"
    assert 'Token="secret"' in headers["Authorization"]


def test_post_playing_items_refreshes_token_once_on_401() -> None:
    refresh_calls = {"count": 0}

    async def refresh() -> None:
        refresh_calls["count"] += 1
        client.user_token = "newtoken"

    session = FakeSession(
        [
            FakeResponse(401, None),
            FakeResponse(204, None),
        ]
    )
    client = JellyfinApiClient(
        session, "http://host", "secret", user_id="user-1", user_token="stale"
    )

    run(
        client.async_post_playing_items(
            item_id="item-1",
            position_ticks=500,
            is_paused=True,
            _async_auth_refresh=refresh,
        )
    )

    # Exactly one refresh attempt, then a successful retry (204).
    assert refresh_calls["count"] == 1
    assert len(session.calls) == 2
    assert session.calls[0]["headers"]["X-Emby-Token"] == "stale"
    assert session.calls[1]["headers"]["X-Emby-Token"] == "newtoken"


def test_post_playing_items_raises_auth_error_when_401_without_refresh() -> None:
    session = FakeSession([FakeResponse(401, None)])
    client = JellyfinApiClient(
        session, "http://host", "secret", user_id="user-1", user_token="stale"
    )

    with pytest.raises(JellyfinAuthenticationError):
        run(
            client.async_post_playing_items(
                item_id="item-1",
                position_ticks=500,
                is_paused=True,
            )
        )


def test_post_playing_items_401_only_retried_once_not_loop() -> None:
    refresh_calls = {"count": 0}

    async def refresh() -> None:
        refresh_calls["count"] += 1
        client.user_token = "still-401"

    session = FakeSession(
        [
            FakeResponse(401, None),
            FakeResponse(401, None),
        ]
    )
    client = JellyfinApiClient(
        session, "http://host", "secret", user_id="user-1", user_token="stale"
    )

    with pytest.raises(JellyfinAuthenticationError):
        run(
            client.async_post_playing_items(
                item_id="item-1",
                position_ticks=500,
                is_paused=True,
                _async_auth_refresh=refresh,
            )
        )

    # One refresh then one final 401 — no infinite loop.
    assert refresh_calls["count"] == 1
    assert len(session.calls) == 2


def test_get_user_access_token_reads_access_token_header() -> None:
    session = FakeSession(
        [
            FakeResponse(200, None, headers={"Access-Token": "fresh-token"})
        ]
    )
    client = JellyfinApiClient(session, "http://host", "secret")

    token = run(client.async_get_user_access_token("user-1", "p4ss"))

    assert token == "fresh-token"
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://host/Users/user-1/Authenticate"
    assert call["json"] == {"Pw": "p4ss"}


def test_get_user_access_token_rejects_missing_token() -> None:
    session = FakeSession([FakeResponse(200, None, headers={})])
    client = JellyfinApiClient(session, "http://host", "secret")

    with pytest.raises(JellyfinInvalidResponseError, match="access token"):
        run(client.async_get_user_access_token("user-1", "p4ss"))


def test_get_user_access_token_rejects_bad_password() -> None:
    session = FakeSession([FakeResponse(401, None)])
    client = JellyfinApiClient(session, "http://host", "secret")

    with pytest.raises(JellyfinAuthenticationError, match="password"):
        run(client.async_get_user_access_token("user-1", "nope"))


def test_post_blocks_route_without_user_prefix() -> None:
    # A POST to a route that lacks the /Users/{uid}/PlayingItems/{id}/Progress
    # prefix is blocked even when _item_id is supplied.
    client = JellyfinApiClient(FakeSession([]), "http://host", "secret", user_id="u1")

    with pytest.raises(JellyfinApiError, match="blocks non-GET"):
        run(
            client._request(
                "POST",
                "/PlayingItems/item-1/Progress",
                params={},
                _item_id="item-1",
            )
        )
