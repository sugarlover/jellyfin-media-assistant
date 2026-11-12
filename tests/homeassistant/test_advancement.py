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
    _build_queue_advancement_handler,
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
    # Three unload callbacks: D4 dynamic-listener release + state-change
    # unsubscribe + periodic write sync.
    assert len(entry.unload_callbacks) == 3
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
        self.auth_refresh: Any = None

    async def async_post_playing_items(
        self,
        *,
        item_id: str,
        position_ticks: int,
        is_paused: bool,
        device_id: str = "jellyfin-assist",
        _async_auth_refresh: Any = None,
    ) -> None:
        self.auth_refresh = _async_auth_refresh
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
            # 60s * 10_000_000 ticks/sec
            "position_ticks": 60.0 * 10_000_000,
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
            # 90s of live elapsed * 10_000_000 ticks/sec
            "position_ticks": 90 * 10_000_000,
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
            "position_ticks": 90.0 * 10_000_000,
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


def test_write_sync_passes_auth_refresh_to_client(tmp_path: Path) -> None:
    """The position write must hand the runtime's reauth trigger to the
    client so api.py can mint a fresh token on a 401 and retry."""
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

    # The callback wired into the write is the runtime's reauth trigger.
    assert client.auth_refresh is not None

    run(client.auth_refresh())
    # It is a coroutine bound to the runtime.
    assert client.calls[0]["item_id"] == "abc123"


def test_runtime_trigger_reauth_starts_config_entry_reauth(
    tmp_path: Path,
) -> None:
    """runtime.async_trigger_reauth must call ConfigEntry.async_start_reauth
    (the HA reauth flow) when the entry+hass are bound; a failure must be
    swallowed, never raising into the sync loop."""
    from custom_components.jellyfin_assist.advancement import (
        _async_write_sync_position,
    )

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    entry = FakeEntry("entry", {"server_url": "http://host", "api_key": "k"})
    rt.async_bind_entry(entry, object())
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

    # Fire the refresh callback exactly like api.py does on a 401.
    run(client.auth_refresh())

    assert entry.reauth_triggered is True


class SpyBackgroundEntry(FakeEntry):
    """FakeEntry variant that keeps background coroutines alive so tests
    can drive them and assert the write actually fires (FakeEntry closes
    them immediately)."""

    def async_create_background_task(
        self,
        hass: Any,
        coro: Any,
        name: str,
    ) -> None:
        self.background_tasks.append((name, coro))


def _drive_state_change(
    hass: FakeHass,
    old_state: Any,
    new_state: Any,
) -> None:
    """Invoke the registered state-change action with a minimal event."""

    action = hass.tracked_state_changes[0][1]
    event = SimpleNamespace(
        data={
            "entity_id": "media_player.example",
            "old_state": old_state,
            "new_state": new_state,
        }
    )
    action(event)


def _drive_background_tasks(entry: SpyBackgroundEntry) -> None:
    """Drive and drain every recorded background coroutine."""

    for _name, coro in entry.background_tasks:
        run(coro)


def test_final_write_fires_on_off(tmp_path: Path) -> None:
    """D3: off transition fires a final write (is_paused=True) before the
    session is popped."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.playback_sessions["media_player.example"] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=60.0,
    )
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    async_setup_queue_advancement(hass, entry, rt)

    old_state = SimpleNamespace(
        entity_id="media_player.example",
        state="playing",
        last_changed=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
        attributes={},
    )
    new_state = SimpleNamespace(
        entity_id="media_player.example",
        state="off",
        last_changed=datetime(2026, 8, 8, 12, 1, tzinfo=timezone.utc),
        attributes={},
    )

    _drive_state_change(hass, old_state, new_state)

    # Session popped on off.
    assert "media_player.example" not in rt.playback_sessions
    # A play-sync background task was scheduled.
    assert any(
        "play sync" in name for name, _coro in entry.background_tasks
    )

    # Drive the tasks: the final write fires with the freshly-updated
    # position. _update_playback_session folded in the 60s transition
    # delta (transition_at - old_state.last_changed) before the snapshot,
    # so accumulated = 60 + 60 = 120s, is_paused=True.
    _drive_background_tasks(entry)
    assert client.calls == [
        {
            "item_id": "abc123",
            "position_ticks": 120.0 * 10_000_000,
            "is_paused": True,
            "device_id": "media_player.example",
        }
    ]


def test_final_write_fires_on_unavailable(tmp_path: Path) -> None:
    """D3: unavailable transition fires a final write before the session
    is popped."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.playback_sessions["media_player.example"] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=45.0,
    )
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    async_setup_queue_advancement(hass, entry, rt)

    old_state = SimpleNamespace(
        entity_id="media_player.example",
        state="playing",
        last_changed=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
        attributes={},
    )
    new_state = SimpleNamespace(
        entity_id="media_player.example",
        state="unavailable",
        last_changed=datetime(2026, 8, 8, 12, 1, tzinfo=timezone.utc),
        attributes={},
    )

    _drive_state_change(hass, old_state, new_state)

    assert "media_player.example" not in rt.playback_sessions
    assert any(
        "play sync" in name for name, _coro in entry.background_tasks
    )

    # _update_playback_session folded in the 60s transition delta before
    # the snapshot, so accumulated = 45 + 60 = 105s, is_paused=True.
    _drive_background_tasks(entry)
    assert client.calls == [
        {
            "item_id": "abc123",
            "position_ticks": 105.0 * 10_000_000,
            "is_paused": True,
            "device_id": "media_player.example",
        }
    ]


