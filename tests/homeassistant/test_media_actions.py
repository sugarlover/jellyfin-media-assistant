"""Tests for native high-level media actions replacing YAML helper scripts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from tests.homeassistant.ha_stubs import FakeHass, FakeState, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist import media_actions
from custom_components.jellyfin_assist.media_actions import (
    async_play_item,
    async_prepare_play_session,
    async_queue_add_item,
)
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime
from custom_components.jellyfin_assist.search import CatalogManager


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def runtime(queue_client: Any) -> JellyfinAssistRuntime:
    async def loader() -> Any:
        raise AssertionError("not used")

    return JellyfinAssistRuntime(
        client=object(),  # type: ignore[arg-type]
        catalog_manager=CatalogManager(
            snapshot_loader=loader,
            requested_types=["Movie"],
            cache_identity="server:user",
            cache_store=None,
        ),
        connection_info=None,
        queue_client=queue_client,
    )


def test_play_item_preserves_playback_response_contract(tmp_path: Path, monkeypatch: Any) -> None:
    hass = FakeHass(
        tmp_path,
        states=[FakeState("media_player.attic_tv", friendly_name="Attic TV", state="idle")],
    )
    rt = runtime(object())

    async def native_play(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["target_entity_id"] == "media_player.attic_tv"
        assert kwargs["item_id"] == "movie1"
        return {"success": True, "status": "playing"}

    monkeypatch.setattr(media_actions, "async_play_on_chromecast", native_play)
    result = run(
        async_play_item(
            hass,
            rt,
            item={"id": "movie1", "name": "Example Movie", "type": "Movie", "year": 2026},
            media_player="media_player.attic_tv",
        )
    )

    assert result["success"] is True
    assert result["status"] == "playing"
    assert result["message"] == "Playing Example Movie (2026) on Attic TV."
    assert result["item_id"] == "movie1"


def test_prepare_play_session_disables_both_repeat_modes(tmp_path: Path) -> None:
    class Queue:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def async_settings(self, player: str, *, repeat_item: bool, repeat_queue: bool) -> dict[str, Any]:
            self.calls.append({"player": player, "repeat_item": repeat_item, "repeat_queue": repeat_queue})
            return {
                "status": 200,
                "content": {"success": True, "repeat_item": False, "repeat_queue": False},
                "headers": {},
            }

    queue = Queue()
    hass = FakeHass(tmp_path, states=[FakeState("media_player.attic_tv", friendly_name="Attic TV")])
    result = run(async_prepare_play_session(hass, runtime(queue), media_player="media_player.attic_tv"))

    assert queue.calls == [{"player": "media_player.attic_tv", "repeat_item": False, "repeat_queue": False}]
    assert result["success"] is True
    assert result["status"] == "ready"
    assert result["repeat_item"] is False
    assert result["repeat_queue"] is False


def test_queue_add_item_never_maps_audio_to_episode_fields(tmp_path: Path) -> None:
    class Queue:
        def __init__(self) -> None:
            self.added: dict[str, Any] | None = None

        async def async_get(self, player: str) -> dict[str, Any]:
            return {"status": 200, "content": {"success": True, "count": 0, "current": None}, "headers": {}}

        async def async_add(self, player: str, item: dict[str, Any]) -> dict[str, Any]:
            self.added = dict(item)
            return {
                "status": 200,
                "content": {"success": True, "status": "added", "count": 1, "current": dict(item)},
                "headers": {},
            }

    queue = Queue()
    hass = FakeHass(tmp_path, states=[FakeState("media_player.attic_tv", friendly_name="Attic TV")])
    result = run(
        async_queue_add_item(
            hass,
            runtime(queue),
            item={
                "id": "song1",
                "name": "Example Song",
                "type": "Audio",
                "artist_name": "Example Artist",
                "album": "Example Album",
                "track_number": 7,
            },
            media_player="media_player.attic_tv",
        )
    )

    assert result["success"] is True
    assert queue.added is not None
    assert queue.added["artist"] == "Example Artist"
    assert queue.added["album"] == "Example Album"
    assert queue.added["season"] == ""
    assert queue.added["episode"] == ""
