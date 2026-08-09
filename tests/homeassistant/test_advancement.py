"""Tests for native automatic queue advancement."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tests.homeassistant.ha_stubs import FakeEntry, FakeHass, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist.advancement import (
    _async_process_completion,
    _estimate_playback_percent,
    _extract_jellyfin_id,
    async_setup_queue_advancement,
)
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime
from custom_components.jellyfin_assist.search import CatalogManager


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def runtime(queue_client: Any, *, targets: tuple[str, ...] = ("media_player.example",)) -> JellyfinAssistRuntime:
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
        playback_targets=targets,
        queue_client=queue_client,
    )


def media_states(*, position: float = 95, duration: float = 100, content_id: str = "/Videos/abc123/") -> tuple[Any, Any]:
    started = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    updated = started + timedelta(seconds=position)
    ended = started + timedelta(seconds=duration)
    old_state = SimpleNamespace(
        entity_id="media_player.example",
        state="playing",
        last_changed=started,
        attributes={
            "friendly_name": "Example Player",
            "media_title": "Example Item",
            "media_position": position,
            "media_duration": duration,
            "media_position_updated_at": updated,
            "media_content_id": content_id,
        },
    )
    new_state = SimpleNamespace(
        entity_id="media_player.example",
        state="idle",
        last_changed=ended,
        attributes={},
    )
    return old_state, new_state


def test_completion_estimate_preserves_automation_extrapolation() -> None:
    old_state, new_state = media_states(position=90, duration=100)

    assert _estimate_playback_percent(old_state, new_state) == 100.0


def test_completion_estimate_rejects_short_playback() -> None:
    old_state, new_state = media_states(position=20, duration=100)
    new_state.last_changed = old_state.last_changed + timedelta(seconds=25)

    assert _estimate_playback_percent(old_state, new_state) == 25.0


def test_extract_jellyfin_id_accepts_video_and_audio_urls() -> None:
    assert _extract_jellyfin_id("http://host/Videos/abc123/stream") == "abc123"
    assert _extract_jellyfin_id("/Audio/def456/") == "def456"
    assert _extract_jellyfin_id("https://example.invalid/nope") == ""


def test_setup_tracks_all_configured_playback_targets(tmp_path: Path) -> None:
    hass = FakeHass(tmp_path)
    entry = FakeEntry("entry", {})
    rt = runtime(object(), targets=("media_player.one", "media_player.two"))

    async_setup_queue_advancement(hass, entry, rt)

    assert hass.tracked_state_changes[0][0] == ("media_player.one", "media_player.two")
    assert len(entry.unload_callbacks) == 1
    assert rt.queue_advancement_targets == ("media_player.one", "media_player.two")


def test_confirmed_completion_advances_and_starts_next_item(tmp_path: Path, monkeypatch: Any) -> None:
    class QueueClient:
        def __init__(self) -> None:
            self.next_calls = 0

        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {"id": "abc123", "name": "Example Item"},
                },
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            self.next_calls += 1
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {"id": "next456", "name": "Next Item", "type": "Audio"},
                    "upcoming_count": 1,
                    "completed": {"id": "abc123"},
                },
                "headers": {},
            }

    queue = QueueClient()
    rt = runtime(queue)
    hass = FakeHass(tmp_path)

    played: list[dict[str, Any]] = []

    async def play(*args: Any, **kwargs: Any) -> dict[str, Any]:
        played.append(dict(kwargs))
        return {"success": True, "status": "playing"}

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.advancement.async_play_item",
        play,
    )
    old_state, new_state = media_states()

    run(
        _async_process_completion(
            hass,
            rt,
            player="media_player.example",
            old_state=old_state,
            new_state=new_state,
        )
    )

    assert queue.next_calls == 1
    assert played == [{
        "item": {"id": "next456", "name": "Next Item", "type": "Audio"},
        "media_player": "media_player.example",
    }]
    assert rt.last_queue_advancement["status"] == "playing_next"


def test_rejected_completion_does_not_advance(tmp_path: Path) -> None:
    class QueueClient:
        def __init__(self) -> None:
            self.next_calls = 0

        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {"id": "abc123", "name": "Example Item"},
                },
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            self.next_calls += 1
            raise AssertionError("must not advance")

    queue = QueueClient()
    rt = runtime(queue)
    hass = FakeHass(tmp_path)
    old_state, new_state = media_states(position=20, duration=100)
    new_state.last_changed = old_state.last_changed + timedelta(seconds=25)

    run(
        _async_process_completion(
            hass,
            rt,
            player="media_player.example",
            old_state=old_state,
            new_state=new_state,
        )
    )

    assert queue.next_calls == 0
    assert rt.last_queue_advancement["status"] == "completion_rejected"


def test_normal_queue_completion_is_silent(tmp_path: Path) -> None:
    class QueueClient:
        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {"success": True, "current": {"id": "abc123"}},
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": None,
                    "upcoming_count": 0,
                    "completed": {"id": "abc123"},
                },
                "headers": {},
            }

    rt = runtime(QueueClient())
    hass = FakeHass(tmp_path)
    old_state, new_state = media_states()

    run(
        _async_process_completion(
            hass,
            rt,
            player="media_player.example",
            old_state=old_state,
            new_state=new_state,
        )
    )

    assert hass.services.calls == []
    assert rt.last_queue_advancement["status"] == "queue_complete"
