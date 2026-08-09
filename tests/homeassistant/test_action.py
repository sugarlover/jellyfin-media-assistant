"""Tests for pure search-action validation and execution."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from custom_components.jellyfin_assist.action import (
    SearchActionValidationError,
    execute_search_action,
    parse_search_action_request,
)
from custom_components.jellyfin_assist.api import JellyfinApiClient
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime
from custom_components.jellyfin_assist.search import (
    CatalogLoadStopReason,
    CatalogManager,
    CatalogSnapshot,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def runtime(tmp_path: Path) -> JellyfinAssistRuntime:
    snapshot = CatalogSnapshot(
        requested_types=("Movie",),
        items=({"Id": "bubba", "Name": "Bubba Ho-tep", "Type": "Movie"},),
        pages=(),
        raw_item_count=1,
        duplicate_item_count=0,
        missing_id_count=0,
        server_overflow_item_count=0,
        stop_reason=CatalogLoadStopReason.COMPLETE,
    )

    async def loader() -> CatalogSnapshot:
        return snapshot

    manager = CatalogManager(
        snapshot_loader=loader,
        requested_types=["Movie"],
        cache_identity="server:user",
        cache_store=None,
    )
    run(manager.async_refresh())
    return JellyfinAssistRuntime(
        client=object(),  # type: ignore[arg-type]
        catalog_manager=manager,
        connection_info=None,
    )


def test_request_normalizes_context_and_year() -> None:
    request = parse_search_action_request(
        {
            "query": "  Bubba ho tep ",
            "media_type": "Movie",
            "artist": " ",
            "year": "2002",
        }
    )

    assert request.query == "Bubba ho tep"
    assert request.media_type == "Movie"
    assert request.artist is None
    assert request.year == 2002


def test_request_rejects_unknown_media_type() -> None:
    with pytest.raises(SearchActionValidationError, match="unsupported"):
        parse_search_action_request({"query": "Title", "media_type": "Book"})


def test_execute_action_returns_frozen_response_contract(tmp_path: Path) -> None:
    response = execute_search_action(
        runtime(tmp_path),
        parse_search_action_request({"query": "Bubba ho tep", "media_type": "Movie"}),
    )

    assert response["decision"]["status"] == "matched"
    assert response["items"][0]["id"] == "bubba"
    assert response["match"]["method"] == "punctuation_spacing"