def test_final_write_fires_on_non_completion_idle(tmp_path: Path) -> None:
    """D3: a non-completion idle transition (old_state not playing) fires a
    final write before the session is popped."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.playback_sessions["media_player.example"] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=30.0,
    )
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    async_setup_queue_advancement(hass, entry, rt)

    # old_state is NOT playing -> the non-completion idle path.
    old_state = SimpleNamespace(
        entity_id="media_player.example",
        state="paused",
        last_changed=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
        attributes={},
    )
    new_state = SimpleNamespace(
        entity_id="media_player.example",
        state="idle",
        last_changed=datetime(2026, 8, 8, 12, 1, tzinfo=timezone.utc),
        attributes={},
    )

    _drive_state_change(hass, old_state, new_state)

    assert "media_player.example" not in rt.playback_sessions
    assert any(
        "play sync" in name for name, _coro in entry.background_tasks
    )

    _drive_background_tasks(entry)
    assert client.calls == [
        {
            "item_id": "abc123",
            "position_ticks": 30.0 * 10_000_000,
            "is_paused": True,
            "device_id": "media_player.example",
        }
    ]


def test_completing_idle_does_not_double_write(tmp_path: Path) -> None:
    """D3: a completing playing->idle transition routes to the completion
    path, not the final-write path — no play-sync task is scheduled."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.playback_sessions["media_player.example"] = _session(
        duration_seconds=100.0,
        accumulated_playing_seconds=100.0,
    )
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    async_setup_queue_advancement(hass, entry, rt)

    old_state, new_state = media_states()

    _drive_state_change(hass, old_state, new_state)

    # No play-sync task on the completion path.
    assert not any(
        "play sync" in name for name, _coro in entry.background_tasks
    )


# ---------------------------------------------------------------------------
# D4: dynamic listener release for unlisted targets
# ---------------------------------------------------------------------------


class FakeDynamicUnsubscribe:
    """Stand-in for the HA state-change unsubscribe callback."""

    def __init__(self) -> None:
        self.called = 0

    def __call__(self) -> None:
        self.called += 1


def _register_dynamic_listener(
    rt: JellyfinAssistRuntime,
    player: str,
) -> FakeDynamicUnsubscribe:
    """Register a fake dynamic listener for an unlisted target in the
    runtime and return the fake unsubscribe so tests can assert on it."""

    unsubscribe = FakeDynamicUnsubscribe()
    rt.playback_session_listeners[player] = unsubscribe
    return unsubscribe


def _drive_unlisted_state_change(
    hass: FakeHass,
    entry: SpyBackgroundEntry,
    rt: JellyfinAssistRuntime,
    player: str,
    old_state: Any,
    new_state: Any,
) -> None:
    """Drive a state change through the handler built by
    _build_queue_advancement_handler for an unlisted target."""

    handler = _build_queue_advancement_handler(hass, entry, rt)
    event = SimpleNamespace(
        data={
            "entity_id": player,
            "old_state": old_state,
            "new_state": new_state,
        }
    )
    handler(event)


def test_d4_listener_released_on_off(tmp_path: Path) -> None:
    """D4: the dynamic listener is released when the session pops on off."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    player = "media_player.unlisted"
    rt.playback_sessions[player] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=60.0,
    )
    unsubscribe = _register_dynamic_listener(rt, player)
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    old_state = SimpleNamespace(
        entity_id=player,
        state="playing",
        last_changed=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
        attributes={},
    )
    new_state = SimpleNamespace(
        entity_id=player,
        state="off",
        last_changed=datetime(2026, 8, 8, 12, 1, tzinfo=timezone.utc),
        attributes={},
    )

    _drive_unlisted_state_change(
        hass, entry, rt, player, old_state, new_state
    )
    _drive_background_tasks(entry)

    # Session popped.
    assert player not in rt.playback_sessions
    # Listener released exactly once.
    assert player not in rt.playback_session_listeners
    assert unsubscribe.called == 1


def test_d4_listener_released_on_unavailable(tmp_path: Path) -> None:
    """D4: the dynamic listener is released when the session pops on
    unavailable."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    player = "media_player.unlisted"
    rt.playback_sessions[player] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=45.0,
    )
    unsubscribe = _register_dynamic_listener(rt, player)
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    old_state = SimpleNamespace(
        entity_id=player,
        state="playing",
        last_changed=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
        attributes={},
    )
    new_state = SimpleNamespace(
        entity_id=player,
        state="unavailable",
        last_changed=datetime(2026, 8, 8, 12, 1, tzinfo=timezone.utc),
        attributes={},
    )

    _drive_unlisted_state_change(
        hass, entry, rt, player, old_state, new_state
    )
    _drive_background_tasks(entry)

    assert player not in rt.playback_sessions
    assert player not in rt.playback_session_listeners
    assert unsubscribe.called == 1


