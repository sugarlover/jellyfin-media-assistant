"""Tests for native media resolution and orchestration replacing YAML scripts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from tests.homeassistant.ha_stubs import FakeHass, FakeState, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist import orchestration
from custom_components.jellyfin_assist.orchestration import (
    async_media_orchestrator,
    async_play_pending_media,
    async_resolve_media_intent,
)
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime
from custom_components.jellyfin_assist.search import CatalogManager


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def runtime(*, client: Any = None) -> JellyfinAssistRuntime:
    async def loader() -> Any:
        raise AssertionError("catalog loader not used")

    return JellyfinAssistRuntime(
        client=client if client is not None else object(),  # type: ignore[arg-type]
        catalog_manager=CatalogManager(
            snapshot_loader=loader,
            requested_types=["Movie"],
            cache_identity="server:user",
            cache_store=None,
        ),
        connection_info=None,
        entry_id="entry-1",
        user_id="user-1",
    )


def test_album_resolution_expands_ordered_audio_plan(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(tmp_path)
    rt = runtime()

    async def search(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": "album-1",
                    "name": "Weathered",
                    "type": "MusicAlbum",
                    "album_artist": "Creed",
                }
            ]
        }

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args[2] == "get_album_tracks"
        return {
            "status": 200,
            "content": {
                "Items": [
                    {
                        "Id": "song-1",
                        "Name": "Bullets",
                        "Type": "Audio",
                        "Artists": ["Creed"],
                        "AlbumArtist": "Creed",
                        "Album": "Weathered",
                        "ParentIndexNumber": 1,
                        "IndexNumber": 1,
                    },
                    {
                        "Id": "song-2",
                        "Name": "Freedom Fighter",
                        "Type": "Audio",
                        "Artists": ["Creed"],
                        "AlbumArtist": "Creed",
                        "Album": "Weathered",
                        "ParentIndexNumber": 1,
                        "IndexNumber": 2,
                    },
                ]
            },
        }

    monkeypatch.setattr(orchestration, "_search", search)
    monkeypatch.setattr(orchestration, "_action", action)

    result = run(
        async_resolve_media_intent(
            hass,
            rt,
            query="Weathered",
            media_type="MusicAlbum",
            artist="Creed",
        )
    )

    assert result["success"] is True
    assert result["intent"] == "MusicAlbum"
    assert [item["name"] for item in result["playback_plan"]] == ["Bullets", "Freedom Fighter"]
    assert result["playback_plan"][0]["artist_name"] == "Creed"
    assert result["message"] == "Found Weathered by Creed. The album contains 2 tracks."


def test_numbered_episode_resolution_preserves_series_context(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(tmp_path)
    rt = runtime()

    async def search(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["media_type"] == "Series"
        return {"items": [{"id": "series-1", "name": "The Twilight Zone", "type": "Series"}]}

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args[2] == "search_episode"
        return {
            "status": 200,
            "content": {
                "Items": [
                    {
                        "Id": "ep-1",
                        "Name": "Where Is Everybody?",
                        "ParentIndexNumber": 1,
                        "IndexNumber": 1,
                    }
                ]
            },
        }

    monkeypatch.setattr(orchestration, "_search", search)
    monkeypatch.setattr(orchestration, "_action", action)

    result = run(
        async_resolve_media_intent(
            hass,
            rt,
            query="The Twilight Zone",
            media_type="Series",
            season=1,
            episode=1,
        )
    )

    assert result["success"] is True
    assert result["intent"] == "Episode"
    assert result["jellyfin_id"] == "ep-1"
    assert result["playback_plan"] == [
        {
            "id": "ep-1",
            "name": "Where Is Everybody?",
            "type": "Episode",
            "series_name": "The Twilight Zone",
            "series_id": "series-1",
            "season": 1,
            "episode": 1,
        }
    ]


def test_resolver_preserves_phonetic_candidate_as_confirmation_only(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    hass = FakeHass(tmp_path)
    rt = runtime()
    candidate = {
        "id": "hailie",
        "name": "Hailie's Song",
        "type": "Audio",
        "artist_name": "Eminem",
        "album": "The Eminem Show",
    }

    async def search(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["media_type"] == "Audio"
        return {
            "items": [],
            "confirmation": {"item": candidate},
        }

    monkeypatch.setattr(orchestration, "_search", search)

    result = run(
        async_resolve_media_intent(
            hass,
            rt,
            query="Haley's Song",
            media_type="Audio",
        )
    )

    assert result["success"] is False
    assert result["status"] == "confirmation_required"
    assert result["items"] == []
    assert result["item"] is None
    assert result["playback_plan"] == []
    assert result["confirmation"] == candidate
    assert "Hailie's Song by Eminem" in result["message"]


def test_orchestrator_stores_multiple_matches_in_runtime(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(
        tmp_path,
        states=[FakeState("media_player.attic_tv", friendly_name="Attic TV")],
    )
    rt = runtime()

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args[2] == "resolve_media_player"
        return {
            "success": True,
            "media_player": "media_player.attic_tv",
            "media_player_name": "Attic TV",
            "query": "planet",
        }

    async def resolver(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "success": False,
            "status": "multiple_matches",
            "intent": "Movie",
            "query": "planet",
            "media_type": "Movie",
            "items": [
                {"id": "1", "name": "Planet of the Apes", "type": "Movie", "year": 1968},
                {"id": "2", "name": "Beneath the Planet of the Apes", "type": "Movie", "year": 1970},
            ],
            "playback_plan": [],
        }

    monkeypatch.setattr(orchestration, "_action", action)
    monkeypatch.setattr(orchestration, "async_resolve_media_intent", resolver)

    result = run(
        async_media_orchestrator(
            hass,
            rt,
            query="planet",
            media_player="media_player.attic_tv",
            media_type="Movie",
        )
    )

    assert result["status"] == "multiple_matches"
    assert "1. Planet of the Apes (1968)" in result["message"]
    assert "Please select a number." in result["message"]
    assert rt.pending_selection == {
        "items": result["items"],
        "media_player": "media_player.attic_tv",
        "operation": "play",
        "query": "planet",
        "intent": "Movie",
    }


def test_orchestrator_stores_phonetic_confirmation_as_one_pending_selection(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    hass = FakeHass(
        tmp_path,
        states=[FakeState("media_player.fredphone", friendly_name="Fred's phone")],
    )
    rt = runtime()
    candidate = {
        "id": "hailie",
        "name": "Hailie's Song",
        "type": "Audio",
        "artist_name": "Eminem",
        "album": "The Eminem Show",
    }

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args[2] == "resolve_media_player"
        return {
            "success": True,
            "media_player": "media_player.fredphone",
            "media_player_name": "Fred's phone",
            "query": "Haley's Song",
            "media_type": "Audio",
        }

    async def resolver(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "success": False,
            "status": "confirmation_required",
            "intent": "Audio",
            "query": "Haley's Song",
            "media_type": "Audio",
            "items": [],
            "confirmation": candidate,
            "playback_plan": [],
        }

    monkeypatch.setattr(orchestration, "_action", action)
    monkeypatch.setattr(orchestration, "async_resolve_media_intent", resolver)

    result = run(
        async_media_orchestrator(
            hass,
            rt,
            query="Haley's Song",
            media_player="media_player.fredphone",
            media_type="Audio",
        )
    )

    assert result["success"] is False
    assert result["status"] == "confirmation_required"
    assert result["item"] == candidate
    assert result["items"] == [candidate]
    assert result["confirmation"] == candidate
    assert result["message"] == (
        "I found Hailie's Song by Eminem from The Eminem Show. Did you mean that? "
        'Say "select number one" to confirm.'
    )
    assert rt.pending_selection == {
        "items": [candidate],
        "media_player": "media_player.fredphone",
        "operation": "play",
        "query": "Haley's Song",
        "intent": "Audio",
    }


def test_orchestrator_play_path_preserves_success_message(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(
        tmp_path,
        states=[FakeState("media_player.basement_tv", friendly_name="Basement TV")],
    )
    rt = runtime()

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        service = args[2]
        if service == "resolve_media_player":
            return {
                "success": True,
                "media_player": "media_player.basement_tv",
                "media_player_name": "Basement TV",
                "query": "Jurassic World",
                "media_type": "Movie",
            }
        if service == "queue_clear":
            return {"status": 200, "content": {"success": True}}
        if service == "queue_add":
            return {"status": 200, "content": {"success": True, "status": "added"}}
        raise AssertionError(service)

    async def resolver(*args: Any, **kwargs: Any) -> dict[str, Any]:
        item = {"id": "movie-1", "name": "Jurassic World", "type": "Movie", "year": 2015}
        return {
            "success": True,
            "status": "resolved",
            "intent": "Movie",
            "query": "Jurassic World",
            "jellyfin_id": "movie-1",
            "item": item,
            "items": [item],
            "playback_plan": [item],
        }

    async def prepare(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"success": True, "status": "ready"}

    async def play(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"success": True, "status": "playing"}

    monkeypatch.setattr(orchestration, "_action", action)
    monkeypatch.setattr(orchestration, "async_resolve_media_intent", resolver)
    monkeypatch.setattr(orchestration, "async_prepare_play_session", prepare)
    monkeypatch.setattr(orchestration, "async_play_item", play)

    result = run(
        async_media_orchestrator(
            hass,
            rt,
            query="Jurassic World",
            media_player="media_player.basement_tv",
            media_type="Movie",
        )
    )

    assert result["success"] is True
    assert result["status"] == "playing"
    assert result["message"] == "Playing Jurassic World (2015) on Basement TV."
    assert result["media_player_name"] == "Basement TV"


def test_pending_selection_uses_runtime_state_and_clears_on_success(tmp_path: Path, monkeypatch: Any) -> None:
    class Client:
        async def async_get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
            assert user_id == "user-1"
            assert item_id == "movie-1"
            return {
                "Id": "movie-1",
                "Name": "Planet of the Apes",
                "Type": "Movie",
                "ProductionYear": 1968,
            }

    hass = FakeHass(
        tmp_path,
        states=[FakeState("media_player.attic_tv", friendly_name="Attic TV")],
    )
    rt = runtime(client=Client())
    rt.pending_selection = {
        "items": [{"id": "movie-1", "name": "Planet of the Apes", "type": "Movie"}],
        "media_player": "media_player.attic_tv",
        "operation": "play",
        "query": "planet",
        "intent": "Movie",
    }

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        service = args[2]
        if service == "queue_clear":
            return {"status": 200, "content": {"success": True}}
        if service == "queue_add":
            return {"status": 200, "content": {"success": True, "status": "added"}}
        raise AssertionError(service)

    async def prepare(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"success": True}

    async def play(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"success": True, "status": "playing"}

    monkeypatch.setattr(orchestration, "_action", action)
    monkeypatch.setattr(orchestration, "async_prepare_play_session", prepare)
    monkeypatch.setattr(orchestration, "async_play_item", play)

    result = run(async_play_pending_media(hass, rt, selection=1))

    assert result["success"] is True
    assert result["message"] == "Playing Planet of the Apes (1968) on Attic TV."
    assert result["query"] == "planet"
    assert result["intent"] == "Movie"
    assert rt.pending_selection is None


def test_series_resolution_expands_season_in_episode_order(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(tmp_path)
    rt = runtime()

    async def search(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"items": [{"id": "series-1", "name": "The Twilight Zone", "type": "Series"}]}

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args[2] == "search_season"
        return {
            "status": 200,
            "content": {"Items": [
                {"Id": "ep-1", "Name": "Where Is Everybody?", "ParentIndexNumber": 1, "IndexNumber": 1},
                {"Id": "ep-2", "Name": "One for the Angels", "ParentIndexNumber": 1, "IndexNumber": 2},
            ]},
        }

    monkeypatch.setattr(orchestration, "_search", search)
    monkeypatch.setattr(orchestration, "_action", action)
    result = run(async_resolve_media_intent(hass, rt, query="The Twilight Zone", media_type="Series", season=1))
    assert result["success"] is True
    assert result["intent"] == "Series"
    assert [item["episode"] for item in result["playback_plan"]] == [1, 2]
    assert result["message"] == "Found The Twilight Zone. Season 1 contains 2 episodes."


def test_artist_resolution_uses_all_physical_ids_and_stable_track_order(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(tmp_path)
    rt = runtime()

    async def search(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"items": [{
            "id": "artist-logical",
            "name": "Creed",
            "type": "MusicArtist",
            "physical_ids": ["artist-a", "artist-b"],
        }]}

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args[2] == "get_artist_tracks"
        assert args[3]["artist_id"] == "artist-a,artist-b"
        return {
            "status": 200,
            "content": {"Items": [
                {"Id": "later", "Name": "Later", "Artists": ["Creed"], "Album": "B", "ProductionYear": 2002, "IndexNumber": 2},
                {"Id": "early", "Name": "Early", "Artists": ["Creed"], "Album": "A", "ProductionYear": 2001, "IndexNumber": 1},
            ]},
        }

    monkeypatch.setattr(orchestration, "_search", search)
    monkeypatch.setattr(orchestration, "_action", action)
    result = run(async_resolve_media_intent(hass, rt, query="Creed", media_type="MusicArtist"))
    assert result["success"] is True
    assert [item["id"] for item in result["playback_plan"]] == ["early", "later"]
    assert result["message"] == "Found Creed. The artist has 2 playable tracks."


def test_orchestrator_add_path_uses_native_queue_item_boundary(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(tmp_path, states=[FakeState("media_player.attic_tv", friendly_name="Attic TV")])
    rt = runtime()

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args[2] == "resolve_media_player"
        return {"success": True, "media_player": "media_player.attic_tv", "media_player_name": "Attic TV", "query": "Jurassic World"}

    async def resolver(*args: Any, **kwargs: Any) -> dict[str, Any]:
        item = {"id": "movie-1", "name": "Jurassic World", "type": "Movie", "year": 2015}
        return {"success": True, "status": "resolved", "intent": "Movie", "query": "Jurassic World", "jellyfin_id": "movie-1", "item": item, "items": [item], "playback_plan": [item]}

    calls: list[tuple[str, str]] = []
    async def add(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((kwargs["item"]["id"], kwargs["media_player"]))
        return {"success": True, "status": "added"}

    monkeypatch.setattr(orchestration, "_action", action)
    monkeypatch.setattr(orchestration, "async_resolve_media_intent", resolver)
    monkeypatch.setattr(orchestration, "async_queue_add_item", add)
    result = run(async_media_orchestrator(hass, rt, query="Jurassic World", media_player="media_player.attic_tv", operation="add", media_type="Movie"))
    assert calls == [("movie-1", "media_player.attic_tv")]
    assert result["success"] is True
    assert result["status"] == "added"
    assert result["message"] == "Added Jurassic World (2015) to the queue for Attic TV."


def test_orchestrator_returns_player_required_without_searching(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(tmp_path)
    rt = runtime()

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args[2] == "resolve_media_player"
        return {"success": False, "reason": "no_player_available", "query": "Jurassic World", "media_type": "Movie"}

    async def resolver(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("resolver must not run without a player")

    monkeypatch.setattr(orchestration, "_action", action)
    monkeypatch.setattr(orchestration, "async_resolve_media_intent", resolver)
    result = run(async_media_orchestrator(hass, rt, query="Jurassic World", media_type="Movie"))
    assert result["success"] is False
    assert result["status"] == "media_player_required"
    assert result["message"] == "Which media player would you like me to use?"


def test_resume_pending_queue_request_dispatches_native_queue_command(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(tmp_path)
    rt = runtime()

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args[2] == "resume_media_request"
        return {"success": True, "operation": "queue_status", "media_player": "media_player.attic_tv", "media_player_name": "Attic TV"}

    async def queue_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["operation"] == "queue_status"
        assert kwargs["media_player"] == "media_player.attic_tv"
        return {"success": True, "status": "ok", "message": "Queue ready"}

    monkeypatch.setattr(orchestration, "_action", action)
    monkeypatch.setattr(orchestration, "async_queue_command", queue_command)
    result = run(orchestration.async_resume_pending_media_request(hass, rt, media_player="Attic TV"))
    assert result["message"] == "Queue ready"


def test_resume_pending_media_request_restores_full_request_context(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(tmp_path)
    rt = runtime()

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "success": True,
            "operation": "play",
            "media_player": "media_player.basement_tv",
            "media_player_name": "Basement TV",
            "query": "Where Is Everybody",
            "media_type": "Episode",
            "artist": "",
            "year": "",
            "series": "The Twilight Zone",
            "season": 1,
            "episode": 1,
        }

    captured: dict[str, Any] = {}
    async def orchestrator(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"success": True, "status": "playing", "message": "Playing episode"}

    monkeypatch.setattr(orchestration, "_action", action)
    monkeypatch.setattr(orchestration, "async_media_orchestrator", orchestrator)
    result = run(orchestration.async_resume_pending_media_request(hass, rt, media_player="Basement TV"))
    assert result["success"] is True
    assert captured["query"] == "Where Is Everybody"
    assert captured["media_player"] == "media_player.basement_tv"
    assert captured["media_player_display_name"] == "Basement TV"
    assert captured["series"] == "The Twilight Zone"
    assert captured["season"] == 1
    assert captured["episode"] == 1
