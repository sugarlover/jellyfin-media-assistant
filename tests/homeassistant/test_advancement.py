"""Tests for native automatic queue advancement."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tests.homeassistant.ha_stubs import (
    FakeEntry,
    FakeHass,
    install_homeassistant_stubs,
)

install_homeassistant_stubs()

from custom_components.jellyfin_assist.advancement import (
    _async_process_completion,
    _estimate_playback_percent,
    _extract_jellyfin_id,
    _session_playback_percent,
    _update_playback_session,
    async_setup_queue_advancement,
)
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime
from custom_components.jellyfin_assist.search import CatalogManager


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def runtime(
    queue_client: Any,
    *,
    targets: tuple[str, ...] = ("media_player.example",),
) -> JellyfinAssistRuntime:
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


def media_states(
    *,
    position: float = 95,
    duration: float = 100,
    content_id: str = "/Videos/abc123/",
) -> tuple[Any, Any]:
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


def metadata_poor_states(
    *,
    played_seconds: float = 100,
) -> tuple[Any, Any]:
    """Return HAVPE-like states with no playback metadata."""

    started = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=played_seconds)

    old_state = SimpleNamespace(
        entity_id="media_player.example",
        state="playing",
        last_changed=started,
        attributes={
            "friendly_name": "Home Assistant Voice Media Player",
        },
    )
    new_state = SimpleNamespace(
        entity_id="media_player.example",
        state="idle",
        last_changed=ended,
        attributes={
            "friendly_name": "Home Assistant Voice Media Player",
        },
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


def test_session_playback_percent_uses_jellyfin_runtime() -> None:
    session = {
        "duration_seconds": 200.0,
        "accumulated_playing_seconds": 190.0,
    }

    assert _session_playback_percent(session) == 95.0


def test_session_playback_percent_rejects_missing_runtime() -> None:
    session = {
        "duration_seconds": 0.0,
        "accumulated_playing_seconds": 200.0,
    }

    assert _session_playback_percent(session) == 0.0


def test_session_playback_percent_caps_at_one_hundred() -> None:
    session = {
        "duration_seconds": 100.0,
        "accumulated_playing_seconds": 150.0,
    }

    assert _session_playback_percent(session) == 100.0


def test_playback_session_counts_only_actual_playing_time() -> None:
    rt = runtime(object())

    started = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    paused_at = started + timedelta(seconds=60)
    resumed_at = started + timedelta(seconds=300)
    ended_at = resumed_at + timedelta(seconds=125)

    rt.playback_sessions["media_player.example"] = {
        "item_id": "abc123",
        "requested_item_id": "abc123",
        "duration_seconds": 185.0,
        "accumulated_playing_seconds": 0.0,
        "playing_started_at": started,
    }

    playing_state = SimpleNamespace(
        state="playing",
        last_changed=started,
        attributes={},
    )
    paused_state = SimpleNamespace(
        state="paused",
        last_changed=paused_at,
        attributes={},
    )
    resumed_state = SimpleNamespace(
        state="playing",
        last_changed=resumed_at,
        attributes={},
    )
    idle_state = SimpleNamespace(
        state="idle",
        last_changed=ended_at,
        attributes={},
    )

    _update_playback_session(
        rt,
        player="media_player.example",
        old_state=playing_state,
        new_state=paused_state,
    )

    assert (
        rt.playback_sessions["media_player.example"][
            "accumulated_playing_seconds"
        ]
        == 60.0
    )
    assert (
        rt.playback_sessions["media_player.example"]["playing_started_at"]
        is None
    )

    _update_playback_session(
        rt,
        player="media_player.example",
        old_state=paused_state,
        new_state=resumed_state,
    )

    assert (
        rt.playback_sessions["media_player.example"]["playing_started_at"]
        == resumed_at
    )

    _update_playback_session(
        rt,
        player="media_player.example",
        old_state=resumed_state,
        new_state=idle_state,
    )

    session = rt.playback_sessions["media_player.example"]

    assert session["accumulated_playing_seconds"] == 185.0
    assert session["playing_started_at"] is None
    assert _session_playback_percent(session) == 100.0


def test_setup_tracks_all_configured_playback_targets(
    tmp_path: Path,
) -> None:
    hass = FakeHass(tmp_path)
    entry = FakeEntry("entry", {})
    rt = runtime(
        object(),
        targets=("media_player.one", "media_player.two"),
    )

    async_setup_queue_advancement(hass, entry, rt)

    assert hass.tracked_state_changes[0][0] == (
        "media_player.one",
        "media_player.two",
    )
    assert len(entry.unload_callbacks) == 2
    assert rt.queue_advancement_targets == (
        "media_player.one",
        "media_player.two",
    )


def test_confirmed_completion_advances_and_starts_next_item(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    class QueueClient:
        def __init__(self) -> None:
            self.next_calls = 0

        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "abc123",
                        "name": "Example Item",
                    },
                },
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            self.next_calls += 1
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "next456",
                        "name": "Next Item",
                        "type": "Audio",
                    },
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
        return {
            "success": True,
            "status": "playing",
        }

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
    assert played == [
        {
            "item": {
                "id": "next456",
                "name": "Next Item",
                "type": "Audio",
            },
            "media_player": "media_player.example",
        }
    ]
    assert rt.last_queue_advancement["status"] == "playing_next"
    assert (
        rt.last_queue_advancement["completion_method"]
        == "player_metadata"
    )


def test_metadata_poor_player_completion_advances_from_tracked_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """HAVPE-like players advance when tracked runtime confirms completion."""

    class QueueClient:
        def __init__(self) -> None:
            self.next_calls = 0

        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "abc123",
                        "name": "Example Item",
                    },
                },
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            self.next_calls += 1
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "next456",
                        "name": "Next Item",
                        "type": "Audio",
                    },
                    "upcoming_count": 1,
                    "completed": {"id": "abc123"},
                },
                "headers": {},
            }

    queue = QueueClient()
    rt = runtime(queue)
    hass = FakeHass(tmp_path)

    rt.playback_sessions["media_player.example"] = {
        "item_id": "abc123",
        "requested_item_id": "abc123",
        "duration_seconds": 100.0,
        "accumulated_playing_seconds": 100.0,
        "playing_started_at": None,
    }

    played: list[dict[str, Any]] = []

    async def play(*args: Any, **kwargs: Any) -> dict[str, Any]:
        played.append(dict(kwargs))
        return {
            "success": True,
            "status": "playing",
        }

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.advancement.async_play_item",
        play,
    )

    old_state, new_state = metadata_poor_states()

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
    assert played == [
        {
            "item": {
                "id": "next456",
                "name": "Next Item",
                "type": "Audio",
            },
            "media_player": "media_player.example",
        }
    ]
    assert rt.last_queue_advancement["status"] == "playing_next"
    assert (
        rt.last_queue_advancement["completion_method"]
        == "tracked_session"
    )
    assert "media_player.example" not in rt.playback_sessions


def test_metadata_poor_player_early_stop_does_not_advance(
    tmp_path: Path,
) -> None:
    """Stopping an HAVPE-like player early must remain Stop, not Next."""

    class QueueClient:
        def __init__(self) -> None:
            self.next_calls = 0

        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "abc123",
                        "name": "Example Item",
                    },
                },
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            self.next_calls += 1
            raise AssertionError("must not advance")

    queue = QueueClient()
    rt = runtime(queue)
    hass = FakeHass(tmp_path)

    rt.playback_sessions["media_player.example"] = {
        "item_id": "abc123",
        "requested_item_id": "abc123",
        "duration_seconds": 100.0,
        "accumulated_playing_seconds": 25.0,
        "playing_started_at": None,
    }

    old_state, new_state = metadata_poor_states(
        played_seconds=25,
    )

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
    assert (
        rt.last_queue_advancement["session_playback_percent"]
        == 25.0
    )
    assert (
        rt.last_queue_advancement["session_item_id"]
        == "abc123"
    )
    assert "media_player.example" not in rt.playback_sessions


def test_metadata_poor_player_stale_item_does_not_advance(
    tmp_path: Path,
) -> None:
    """A completed stale session must not advance a different queue item."""

    class QueueClient:
        def __init__(self) -> None:
            self.next_calls = 0

        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "abc123",
                        "name": "Current Item",
                    },
                },
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            self.next_calls += 1
            raise AssertionError("must not advance")

    queue = QueueClient()
    rt = runtime(queue)
    hass = FakeHass(tmp_path)

    rt.playback_sessions["media_player.example"] = {
        "item_id": "stale999",
        "requested_item_id": "stale999",
        "duration_seconds": 100.0,
        "accumulated_playing_seconds": 100.0,
        "playing_started_at": None,
    }

    old_state, new_state = metadata_poor_states()

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
    assert (
        rt.last_queue_advancement["session_playback_percent"]
        == 100.0
    )
    assert (
        rt.last_queue_advancement["session_item_id"]
        == "stale999"
    )
    assert (
        rt.last_queue_advancement["queue_current_id"]
        == "abc123"
    )
    assert "media_player.example" not in rt.playback_sessions


def test_tracked_session_does_not_override_conflicting_player_metadata(
    tmp_path: Path,
) -> None:
    """Fallback must not override metadata that identifies another item."""

    class QueueClient:
        def __init__(self) -> None:
            self.next_calls = 0

        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "abc123",
                        "name": "Current Item",
                    },
                },
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            self.next_calls += 1
            raise AssertionError("must not advance")

    queue = QueueClient()
    rt = runtime(queue)
    hass = FakeHass(tmp_path)

    rt.playback_sessions["media_player.example"] = {
        "item_id": "abc123",
        "requested_item_id": "abc123",
        "duration_seconds": 100.0,
        "accumulated_playing_seconds": 100.0,
        "playing_started_at": None,
    }

    old_state, new_state = media_states(
        position=0,
        duration=100,
        content_id="/Audio/wrong999/",
    )
    new_state.last_changed = old_state.last_changed

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
    assert rt.last_queue_advancement["jellyfin_id"] == "wrong999"
    assert "media_player.example" not in rt.playback_sessions


def test_rejected_completion_does_not_advance(
    tmp_path: Path,
) -> None:
    class QueueClient:
        def __init__(self) -> None:
            self.next_calls = 0

        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "abc123",
                        "name": "Example Item",
                    },
                },
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            self.next_calls += 1
            raise AssertionError("must not advance")

    queue = QueueClient()
    rt = runtime(queue)
    hass = FakeHass(tmp_path)

    old_state, new_state = media_states(
        position=20,
        duration=100,
    )
    new_state.last_changed = (
        old_state.last_changed
        + timedelta(seconds=25)
    )

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


def test_normal_queue_completion_is_silent(
    tmp_path: Path,
) -> None:
    class QueueClient:
        async def async_get(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "abc123",
                    },
                },
                "headers": {},
            }

        async def async_next(self, player: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": None,
                    "upcoming_count": 0,
                    "completed": {
                        "id": "abc123",
                    },
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
    assert (
        rt.last_queue_advancement["completion_method"]
        == "player_metadata"
    )


class RecordingPlayingClient:
    """Standalone client whose async_post_playing_items records calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def async_post_playing_items(
        self,
        *,
        item_id: str,
        position_ticks: int,
        is_paused: bool,
        device_id: str = "jellyfin-assist",
    ) -> None:
        self.calls.append(
            {
                "item_id": item_id,
                "position_ticks": position_ticks,
                "is_paused": is_paused,
                "device_id": device_id,
            }
        )


