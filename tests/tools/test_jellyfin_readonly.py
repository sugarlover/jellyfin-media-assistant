from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tools.jellyfin_readonly import (
    JellyfinLiveConfigurationError,
    JellyfinReadOnlyApi,
    JellyfinReadOnlyError,
)


def test_requires_complete_url_and_api_key() -> None:
    with pytest.raises(JellyfinLiveConfigurationError):
        JellyfinReadOnlyApi("jellyfin.local:8096", "key")
    with pytest.raises(JellyfinLiveConfigurationError):
        JellyfinReadOnlyApi("http://jellyfin.local:8096", "")


def test_request_blocks_non_get_before_network_access() -> None:
    api = JellyfinReadOnlyApi("http://jellyfin.local:8096", "secret")

    with pytest.raises(JellyfinReadOnlyError, match="blocks every non-GET"):
        asyncio.run(api._request("POST", "/Items/123"))


def test_headers_include_token_but_object_repr_hides_it() -> None:
    api = JellyfinReadOnlyApi("http://jellyfin.local:8096", "secret-token")

    assert api._headers["X-Emby-Token"] == "secret-token"
    assert "secret-token" not in repr(api)


def test_library_items_translate_search_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    api = JellyfinReadOnlyApi("http://jellyfin.local:8096", "secret")
    captured: dict[str, Any] = {}

    async def fake_request(
        self: JellyfinReadOnlyApi,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        captured.update(method=method, endpoint=endpoint, kwargs=kwargs)
        return {"Items": [{"Id": "1", "Name": "3AM", "Type": "Audio"}]}

    monkeypatch.setattr(JellyfinReadOnlyApi, "_request", fake_request)
    items = asyncio.run(
        api.get_library_items(
            user_id="user-1",
            limit=20,
            item_types=["Audio"],
            search_term="three am",
            year=1997,
        )
    )

    assert items[0]["Name"] == "3AM"
    assert captured["method"] == "GET"
    assert captured["endpoint"] == "/Users/user-1/Items"
    params = captured["kwargs"]["params"]
    assert params["SearchTerm"] == "three am"
    assert params["IncludeItemTypes"] == "Audio"
    assert params["Limit"] == "20"
    assert params["Years"] == "1997"