def test_d4_listener_released_on_non_completion_idle(tmp_path: Path) -> None:
    """D4: the dynamic listener is released when the session pops on a
    non-completion idle (old_state not playing)."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    player = "media_player.unlisted"
    rt.playback_sessions[player] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=30.0,
    )
    unsubscribe = _register_dynamic_listener(rt, player)
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    old_state = SimpleNamespace(
        entity_id=player,
        state="paused",
        last_changed=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
        attributes={},
    )
    new_state = SimpleNamespace(
        entity_id=player,
        state="idle",
        last_changed=datetime(2026, 8, 8, 12, 1, tzinfo=timezone.utc),
        attributes={},
    )

    _drive_unlisted_state_change(
        hass, entry, rt, player, old_state, new_state
    )
    _drive_background_tasks(entry)

    assert player not in rt.playback_sessions
    assert player not in rt.playback_session_listeners
    assert unsubscribe.called == 1


def test_d4_listener_released_on_completion(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """D4: the dynamic listener is released on a confirmed completion
    (playing->idle with a verifiable queue item)."""

    class QueueClient:
        def __init__(self) -> None:
            self.next_calls = 0

        async def async_get(self, pname: str) -> dict[str, Any]:
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {"id": "abc123", "name": "Example Item"},
                },
                "headers": {},
            }

        async def async_next(self, pname: str) -> dict[str, Any]:
            self.next_calls += 1
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

    queue = QueueClient()
    rt = runtime(queue)
    player = "media_player.unlisted"
    rt.playback_sessions[player] = _session(
        duration_seconds=100.0,
        accumulated_playing_seconds=100.0,
    )
    unsubscribe = _register_dynamic_listener(rt, player)
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    old_state, new_state = media_states()
    # Point the states at the unlisted player so the handler's pop site
    # matches the registered listener.
    old_state.entity_id = player
    new_state.entity_id = player

    async def play(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"success": True, "status": "playing"}

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.advancement.async_play_item",
        play,
    )

    # Drive the state change to schedule the completion task.
    _drive_unlisted_state_change(
        hass, entry, rt, player, old_state, new_state
    )
    # Drive the scheduled background completion task.
    _drive_background_tasks(entry)

    # Confirmed completion pops the session and releases the listener.
    assert player not in rt.playback_sessions
    assert player not in rt.playback_session_listeners
    assert unsubscribe.called == 1


def test_d4_listener_not_released_on_pause(tmp_path: Path) -> None:
    """D4: a pause transition (no pop) does NOT release the dynamic
    listener — the session is still alive."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    player = "media_player.unlisted"
    rt.playback_sessions[player] = _session(
        duration_seconds=180.0,
        accumulated_playing_seconds=60.0,
    )
    unsubscribe = _register_dynamic_listener(rt, player)
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    started = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    paused_at = started + timedelta(seconds=60)
    old_state = SimpleNamespace(
        entity_id=player,
        state="playing",
        last_changed=started,
        attributes={},
    )
    new_state = SimpleNamespace(
        entity_id=player,
        state="paused",
        last_changed=paused_at,
        attributes={},
    )

    _drive_unlisted_state_change(
        hass, entry, rt, player, old_state, new_state
    )

    # Session still alive; listener NOT released.
    assert player in rt.playback_sessions
    assert player in rt.playback_session_listeners
    assert unsubscribe.called == 0


def test_d4_unload_releases_all_dynamic_listeners(tmp_path: Path) -> None:
    """D4: the unload callback registered in async_setup_queue_advancement
    releases every dynamic listener for unlisted targets."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})

    async_setup_queue_advancement(hass, entry, rt)

    # Simulate two unlisted targets having dynamic listeners registered.
    unlisted_a = "media_player.unlisted_a"
    unlisted_b = "media_player.unlisted_b"
    unsubscribe_a = FakeDynamicUnsubscribe()
    unsubscribe_b = FakeDynamicUnsubscribe()
    rt.playback_session_listeners[unlisted_a] = unsubscribe_a
    rt.playback_session_listeners[unlisted_b] = unsubscribe_b

    # The unload callback (registered by async_setup_queue_advancement)
    # must release every dynamic listener.
    for callback in entry.unload_callbacks:
        callback()

    assert unlisted_a not in rt.playback_session_listeners
    assert unlisted_b not in rt.playback_session_listeners
    assert unsubscribe_a.called == 1
    assert unsubscribe_b.called == 1