def runtime_with_client(client: Any) -> JellyfinAssistRuntime:
    async def loader() -> Any:
        raise AssertionError("not used")

    return JellyfinAssistRuntime(
        client=client,  # type: ignore[arg-type]
        catalog_manager=CatalogManager(
            snapshot_loader=loader,
            requested_types=["Movie"],
            cache_identity="server:user",
            cache_store=None,
        ),
        connection_info=None,
        playback_targets=("media_player.example",),
        queue_client=object(),
    )


def _session(
    *,
    duration_seconds: float,
    accumulated_playing_seconds: float,
    playing_started_at: Any = None,
) -> dict[str, Any]:
    return {
        "item_id": "abc123",
        "requested_item_id": "abc123",
        "duration_seconds": duration_seconds,
        "accumulated_playing_seconds": accumulated_playing_seconds,
        "playing_started_at": playing_started_at,
    }


def test_write_sync_on_pause_posts_tracked_position(tmp_path: Path) -> None:
    from custom_components.jellyfin_assist.advancement import (
        _async_write_sync_position,
    )

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.playback_sessions["media_player.example"] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=60.0,
    )
    hass = FakeHass(tmp_path)

    run(
        _async_write_sync_position(
            hass,
            rt,
            player="media_player.example",
            is_paused=True,
        )
    )

    assert client.calls == [
        {
            "item_id": "abc123",
            # 60s * 10_000 ticks/sec * 100 nano ticks
            "position_ticks": 60.0 * 10_000 * 100,
            "is_paused": True,
            "device_id": "media_player.example",
        }
    ]


