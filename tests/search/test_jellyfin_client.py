"""Tests for the concrete JellyHA-compatible Jellyfin catalog client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from custom_components.jellyfin_assist.matching import (
    MatchDecisionStatus,
    MediaSearchContext,
)
from custom_components.jellyfin_assist.search import (
    CatalogPageRequest,
    CatalogQueryAttempt,
    CatalogQueryMethod,
    CatalogSearchFilters,
    CatalogSearchRequest,
    JellyfinCatalogClient,
    JellyfinCatalogConfigurationError,
    JellyfinCatalogResponseError,
    retrieve_rank_and_decide,
)


def run(coro: Any) -> Any:
    """Run one async client function without an asyncio pytest plugin."""

    return asyncio.run(coro)


def request(
    term: str = "Matrix",
    *,
    limit: int = 20,
    filters: CatalogSearchFilters | None = None,
) -> CatalogSearchRequest:
    """Build one direct request fixture."""

    return CatalogSearchRequest(
        attempt=CatalogQueryAttempt(
            index=0,
            term=term,
            methods=(CatalogQueryMethod.ORIGINAL,),
        ),
        limit=limit,
        filters=filters or CatalogSearchFilters(),
    )


class RecordingApi:
    """Fake JellyHA API that records both supported catalog call shapes."""

    def __init__(
        self,
        *,
        library_response: Any = (),
        artist_response: Any = None,
    ) -> None:
        self.library_response = library_response
        self.artist_response = {"Items": []} if artist_response is None else artist_response
        self.library_calls: list[dict[str, Any]] = []
        self.raw_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def get_library_items(self, **kwargs: Any) -> Any:
        self.library_calls.append(kwargs)
        if isinstance(self.library_response, Exception):
            raise self.library_response
        return self.library_response

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any],
    ) -> Any:
        self.raw_calls.append((method, path, params))
        if isinstance(self.artist_response, Exception):
            raise self.artist_response
        return self.artist_response


@dataclass
class FakeEntry:
    data: Any


class EntryCoordinator:
    def __init__(self, api: Any, data: Any) -> None:
        self._api = api
        self.entry = FakeEntry(data)


class ConfigEntryCoordinator:
    def __init__(self, api: Any, data: Any) -> None:
        self._api = api
        self.config_entry = FakeEntry(data)


def test_direct_client_requires_api() -> None:
    with pytest.raises(JellyfinCatalogConfigurationError, match="API"):
        JellyfinCatalogClient(api=None, user_id="user")


def test_direct_client_requires_nonempty_user_id() -> None:
    with pytest.raises(JellyfinCatalogConfigurationError, match="user_id"):
        JellyfinCatalogClient(api=RecordingApi(), user_id="  ")


def test_direct_client_strips_user_id_whitespace() -> None:
    client = JellyfinCatalogClient(api=RecordingApi(), user_id="  user-1  ")

    assert client.user_id == "user-1"


def test_client_builds_from_current_jellyha_entry_shape() -> None:
    api = RecordingApi()
    coordinator = EntryCoordinator(api, {"user_id": "user-1"})

    client = JellyfinCatalogClient.from_jellyha_coordinator(coordinator)

    assert client.api is api
    assert client.user_id == "user-1"


def test_client_accepts_config_entry_fallback_shape() -> None:
    api = RecordingApi()
    coordinator = ConfigEntryCoordinator(api, {"user_id": "user-2"})

    client = JellyfinCatalogClient.from_jellyha_coordinator(coordinator)

    assert client.api is api
    assert client.user_id == "user-2"


def test_coordinator_requires_initialized_api() -> None:
    coordinator = EntryCoordinator(None, {"user_id": "user"})

    with pytest.raises(JellyfinCatalogConfigurationError, match="not initialized"):
        JellyfinCatalogClient.from_jellyha_coordinator(coordinator)


def test_coordinator_requires_entry_attribute() -> None:
    coordinator = type("Coordinator", (), {"_api": RecordingApi()})()

    with pytest.raises(JellyfinCatalogConfigurationError, match="entry"):
        JellyfinCatalogClient.from_jellyha_coordinator(coordinator)


def test_coordinator_entry_data_must_be_mapping() -> None:
    coordinator = EntryCoordinator(RecordingApi(), ["not", "a", "mapping"])

    with pytest.raises(JellyfinCatalogConfigurationError, match="mapping data"):
        JellyfinCatalogClient.from_jellyha_coordinator(coordinator)


def test_coordinator_requires_user_id() -> None:
    coordinator = EntryCoordinator(RecordingApi(), {})

    with pytest.raises(JellyfinCatalogConfigurationError, match="user_id"):
        JellyfinCatalogClient.from_jellyha_coordinator(coordinator)


def test_library_request_translates_all_current_jellyha_filters() -> None:
    api = RecordingApi(
        library_response=(
            {"Id": "movie", "Name": "The Matrix", "Type": "Movie"},
        )
    )
    client = JellyfinCatalogClient(api=api, user_id="user")
    filters = CatalogSearchFilters(
        media_type="Movie",
        is_played=False,
        is_favorite=True,
        genre="Science Fiction",
        year=1999,
        min_rating=7.5,
        season=1,
        episode=2,
    )

    items = run(client(request("Matrix", limit=17, filters=filters)))

    assert items == ({"Id": "movie", "Name": "The Matrix", "Type": "Movie"},)
    assert api.library_calls == [
        {
            "user_id": "user",
            "limit": 17,
            "search_term": "Matrix",
            "item_types": ["Movie"],
            "is_played": False,
            "is_favorite": True,
            "genre": "Science Fiction",
            "year": 1999,
            "min_rating": 7.5,
            "season": 1,
            "episode": 2,
        }
    ]
    assert api.raw_calls == []


def test_untyped_library_request_passes_none_for_item_types() -> None:
    api = RecordingApi()
    client = JellyfinCatalogClient(api=api, user_id="user")

    run(client(request("Anything")))

    assert api.library_calls[0]["item_types"] is None


def test_library_items_are_copied_from_api_response() -> None:
    original = {"Id": "movie", "Name": "Matrix"}
    api = RecordingApi(library_response=[original])
    client = JellyfinCatalogClient(api=api, user_id="user")

    items = run(client(request()))
    items[0]["Name"] = "Changed locally"

    assert original["Name"] == "Matrix"


def test_library_api_method_is_required() -> None:
    api = object()
    client = JellyfinCatalogClient(api=api, user_id="user")

    with pytest.raises(JellyfinCatalogConfigurationError, match="get_library_items"):
        run(client(request()))


def test_library_response_must_be_sequence() -> None:
    api = RecordingApi(library_response={"Items": []})
    client = JellyfinCatalogClient(api=api, user_id="user")

    with pytest.raises(JellyfinCatalogResponseError, match="sequence"):
        run(client(request()))


def test_library_response_items_must_be_mappings() -> None:
    api = RecordingApi(library_response=["invalid"])
    client = JellyfinCatalogClient(api=api, user_id="user")

    with pytest.raises(JellyfinCatalogResponseError, match="non-mapping"):
        run(client(request()))


def test_library_api_exception_propagates_for_retrieval_layer() -> None:
    api = RecordingApi(library_response=RuntimeError("server unavailable"))
    client = JellyfinCatalogClient(api=api, user_id="user")

    with pytest.raises(RuntimeError, match="server unavailable"):
        run(client(request()))


def test_music_artist_uses_current_jellyha_endpoint_contract() -> None:
    api = RecordingApi(
        artist_response={
            "Items": [
                {"Id": "artist", "Name": "Matchbox Twenty", "Type": "MusicArtist"}
            ]
        }
    )
    client = JellyfinCatalogClient(api=api, user_id="user")

    items = run(
        client(
            request(
                "matchbox twenty",
                limit=9,
                filters=CatalogSearchFilters(media_type="MusicArtist"),
            )
        )
    )

    assert items[0]["Id"] == "artist"
    assert api.library_calls == []
    assert api.raw_calls == [
        (
            "GET",
            "/Artists/AlbumArtists",
            {
                "SortBy": "SortName",
                "SortOrder": "Ascending",
                "Recursive": "true",
                "Fields": "PrimaryImageAspectRatio,ProviderIds",
                "Limit": "9",
                "searchTerm": "matchbox twenty",
            },
        )
    ]


def test_music_artist_path_preserves_existing_filter_behavior() -> None:
    api = RecordingApi()
    client = JellyfinCatalogClient(api=api, user_id="user")
    filters = CatalogSearchFilters(
        media_type="MusicArtist",
        is_favorite=True,
        genre="Rock",
        year=1996,
    )

    run(client(request("Matchbox", filters=filters)))

    params = api.raw_calls[0][2]
    assert set(params) == {
        "SortBy",
        "SortOrder",
        "Recursive",
        "Fields",
        "Limit",
        "searchTerm",
    }


def test_music_artist_missing_items_is_an_empty_result() -> None:
    api = RecordingApi(artist_response={})
    client = JellyfinCatalogClient(api=api, user_id="user")

    items = run(
        client(
            request(
                "Unknown",
                filters=CatalogSearchFilters(media_type="MusicArtist"),
            )
        )
    )

    assert items == ()


def test_music_artist_response_must_be_mapping() -> None:
    api = RecordingApi(artist_response=[])
    client = JellyfinCatalogClient(api=api, user_id="user")

    with pytest.raises(JellyfinCatalogResponseError, match="mapping response"):
        run(
            client(
                request(
                    "Artist",
                    filters=CatalogSearchFilters(media_type="MusicArtist"),
                )
            )
        )


def test_music_artist_items_must_be_sequence() -> None:
    api = RecordingApi(artist_response={"Items": {"Id": "artist"}})
    client = JellyfinCatalogClient(api=api, user_id="user")

    with pytest.raises(JellyfinCatalogResponseError, match="sequence"):
        run(
            client(
                request(
                    "Artist",
                    filters=CatalogSearchFilters(media_type="MusicArtist"),
                )
            )
        )


def test_music_artist_api_method_is_required() -> None:
    api = type("LibraryOnly", (), {"get_library_items": lambda self, **kwargs: ()})()
    client = JellyfinCatalogClient(api=api, user_id="user")

    with pytest.raises(JellyfinCatalogConfigurationError, match="artist request"):
        run(
            client(
                request(
                    "Artist",
                    filters=CatalogSearchFilters(media_type="MusicArtist"),
                )
            )
        )


def test_concrete_client_runs_complete_three_am_retrieval_path() -> None:
    class VariantApi(RecordingApi):
        async def get_library_items(self, **kwargs: Any) -> Any:
            self.library_calls.append(kwargs)
            if kwargs["search_term"] == "3am":
                return [
                    {
                        "Id": "song",
                        "Name": "3AM",
                        "Type": "Audio",
                        "Artists": ["Matchbox Twenty"],
                    }
                ]
            return []

    api = VariantApi()
    client = JellyfinCatalogClient(api=api, user_id="user")

    outcome = run(
        retrieve_rank_and_decide(
            "three am",
            client,
            context=MediaSearchContext(media_type="Audio"),
        )
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_catalog_candidate is not None
    assert outcome.selected_catalog_candidate.item_id == "song"
    assert [call["search_term"] for call in api.library_calls] == [
        "three am",
        "3 am",
        "3am",
    ]


def test_adapter_never_calls_coordinator_transformer() -> None:
    class TransformTrapCoordinator(EntryCoordinator):
        async def _async_transform_item(self, _item: Any) -> Any:
            raise AssertionError("transformer must not be called by catalog adapter")

    api = RecordingApi(library_response=[{"Id": "movie", "Name": "Matrix"}])
    coordinator = TransformTrapCoordinator(api, {"user_id": "user"})
    client = JellyfinCatalogClient.from_jellyha_coordinator(coordinator)

    items = run(client(request()))

    assert items[0]["Id"] == "movie"


def test_regular_catalog_page_uses_paginated_user_items_endpoint() -> None:
    api = RecordingApi(
        artist_response={
            "Items": [{"Id": "movie", "Name": "Matrix", "Type": "Movie"}],
            "TotalRecordCount": 11,
        }
    )
    client = JellyfinCatalogClient(api=api, user_id="user")
    request_value = CatalogPageRequest(
        item_types=("Movie", "Audio"),
        start_index=5,
        limit=3,
    )

    result = run(client.fetch_catalog_page(request_value))

    assert result.request == request_value
    assert result.total_record_count == 11
    assert result.items[0]["Id"] == "movie"
    assert api.raw_calls[0][0:2] == ("GET", "/Users/user/Items")
    params = api.raw_calls[0][2]
    assert params["IncludeItemTypes"] == "Movie,Audio"
    assert params["StartIndex"] == "5"
    assert params["Limit"] == "3"
    assert "ProviderIds" in params["Fields"]
    assert "SearchTerm" not in params


def test_artist_catalog_page_uses_dedicated_endpoint_and_sets_type() -> None:
    api = RecordingApi(
        artist_response={
            "Items": [{"Id": "artist", "Name": "Metallica"}],
            "TotalRecordCount": 1,
        }
    )
    client = JellyfinCatalogClient(api=api, user_id="user")
    request_value = CatalogPageRequest(
        item_types=("MusicArtist",),
        start_index=0,
        limit=100,
    )

    result = run(client.fetch_catalog_page(request_value))

    assert result.items[0]["Type"] == "MusicArtist"
    assert api.raw_calls[0][0:2] == ("GET", "/Artists/AlbumArtists")
    params = api.raw_calls[0][2]
    assert params["UserId"] == "user"
    assert params["StartIndex"] == "0"
    assert params["Limit"] == "100"
    assert "ProviderIds" in params["Fields"]


def test_catalog_page_requires_mapping_response() -> None:
    api = RecordingApi(artist_response=[])
    client = JellyfinCatalogClient(api=api, user_id="user")

    with pytest.raises(JellyfinCatalogResponseError, match="mapping response"):
        run(
            client.fetch_catalog_page(
                CatalogPageRequest(item_types=("Movie",), start_index=0, limit=10)
            )
        )


def test_catalog_page_total_must_be_integer() -> None:
    api = RecordingApi(artist_response={"Items": [], "TotalRecordCount": "1"})
    client = JellyfinCatalogClient(api=api, user_id="user")

    with pytest.raises(JellyfinCatalogResponseError, match="integer"):
        run(
            client.fetch_catalog_page(
                CatalogPageRequest(item_types=("Movie",), start_index=0, limit=10)
            )
        )
