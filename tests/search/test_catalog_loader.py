"""Tests for read-only paginated Jellyfin catalog loading."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from custom_components.jellyfin_assist.matching import MatchDecisionStatus, MediaSearchContext
from custom_components.jellyfin_assist.search import (
    DEFAULT_CATALOG_MEDIA_TYPES,
    MUSIC_ARTIST_MEDIA_TYPE,
    CatalogIndex,
    CatalogLoadStopReason,
    CatalogPage,
    CatalogPageRequest,
    CatalogPageResponseError,
    catalog_request_groups,
    load_catalog_snapshot,
    normalize_catalog_media_types,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def page(
    request: CatalogPageRequest,
    items: list[Mapping[str, Any]],
    *,
    total: int | None,
) -> CatalogPage:
    return CatalogPage(
        request=request,
        items=tuple(dict(item) for item in items),
        total_record_count=total,
    )


def test_default_media_types_are_stable_and_artist_is_separate() -> None:
    assert normalize_catalog_media_types(None) == DEFAULT_CATALOG_MEDIA_TYPES
    assert catalog_request_groups(None) == (
        ("Movie", "Series", "Episode", "Audio", "MusicAlbum"),
        (MUSIC_ARTIST_MEDIA_TYPE,),
    )


def test_requested_types_are_deduplicated_in_first_seen_order() -> None:
    assert normalize_catalog_media_types(["Movie", "Audio", "Movie"]) == (
        "Movie",
        "Audio",
    )


def test_unsupported_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        normalize_catalog_media_types(["Playlist"])


def test_loader_paginates_regular_items_then_artists() -> None:
    requests: list[CatalogPageRequest] = []

    async def fetch(request: CatalogPageRequest) -> CatalogPage:
        requests.append(request)
        if request.item_types == ("Movie", "Audio"):
            if request.start_index == 0:
                return page(
                    request,
                    [
                        {"Id": "movie", "Name": "Matrix", "Type": "Movie"},
                        {"Id": "song", "Name": "One", "Type": "Audio"},
                    ],
                    total=3,
                )
            return page(
                request,
                [{"Id": "song-2", "Name": "Two", "Type": "Audio"}],
                total=3,
            )
        return page(
            request,
            [{"Id": "artist", "Name": "Metallica", "Type": "MusicArtist"}],
            total=1,
        )

    snapshot = run(
        load_catalog_snapshot(
            fetch,
            item_types=["Movie", "Audio", "MusicArtist"],
            page_size=2,
        )
    )

    assert [(request.item_types, request.start_index, request.limit) for request in requests] == [
        (("Movie", "Audio"), 0, 2),
        (("Movie", "Audio"), 2, 2),
        (("MusicArtist",), 0, 2),
    ]
    assert [item["Id"] for item in snapshot.items] == [
        "movie",
        "song",
        "song-2",
        "artist",
    ]
    assert snapshot.stop_reason is CatalogLoadStopReason.COMPLETE
    assert snapshot.truncated is False


def test_loader_deduplicates_ids_across_pages() -> None:
    async def fetch(request: CatalogPageRequest) -> CatalogPage:
        if request.start_index == 0:
            return page(
                request,
                [
                    {"Id": "one", "Name": "One", "Type": "Movie"},
                    {"Id": "two", "Name": "Two", "Type": "Movie"},
                ],
                total=4,
            )
        return page(
            request,
            [
                {"Id": "two", "Name": "Duplicate", "Type": "Movie"},
                {"Id": "three", "Name": "Three", "Type": "Movie"},
            ],
            total=4,
        )

    snapshot = run(
        load_catalog_snapshot(fetch, item_types=["Movie"], page_size=2)
    )

    assert [item["Id"] for item in snapshot.items] == ["one", "two", "three"]
    assert snapshot.raw_item_count == 4
    assert snapshot.duplicate_item_count == 1


def test_loader_preserves_missing_id_items_for_index_diagnostics() -> None:
    async def fetch(request: CatalogPageRequest) -> CatalogPage:
        return page(request, [{"Name": "Missing ID", "Type": "Movie"}], total=1)

    snapshot = run(load_catalog_snapshot(fetch, item_types=["Movie"]))
    index = CatalogIndex.build(snapshot.items)

    assert snapshot.missing_id_count == 1
    assert len(snapshot.items) == 1
    assert len(index.records) == 0
    assert len(index.issues) == 1


def test_loader_honors_unique_item_cap() -> None:
    requests: list[CatalogPageRequest] = []

    async def fetch(request: CatalogPageRequest) -> CatalogPage:
        requests.append(request)
        return page(
            request,
            [
                {"Id": f"item-{request.start_index + index}", "Name": "Title", "Type": "Movie"}
                for index in range(request.limit)
            ],
            total=20,
        )

    snapshot = run(
        load_catalog_snapshot(
            fetch,
            item_types=["Movie"],
            page_size=4,
            max_items=5,
        )
    )

    assert [request.limit for request in requests] == [4, 1]
    assert len(snapshot.items) == 5
    assert snapshot.stop_reason is CatalogLoadStopReason.MAX_ITEMS_REACHED
    assert snapshot.truncated is True


def test_loader_rejects_mismatched_response_request() -> None:
    async def fetch(request: CatalogPageRequest) -> CatalogPage:
        wrong = CatalogPageRequest(
            item_types=request.item_types,
            start_index=request.start_index + 1,
            limit=request.limit,
        )
        return page(wrong, [], total=0)

    with pytest.raises(CatalogPageResponseError, match="does not match"):
        run(load_catalog_snapshot(fetch, item_types=["Movie"]))


def test_snapshot_builds_local_index_that_resolves_bubba() -> None:
    async def fetch(request: CatalogPageRequest) -> CatalogPage:
        return page(
            request,
            [{"Id": "bubba", "Name": "Bubba Ho-tep", "Type": "Movie", "ProductionYear": 2002}],
            total=1,
        )

    snapshot = run(load_catalog_snapshot(fetch, item_types=["Movie"]))
    outcome = CatalogIndex.build(snapshot.items).search(
        "Bubba ho tep",
        context=MediaSearchContext(media_type="Movie"),
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_record.item_id == "bubba"