def test_write_sync_posts_live_in_progress_seconds_while_playing(
    tmp_path: Path,
) -> None:
    from custom_components.jellyfin_assist.advancement import (
        _async_write_sync_position,
    )

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    # Set playing_started_at 90s in the past so the live-elapsed branch
    # resolves to 90s (int() truncates the sub-second drift).
    started = datetime.now(timezone.utc) - timedelta(seconds=90)
    rt.playback_sessions["media_player.example"] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=0.0,
        playing_started_at=started,
    )
    hass = FakeHass(tmp_path)

    run(
        _async_write_sync_position(
            hass,
            rt,
            player="media_player.example",
            is_paused=False,
        )
    )

    assert client.calls == [
        {
            "item_id": "abc123",
            # 90s of live elapsed * 10_000 ticks/sec * 100 nano ticks
            "position_ticks": 90 * 10_000 * 100,
            "is_paused": False,
            "device_id": "media_player.example",
        }
    ]


def test_write_sync_skips_position_past_completion_threshold(
    tmp_path: Path,
) -> None:
    from custom_components.jellyfin_assist.advancement import (
        _async_write_sync_position,
    )

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    # 100s out of 100s = 100% -> past the 95% threshold, must not write.
    rt.playback_sessions["media_player.example"] = _session(
        duration_seconds=100.0,
        accumulated_playing_seconds=100.0,
    )
    hass = FakeHass(tmp_path)

    run(
        _async_write_sync_position(
            hass,
            rt,
            player="media_player.example",
            is_paused=True,
        )
    )

    assert client.calls == []


