"""Tests for native high-level queue control replacing YAML scripts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from tests.homeassistant.ha_stubs import FakeEntry, FakeHass, FakeState, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist import queue_control
from custom_components.jellyfin_assist.queue_control import (
    async_execute_queue_operation,
    async_queue_command,
)
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime
from custom_components.jellyfin_assist.search import CatalogManager
from custom_components.jellyfin_assist.services import async_register_services


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
        default_media_player="media_player.attic_tv",
        playback_targets=("media_player.attic_tv", "media_player.basement_tv"),
        queue_client=queue_client,
    )


class Queue:
    def __init__(self) -> None:
        self.body = {
            "success": True,
            "status": "ok",
            "count": 2,
            "current_index": 0,
            "current": {"id": "song1", "name": "Bullets", "type": "Audio", "artist": "Creed", "album": "Weathered"},
            "previous": None,
            "last_completed": None,
            "next": {"id": "song2", "name": "Freedom Fighter", "type": "Audio", "artist": "Creed", "album": "Weathered"},
            "items": [
                {"id": "song1", "name": "Bullets", "type": "Audio", "artist": "Creed", "album": "Weathered"},
                {"id": "song2", "name": "Freedom Fighter", "type": "Audio", "artist": "Creed", "album": "Weathered"},
            ],
            "history": [],
            "completed_count": 0,
            "upcoming_count": 1,
            "repeat_item": False,
            "repeat_queue": False,
        }

    async def async_get(self, player: str) -> dict[str, Any]:
        return {"status": 200, "content": dict(self.body), "headers": {}}

    async def async_next(self, player: str) -> dict[str, Any]:
        body = dict(self.body)
        body.update(
            {
                "status": "advanced",
                "current_index": 1,
                "current": body["next"],
                "next": None,
                "completed": body["current"],
                "last_completed": body["current"],
                "completed_count": 1,
                "upcoming_count": 0,
            }
        )
        return {"status": 200, "content": body, "headers": {}}

    async def async_shuffle(self, player: str) -> dict[str, Any]:
        body = dict(self.body)
        body.update({"status": "unchanged", "shuffled_count": 0, "order_changed": False})
        return {"status": 200, "content": body, "headers": {}}

    async def async_clear(self, player: str) -> dict[str, Any]:
        self.body = {"success": True, "status": "cleared", "count": 0, "current": None, "items": [], "history": [], "completed_count": 0, "upcoming_count": 0, "repeat_item": False, "repeat_queue": False}
        return {"status": 200, "content": dict(self.body), "headers": {}}

    async def async_settings(self, player: str, *, repeat_item: bool, repeat_queue: bool) -> dict[str, Any]:
        self.body["repeat_item"] = repeat_item
        self.body["repeat_queue"] = repeat_queue
        body = dict(self.body)
        body["status"] = "settings_updated"
        return {"status": 200, "content": body, "headers": {}}


def test_whats_playing_preserves_spoken_contract(tmp_path: Path) -> None:
    queue = Queue()
    hass = FakeHass(tmp_path, states=[FakeState("media_player.attic_tv", friendly_name="Attic TV", state="playing")])
    result = run(async_execute_queue_operation(hass, runtime(queue), operation="whats_playing", media_player="media_player.attic_tv"))

    assert result["success"] is True
    assert result["status"] == "playing"
    assert result["speak"] == "Bullets by Creed from Weathered is playing on Attic TV."


def test_next_plays_new_current_item(tmp_path: Path, monkeypatch: Any) -> None:
    queue = Queue()
    hass = FakeHass(tmp_path, states=[FakeState("media_player.attic_tv", friendly_name="Attic TV", state="playing")])

    async def play(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["item"]["id"] == "song2"
        return {"success": True, "status": "playing"}

    monkeypatch.setattr(queue_control, "async_play_item", play)
    result = run(async_execute_queue_operation(hass, runtime(queue), operation="queue_next", media_player="media_player.attic_tv"))

    assert result["success"] is True
    assert result["status"] == "playing"
    assert result["speak"] == "Playing Freedom Fighter by Creed on Attic TV."


def test_repeat_toggle_updates_queue_service(tmp_path: Path) -> None:
    queue = Queue()
    hass = FakeHass(tmp_path, states=[FakeState("media_player.attic_tv", friendly_name="Attic TV")])
    result = run(async_execute_queue_operation(hass, runtime(queue), operation="repeat_item_toggle", media_player="media_player.attic_tv"))

    assert result["success"] is True
    assert result["status"] == "repeat_item_on"
    assert result["repeat_item"] is True
    assert result["repeat_queue"] is False


def test_queue_command_uses_native_player_resolution_and_display_name(tmp_path: Path) -> None:
    queue = Queue()
    rt = runtime(queue)
    entry = FakeEntry("entry", {})
    entry.runtime_data = rt
    hass = FakeHass(
        tmp_path,
        entries=[entry],
        states=[
            FakeState("media_player.attic_tv", friendly_name="Odd Friendly Name", state="playing"),
            FakeState("media_player.basement_tv", friendly_name="Basement TV", state="idle"),
        ],
    )
    run(async_register_services(hass))

    result = run(
        async_queue_command(
            hass,
            rt,
            operation="whats_playing",
            media_player="media_player.attic_tv",
        )
    )

    assert result["success"] is True
    assert result["media_player"] == "media_player.attic_tv"
    assert result["media_player_name"] == "Attic TV"
    assert result["speak"].endswith("on Attic TV.")
