"""Tests for Home Assistant search-action registration and routing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.homeassistant.ha_stubs import (
    ConfigEntryState,
    FakeEntry,
    FakeHass,
    FakeRegistryEntry,
    FakeState,
    ServiceCall,
    ServiceValidationError,
    SupportsResponse,
    install_homeassistant_stubs,
)

install_homeassistant_stubs()

from custom_components.jellyfin_assist.api import JellyfinApiError
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime
from custom_components.jellyfin_assist.playback_strategy import ChromecastPlaybackStrategy
from custom_components.jellyfin_assist.search import (
    CatalogLoadStopReason,
    CatalogManager,
    CatalogSnapshot,
)
from custom_components.jellyfin_assist.services import async_register_services


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def build_runtime(
    *,
    default_media_player: str | None = None,
    playback_targets: tuple[str, ...] = (),
    client: Any = None,
    queue_client: Any = None,
    user_id: str = "USER-1",
) -> JellyfinAssistRuntime:
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
        client=client if client is not None else object(),  # type: ignore[arg-type]
        catalog_manager=manager,
        connection_info=None,
        user_id=user_id,
        default_media_player=default_media_player,
        playback_targets=playback_targets,
        queue_client=queue_client,
    )


def test_registers_response_only_search_action_and_returns_data(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime()
    hass = FakeHass(tmp_path, entries=[entry])

    run(async_register_services(hass))
    registered = hass.services.registered[("jellyfin_assist", "search")]
    response = run(
        registered["handler"](
            ServiceCall({"config_entry_id": "entry-1", "query": "Bubba ho tep", "media_type": "Movie"})
        )
    )

    assert registered["supports_response"] is SupportsResponse.ONLY
    assert response["decision"]["status"] == "matched"
    assert response["items"][0]["name"] == "Bubba Ho-tep"


def test_registration_is_idempotent(tmp_path: Path) -> None:
    hass = FakeHass(tmp_path)

    run(async_register_services(hass))
    run(async_register_services(hass))

    assert set(hass.services.registered) == {
        ("jellyfin_assist", "get_album_tracks"),
        ("jellyfin_assist", "get_artist_tracks"),
        ("jellyfin_assist", "get_item"),
        ("jellyfin_assist", "media_orchestrator"),
        ("jellyfin_assist", "play_on_chromecast"),
        ("jellyfin_assist", "play_pending_media"),
        ("jellyfin_assist", "queue_add"),
        ("jellyfin_assist", "queue_clear"),
        ("jellyfin_assist", "queue_command"),
        ("jellyfin_assist", "queue_get"),
        ("jellyfin_assist", "queue_next"),
        ("jellyfin_assist", "queue_set_repeat"),
        ("jellyfin_assist", "queue_shuffle"),
        ("jellyfin_assist", "repair_voice_sentences"),
        ("jellyfin_assist", "resolve_media_player"),
        ("jellyfin_assist", "resume_media_request"),
        ("jellyfin_assist", "resume_pending_media_request"),
        ("jellyfin_assist", "search"),
        ("jellyfin_assist", "search_episode"),
        ("jellyfin_assist", "search_episode_title"),
        ("jellyfin_assist", "search_season"),
    }


@pytest.mark.parametrize(
    ("service_name", "call_data", "method_name", "expected_kwargs"),
    [
        ("queue_get", {"media_player": "media_player.example"}, "async_get", {"player": "media_player.example"}),
        (
            "queue_add",
            {
                "media_player": "media_player.example",
                "id": "item-1",
                "name": "Example",
                "type": "Movie",
                "artist": "",
                "album": "",
                "series": "",
                "season": "",
                "episode": "",
            },
            "async_add",
            {
                "player": "media_player.example",
                "item": {
                    "id": "item-1",
                    "name": "Example",
                    "type": "Movie",
                    "artist": "",
                    "album": "",
                    "series": "",
                    "season": "",
                    "episode": "",
                },
            },
        ),
        ("queue_next", {"media_player": "media_player.example"}, "async_next", {"player": "media_player.example"}),
        ("queue_clear", {"media_player": "media_player.example"}, "async_clear", {"player": "media_player.example"}),
        (
            "queue_set_repeat",
            {
                "media_player": "media_player.example",
                "repeat_item": True,
                "repeat_queue": False,
            },
            "async_settings",
            {
                "player": "media_player.example",
                "repeat_item": True,
                "repeat_queue": False,
            },
        ),
        ("queue_shuffle", {"media_player": "media_player.example"}, "async_shuffle", {"player": "media_player.example"}),
    ],
)
def test_native_queue_actions_preserve_rest_response_contract(
    tmp_path: Path,
    service_name: str,
    call_data: dict[str, Any],
    method_name: str,
    expected_kwargs: dict[str, Any],
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class QueueClient:
        def __getattr__(self, name: str) -> Any:
            if not name.startswith("async_"):
                raise AttributeError(name)

            async def call(**kwargs: Any) -> dict[str, Any]:
                calls.append((name, kwargs))
                return {
                    "status": 200,
                    "content": {"success": True, "status": "ok"},
                    "headers": {"Server": "jellyfin-assist-native-queue/1"},
                }

            return call

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(queue_client=QueueClient())
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    registered = hass.services.registered[("jellyfin_assist", service_name)]
    response = run(
        registered["handler"](
            ServiceCall({"config_entry_id": "entry-1", **call_data})
        )
    )

    assert registered["supports_response"] is SupportsResponse.ONLY
    assert calls == [(method_name, expected_kwargs)]
    assert response["status"] == 200
    assert response["content"]["success"] is True


def test_native_queue_transport_failure_returns_compatible_unavailable_response(
    tmp_path: Path,
) -> None:
    from custom_components.jellyfin_assist.queue_store import QueueStoreError

    class QueueClient:
        async def async_get(self, player: str) -> dict[str, Any]:
            raise QueueStoreError("offline")

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(queue_client=QueueClient())
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "queue_get")]["handler"](
            ServiceCall({"config_entry_id": "entry-1", "media_player": "media_player.example"})
        )
    )

    assert response == {
        "status": 503,
        "content": {
            "success": False,
            "status": "unavailable",
            "message": "offline",
        },
        "headers": {},
    }


@pytest.mark.parametrize(
    ("service_name", "call_data", "expected_kwargs"),
    [
        (
            "search_season",
            {"series_id": "series-1", "season": 2},
            {
                "parent_id": "series-1",
                "include_item_types": "Episode",
                "recursive": True,
                "season": 2,
                "sort_by": "ParentIndexNumber,IndexNumber",
            },
        ),
        (
            "search_episode",
            {"series_id": "series-1", "season": 2, "episode": 3},
            {
                "parent_id": "series-1",
                "include_item_types": "Episode",
                "recursive": True,
                "season": 2,
                "episode": 3,
            },
        ),
        (
            "search_episode_title",
            {"series_id": "series-1", "episode_title": "The Pilot"},
            {
                "parent_id": "series-1",
                "include_item_types": "Episode",
                "recursive": True,
                "search_term": "The Pilot",
                "sort_by": "ParentIndexNumber,IndexNumber",
                "sort_order": "Ascending",
            },
        ),
        (
            "get_album_tracks",
            {"album_id": "album-1"},
            {
                "parent_id": "album-1",
                "include_item_types": "Audio",
                "recursive": True,
                "sort_by": "ParentIndexNumber,IndexNumber",
                "sort_order": "Ascending",
            },
        ),
        (
            "get_artist_tracks",
            {"artist_id": "artist-1,artist-2"},
            {
                "artist_ids": "artist-1,artist-2",
                "include_item_types": "Audio",
                "recursive": True,
                "sort_by": "Album,ParentIndexNumber,IndexNumber",
                "sort_order": "Ascending",
            },
        ),
    ],
)
def test_native_item_query_actions_preserve_rest_response_contract(
    tmp_path: Path,
    service_name: str,
    call_data: dict[str, Any],
    expected_kwargs: dict[str, Any],
) -> None:
    calls: list[dict[str, Any]] = []

    class Client:
        async def async_get_items(
            self, user_id: str, **kwargs: Any
        ) -> dict[str, Any]:
            assert user_id == "USER-1"
            calls.append(kwargs)
            return {
                "Items": [{"Id": "item-1", "Name": "Example"}],
                "TotalRecordCount": 1,
            }

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(client=Client())
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    registered = hass.services.registered[("jellyfin_assist", service_name)]
    response = run(
        registered["handler"](
            ServiceCall({"config_entry_id": "entry-1", **call_data})
        )
    )

    assert registered["supports_response"] is SupportsResponse.ONLY
    assert calls == [expected_kwargs]
    assert response == {
        "status": 200,
        "content": {
            "Items": [{"Id": "item-1", "Name": "Example"}],
            "TotalRecordCount": 1,
        },
    }


def test_native_item_query_failure_is_translated(tmp_path: Path) -> None:
    class Client:
        async def async_get_items(self, user_id: str, **kwargs: Any) -> dict[str, Any]:
            raise JellyfinApiError("native query unavailable")

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(client=Client())
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    with pytest.raises(ServiceValidationError) as error:
        run(
            hass.services.registered[("jellyfin_assist", "search_season")][
                "handler"
            ](
                ServiceCall(
                    {
                        "config_entry_id": "entry-1",
                        "series_id": "series-1",
                        "season": 1,
                    }
                )
            )
        )

    assert error.value.translation_key == "library_query_failed"


def test_native_get_item_returns_jellyha_compatible_response(tmp_path: Path) -> None:
    class Client:
        async def async_get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            assert user_id == "USER-1"
            assert item_id == "movie-1"
            return {
                "Id": "movie-1",
                "Name": "Example Movie",
                "Type": "Movie",
                "MediaSources": [{"MediaStreams": [{"Type": "Video"}]}],
                "UserData": {"IsFavorite": True, "Played": False},
            }

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(client=Client())
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "get_item")]["handler"](
            ServiceCall({"config_entry_id": "entry-1", "item_id": "movie-1"})
        )
    )

    assert response["item"]["Id"] == "movie-1"
    assert response["item"]["media_streams"] == [{"Type": "Video"}]
    assert response["item"]["is_favorite"] is True
    assert response["item"]["is_played"] is False


def test_get_item_infers_single_entry_and_stays_native(tmp_path: Path) -> None:
    class Client:
        async def async_get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            return {"Id": item_id, "Name": "Native", "UserData": {}}

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(client=Client())
    hass = FakeHass(tmp_path, entries=[entry])

    async def legacy_get_item(call: ServiceCall) -> dict[str, Any]:
        raise AssertionError("JellyHA fallback must not run when native succeeds")

    hass.services.async_register("jellyha", "get_item", legacy_get_item)
    run(async_register_services(hass))
    response = run(
        hass.services.registered[("jellyfin_assist", "get_item")]["handler"](
            ServiceCall({"item_id": "movie-1"})
        )
    )

    assert response["item"]["Name"] == "Native"
    assert not hass.services.calls


def test_get_item_native_failure_never_calls_jellyha_even_if_available(tmp_path: Path) -> None:
    class Client:
        async def async_get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            raise JellyfinApiError("native unavailable")

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(client=Client())
    hass = FakeHass(tmp_path, entries=[entry])

    async def legacy_get_item(call: ServiceCall) -> dict[str, Any]:
        raise AssertionError("Standalone get_item must never call JellyHA")

    hass.services.async_register("jellyha", "get_item", legacy_get_item)
    run(async_register_services(hass))

    with pytest.raises(ServiceValidationError) as error:
        run(
            hass.services.registered[("jellyfin_assist", "get_item")]["handler"](
                ServiceCall({"item_id": "movie-1"})
            )
        )

    assert error.value.translation_key == "item_lookup_failed"
    assert not hass.services.calls


def test_get_item_native_failure_without_jellyha_surfaces_error(tmp_path: Path) -> None:
    class Client:
        async def async_get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            raise JellyfinApiError("native unavailable")

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(client=Client())
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    with pytest.raises(ServiceValidationError) as error:
        run(
            hass.services.registered[("jellyfin_assist", "get_item")]["handler"](
                ServiceCall({"item_id": "movie-1"})
            )
        )

    assert error.value.translation_key == "item_lookup_failed"


def test_native_playback_action_is_optional_response_and_does_not_call_jellyha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        server_url = "http://jellyfin.local:8096"
        api_key = "secret"

        async def async_get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            assert user_id == "USER-1"
            assert item_id == "movie-1"
            return {
                "Id": "movie-1",
                "Name": "Example Movie",
                "Type": "Movie",
                "Container": "mkv",
                "MediaStreams": [
                    {"Type": "Video", "Codec": "h264", "Height": 1080, "BitDepth": 8},
                    {"Type": "Audio", "Index": 1, "Codec": "aac", "Channels": 2},
                ],
            }

        async def async_get_next_up_episode(
            self, user_id: str, series_id: str
        ) -> dict[str, Any] | None:
            raise AssertionError("Movie playback must not query Next Up")

        def get_image_url(self, item_id: str, image_type: str = "Primary") -> str:
            return f"http://jellyfin.local:8096/Items/{item_id}/Images/{image_type}?api_key=secret"

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(client=Client())
    hass = FakeHass(tmp_path, entries=[entry])

    async def media_play(call: ServiceCall) -> None:
        return None

    async def forbidden_jellyha(call: ServiceCall) -> None:
        raise AssertionError("Native playback must not call JellyHA")

    hass.services.async_register("media_player", "play_media", media_play)
    hass.services.async_register("jellyha", "play_on_chromecast", forbidden_jellyha)
    monkeypatch.setattr(
        ChromecastPlaybackStrategy,
        "discover_chromecast_model",
        staticmethod(lambda hass, entity_id: ("Chromecast Ultra", False)),
    )
    run(async_register_services(hass))

    registered = hass.services.registered[("jellyfin_assist", "play_on_chromecast")]
    response = run(
        registered["handler"](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "entity_id": "media_player.example_chromecast",
                    "item_id": "movie-1",
                }
            )
        )
    )

    assert registered["supports_response"] is SupportsResponse.OPTIONAL
    assert response == {
        "success": True,
        "status": "playing",
        "entity_id": "media_player.example_chromecast",
        "requested_item_id": "movie-1",
        "item_id": "movie-1",
        "item_name": "Example Movie",
        "item_type": "Movie",
        "resolved_from_type": None,
        "device_model": "Chromecast Ultra",
        "legacy_chromecast": False,
        "playback_mode": "direct_play",
        "media_content_type": "video/mp4",
    }
    assert "secret" not in repr(response)
    assert len(hass.services.calls) == 1
    call = hass.services.calls[0]
    assert call["domain"] == "media_player"
    assert call["service"] == "play_media"
    assert call["blocking"] is True
    assert call["return_response"] is False
    assert call["data"]["entity_id"] == "media_player.example_chromecast"
    assert call["data"]["media_content_type"] == "video/mp4"
    assert call["data"]["extra"]["title"] == "Example Movie"


def test_native_playback_action_resolves_series_to_next_up_episode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        server_url = "http://jellyfin.local:8096"
        api_key = "secret"

        async def async_get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            return {"Id": item_id, "Name": "Example Series", "Type": "Series"}

        async def async_get_next_up_episode(
            self, user_id: str, series_id: str
        ) -> dict[str, Any] | None:
            assert (user_id, series_id) == ("USER-1", "series-1")
            return {
                "Id": "episode-4",
                "Name": "Fourth Episode",
                "Type": "Episode",
                "SeriesName": "Example Series",
                "ParentIndexNumber": 1,
                "IndexNumber": 4,
                "Container": "mkv",
                "MediaStreams": [
                    {"Type": "Video", "Codec": "h264", "Height": 720, "BitDepth": 8},
                    {"Type": "Audio", "Index": 1, "Codec": "aac", "Channels": 2},
                ],
            }

        def get_image_url(self, item_id: str, image_type: str = "Primary") -> str:
            return f"http://jellyfin.local:8096/Items/{item_id}/Images/{image_type}?api_key=secret"

    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(client=Client())
    hass = FakeHass(tmp_path, entries=[entry])

    async def media_play(call: ServiceCall) -> None:
        return None

    hass.services.async_register("media_player", "play_media", media_play)
    monkeypatch.setattr(
        ChromecastPlaybackStrategy,
        "discover_chromecast_model",
        staticmethod(lambda hass, entity_id: ("Chromecast", True)),
    )
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "play_on_chromecast")]["handler"](
            ServiceCall(
                {
                    "entity_id": "media_player.example_chromecast",
                    "item_id": "series-1",
                }
            )
        )
    )

    assert response["requested_item_id"] == "series-1"
    assert response["item_id"] == "episode-4"
    assert response["item_type"] == "Episode"
    assert response["resolved_from_type"] == "Series"
    assert response["legacy_chromecast"] is True
    media_call = hass.services.calls[0]["data"]
    assert media_call["extra"]["metadata"]["seriesTitle"] == "Example Series"
    assert media_call["extra"]["metadata"]["season"] == 1
    assert media_call["extra"]["metadata"]["episode"] == 4


def test_action_infers_single_loaded_config_entry(tmp_path: Path) -> None:
    entry = FakeEntry("one", {})
    entry.runtime_data = build_runtime()
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))
    handler = hass.services.registered[("jellyfin_assist", "search")]["handler"]

    response = run(handler(ServiceCall({"query": "Bubba ho tep"})))

    assert response["jellyfin_id"] == "bubba"


def test_action_requires_config_entry_when_multiple_are_loaded(tmp_path: Path) -> None:
    one = FakeEntry("one", {})
    two = FakeEntry("two", {})
    one.runtime_data = build_runtime()
    two.runtime_data = build_runtime()
    hass = FakeHass(tmp_path, entries=[one, two])
    run(async_register_services(hass))
    handler = hass.services.registered[("jellyfin_assist", "search")]["handler"]

    with pytest.raises(ServiceValidationError) as error:
        run(handler(ServiceCall({"query": "Bubba ho tep"})))

    assert error.value.translation_key == "config_entry_required"


def test_explicit_loaded_entry_is_used(tmp_path: Path) -> None:
    selected = FakeEntry("selected", {})
    other = FakeEntry("other", {})
    selected.runtime_data = build_runtime()
    other.runtime_data = build_runtime()
    hass = FakeHass(tmp_path, entries=[selected, other])
    run(async_register_services(hass))
    handler = hass.services.registered[("jellyfin_assist", "search")]["handler"]

    response = run(
        handler(
            ServiceCall(
                {
                    "config_entry_id": "selected",
                    "query": "Bubba ho tep",
                    "media_type": "Movie",
                }
            )
        )
    )

    assert response["jellyfin_id"] == "bubba"


def test_explicit_unloaded_entry_is_rejected(tmp_path: Path) -> None:
    entry = FakeEntry("entry", {})
    entry.state = ConfigEntryState.NOT_LOADED
    entry.runtime_data = build_runtime()
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))
    handler = hass.services.registered[("jellyfin_assist", "search")]["handler"]

    with pytest.raises(ServiceValidationError) as error:
        run(handler(ServiceCall({"config_entry_id": "entry", "query": "Title"})))

    assert error.value.translation_key == "config_entry_not_loaded"


def test_explicit_media_player_overrides_configured_default(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(default_media_player="media_player.example_chromecast")
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "media_player": "media_player.example_secondary_chromecast",
                    "query": "Bubba Ho-tep",
                    "operation": "play",
                }
            )
        )
    )

    assert response["success"] is True
    assert response["status"] == "resolved"
    assert response["source"] == "explicit"
    assert response["media_player"] == "media_player.example_secondary_chromecast"
    assert response["query"] == "Bubba Ho-tep"
    assert response["player_resolution"]["match_method"] == "entity_id"
    assert entry.runtime_data.pending_media_request is None



def test_entity_id_resolution_uses_preferred_native_alias_for_response(
    tmp_path: Path,
) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(
        playback_targets=("media_player.example_chromecast",)
    )
    hass = FakeHass(
        tmp_path,
        entries=[entry],
        registry_entries=[
            FakeRegistryEntry("media_player.example_chromecast", ["Example Chromecast", "Movie Screen"]),
        ],
    )
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "media_player": "media_player.example_chromecast",
                    "query": "Higher",
                }
            )
        )
    )

    assert response["media_player_name"] == "Movie Screen"
    assert response["player_resolution"]["match_method"] == "entity_id"



def test_entity_id_resolution_does_not_leak_mismatched_friendly_name(
    tmp_path: Path,
) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(playback_targets=("media_player.attic_tv",))
    hass = FakeHass(
        tmp_path,
        entries=[entry],
        states=[FakeState("media_player.attic_tv", friendly_name="Main TV")],
        registry_entries=[FakeRegistryEntry("media_player.attic_tv")],
    )
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "media_player": "media_player.attic_tv",
                    "query": "Jurassic World",
                    "operation": "play",
                }
            )
        )
    )

    assert response["success"] is True
    assert response["media_player"] == "media_player.attic_tv"
    assert response["media_player_name"] == "Attic TV"
    assert response["player_resolution"]["matched_name"] == "Main TV"
    assert response["player_resolution"]["matched_alias"] == "Attic TV"

def test_configured_default_is_used_when_player_is_omitted(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(default_media_player="media_player.example_chromecast")
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "query": "Bubba Ho-tep",
                    "operation": "play",
                }
            )
        )
    )

    assert response["success"] is True
    assert response["source"] == "default"
    assert response["media_player"] == "media_player.example_chromecast"


def test_missing_default_stores_request_for_player_follow_up(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime()
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "query": "three am",
                    "operation": "add",
                    "media_type": "Audio",
                    "artist": "Matchbox",
                }
            )
        )
    )

    assert response["status"] == "media_player_required"
    assert response["reason"] == "no_default_configured"
    assert response["request_stored"] is True
    assert entry.runtime_data.pending_media_request == {
        "query": "three am",
        "operation": "add",
        "media_type": "Audio",
        "artist": "Matchbox",
        "album": "",
        "series": "",
        "year": None,
        "season": None,
        "episode": None,
    }


def test_player_follow_up_resumes_and_consumes_pending_request(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime()
    entry.runtime_data.pending_media_request = {
        "query": "three am",
        "operation": "play",
        "media_type": "Audio",
        "artist": "",
        "album": "",
        "series": "",
        "year": None,
        "season": None,
        "episode": None,
    }
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resume_media_request")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "media_player": "media_player.example_secondary_chromecast",
                }
            )
        )
    )

    assert response["success"] is True
    assert response["status"] == "resumed"
    assert response["query"] == "three am"
    assert response["media_type"] == "Audio"
    assert response["media_player"] == "media_player.example_secondary_chromecast"
    assert entry.runtime_data.pending_media_request is None


def test_player_follow_up_without_pending_request_is_safe(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime()
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resume_media_request")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "media_player": "media_player.example_secondary_chromecast",
                }
            )
        )
    )

    assert response["success"] is False
    assert response["status"] == "no_pending_media_request"


def test_native_home_assistant_alias_resolves_explicit_player(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(
        playback_targets=(
            "media_player.example_chromecast",
            "media_player.example_secondary_chromecast",
        )
    )
    hass = FakeHass(
        tmp_path,
        entries=[entry],
        registry_entries=[
            FakeRegistryEntry("media_player.example_chromecast", ["Example Chromecast", "Movie Screen"]),
            FakeRegistryEntry("media_player.example_secondary_chromecast", ["Example Secondary Chromecast"]),
        ],
    )
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "media_player": "Movie.Screen",
                    "query": "My Sacrifice",
                    "media_type": "Audio",
                }
            )
        )
    )

    assert response["success"] is True
    assert response["media_player"] == "media_player.example_chromecast"
    assert response["player_resolution"]["matched_alias"] == "Movie Screen"


def test_trailing_player_alias_is_recovered_from_artist_context(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(
        default_media_player="media_player.example_chromecast",
        playback_targets=(
            "media_player.example_chromecast",
            "media_player.example_secondary_chromecast",
        ),
    )
    hass = FakeHass(
        tmp_path,
        entries=[entry],
        registry_entries=[
            FakeRegistryEntry("media_player.example_chromecast", ["Example Chromecast", "Movie Screen"]),
            FakeRegistryEntry("media_player.example_secondary_chromecast", ["Example Secondary Chromecast"]),
        ],
    )
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "query": "Crash Into Me",
                    "artist": "Dave Matthews Band on Movie Screen",
                    "media_type": "Audio",
                }
            )
        )
    )

    assert response["success"] is True
    assert response["source"] == "trailing_alias"
    assert response["media_player"] == "media_player.example_chromecast"
    assert response["artist"] == "Dave Matthews Band"
    assert response["player_resolution"]["trailing_recovery_used"] is True
    assert response["media_player_name"] == "Movie Screen"


def test_unrecognized_trailing_player_never_falls_back_to_default(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(
        default_media_player="media_player.example_chromecast",
        playback_targets=(
            "media_player.example_chromecast",
            "media_player.example_secondary_chromecast",
        ),
    )
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "query": "Bubba Ho-tep on Bedroom TV",
                    "operation": "play",
                    "media_type": "Movie",
                }
            )
        )
    )

    assert response["success"] is False
    assert response["reason"] == "explicit_player_not_found"
    assert response["query"] == "Bubba Ho-tep"
    assert entry.runtime_data.pending_media_request["query"] == "Bubba Ho-tep"


def test_follow_up_accepts_unique_typo_with_configured_targets(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(
        playback_targets=(
            "media_player.example_chromecast",
            "media_player.example_secondary_chromecast",
        )
    )
    entry.runtime_data.pending_media_request = {
        "query": "three am",
        "operation": "play",
        "media_type": "Audio",
        "artist": "",
        "album": "",
        "series": "",
        "year": None,
        "season": None,
        "episode": None,
    }
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resume_media_request")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "media_player": "example secondary chromcast",
                }
            )
        )
    )

    assert response["success"] is True
    assert response["media_player"] == "media_player.example_secondary_chromecast"
    assert response["media_player_name"] == "Example Secondary Chromecast"
    assert response["player_resolution"]["match_method"] == "fuzzy_alias"


def test_invalid_legacy_default_outside_allowlist_is_not_used(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(
        default_media_player="media_player.example_chromecast",
        playback_targets=("media_player.example_secondary_chromecast",),
    )
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "query": "Bubba Ho-tep",
                    "media_type": "Movie",
                }
            )
        )
    )

    assert response["success"] is False
    assert response["reason"] == "configured_default_not_allowed"


def test_queue_request_without_default_is_stored_for_player_follow_up(
    tmp_path: Path,
) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime()
    hass = FakeHass(tmp_path, entries=[entry])
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resolve_media_player")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "operation": "queue_status",
                }
            )
        )
    )

    assert response["success"] is False
    assert response["status"] == "media_player_required"
    assert response["request_stored"] is True
    assert entry.runtime_data.pending_media_request is not None
    assert entry.runtime_data.pending_media_request["operation"] == "queue_status"
    assert entry.runtime_data.pending_media_request["query"] == ""


def test_queue_follow_up_accepts_native_alias_and_restores_operation(
    tmp_path: Path,
) -> None:
    entry = FakeEntry("entry-1", {})
    entry.runtime_data = build_runtime(
        playback_targets=("media_player.example_chromecast", "media_player.example_secondary_chromecast")
    )
    entry.runtime_data.pending_media_request = {
        "query": "",
        "operation": "queue_status",
        "media_type": None,
        "artist": "",
        "album": "",
        "series": "",
        "year": None,
        "season": None,
        "episode": None,
    }
    hass = FakeHass(
        tmp_path,
        entries=[entry],
        registry_entries=[
            FakeRegistryEntry("media_player.example_chromecast", ["Example Chromecast", "Movie Screen"]),
            FakeRegistryEntry("media_player.example_secondary_chromecast", ["Example Secondary Chromecast"]),
        ],
    )
    run(async_register_services(hass))

    response = run(
        hass.services.registered[("jellyfin_assist", "resume_media_request")][
            "handler"
        ](
            ServiceCall(
                {
                    "config_entry_id": "entry-1",
                    "media_player": "Movie Screen",
                }
            )
        )
    )

    assert response["success"] is True
    assert response["operation"] == "queue_status"
    assert response["media_player"] == "media_player.example_chromecast"
    assert response["media_player_name"] == "Movie Screen"
    assert entry.runtime_data.pending_media_request is None


def test_repair_voice_sentences_action_installs_managed_file(tmp_path: Path) -> None:
    hass = FakeHass(tmp_path)
    run(async_register_services(hass))

    registered = hass.services.registered[("jellyfin_assist", "repair_voice_sentences")]
    response = run(registered["handler"](ServiceCall({})))

    assert registered["supports_response"] is SupportsResponse.ONLY
    assert response["status"] == "installed"
    assert response["managed"] is True
    assert response["current"] is True
    assert (
        tmp_path
        / "custom_sentences"
        / "en"
        / "jellyfin_assist_media.yaml"
    ).is_file()