def test_write_sync_skips_when_no_session(tmp_path: Path) -> None:
    from custom_components.jellyfin_assist.advancement import (
        _async_write_sync_position,
    )

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    hass = FakeHass(tmp_path)

    run(
        _async_write_sync_position(
            hass,
            rt,
            player="media_player.example",
            is_paused=True,
        )
    )

    assert client.calls == []


def test_periodic_write_sync_writes_only_players_that_are_playing(
    tmp_path: Path,
) -> None:
    from custom_components.jellyfin_assist.advancement import (
        _async_periodic_write_sync_tasks,
    )

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.playback_sessions["media_player.example"] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=90.0,
    )
    hass = FakeHass(tmp_path)
    hass.states.set("media_player.example", "playing", {})

    run(_async_periodic_write_sync_tasks(hass, rt))

    assert client.calls == [
        {
            "item_id": "abc123",
            "position_ticks": 90.0 * 10_000 * 100,
            "is_paused": False,
            "device_id": "media_player.example",
        }
    ]


def test_periodic_write_sync_skips_paused_players(
    tmp_path: Path,
) -> None:
    from custom_components.jellyfin_assist.advancement import (
        _async_periodic_write_sync_tasks,
    )

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.playback_sessions["media_player.example"] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=90.0,
    )
    hass = FakeHass(tmp_path)
    hass.states.set("media_player.example", "paused", {})

    run(_async_periodic_write_sync_tasks(hass, rt))

    assert client.calls == []


def test_setup_tracks_periodic_write_sync_with_keyword_args(
    tmp_path: Path,
) -> None:
    """Regression guard for the HA ``async_track_time_interval`` argument order.

    The HA core build deployed on this host exposes
    ``async_track_time_interval(hass, action, interval)`` — the reverse of
    upstream's ``async_track_time_interval(hass, interval, action)``. A
    positional call therefore drops ``timedelta(...)`` into the ``action``
    slot and the callback into ``interval``, which aborts entry setup with
    ``'function' object has no attribute 'total_seconds'``. The call site
    must use keyword args so it is immune to either parameter order.
    """
    from unittest.mock import patch

    from custom_components.jellyfin_assist.advancement import (
        PLAYBACK_WRITESYNC_INTERVAL_SECONDS,
    )

    hass = FakeHass(tmp_path)
    entry = FakeEntry("entry", {})
    rt = runtime(object())

    with patch(
        "custom_components.jellyfin_assist.advancement.async_track_time_interval"
    ) as tracker:
        async_setup_queue_advancement(hass, entry, rt)

    assert tracker.call_count == 1
    call = tracker.call_args
    # Only ``hass`` may be passed positionally; interval/action must be
    # keyword args so the call is immune to the parameter order.
    assert call.args == (hass,)
    interval = call.kwargs["interval"]
    action = call.kwargs["action"]
    # interval must be the timedelta and action the callback — not swapped.
    assert isinstance(interval, timedelta)
    assert interval == timedelta(seconds=PLAYBACK_WRITESYNC_INTERVAL_SECONDS)
    assert not isinstance(action, timedelta)
    assert callable(action)