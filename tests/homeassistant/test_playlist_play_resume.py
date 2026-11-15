"""Unit tests for the playlist play/resume wiring (card 3).

Mirrors the album resume/play coverage in
``test_album_resume_and_completion.py`` (plan decision Q5), proving:

- ``async_play_playlist`` resets the (user, playlist) tracking store, builds
  the full ordered queue, and plays the first track at 0:00 (reset-on-play).
- ``async_resume_playlist`` filters completed tracks out of the queue, plays
  the first remaining track at 0:00, and does NOT reset the store
  (filter-on-resume).
- A fully complete playlist returns ``playlist_complete`` without playing.
- Without a store, resuming queues every track from the start.
- The playlist queue origin (``queued_playlist_id``) is set only after the
  queue is built, so a failed lookup/queue call leaves it untouched.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from tests.homeassistant.ha_stubs import FakeHass, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist.const import (
    SERVICE_GET_PLAYLIST_TRACKS,
    SERVICE_QUEUE_ADD,
    SERVICE_QUEUE_CLEAR,
)
from custom_components.jellyfin_assist.orchestration import (
    async_play_playlist,
    async_resume_playlist,
)
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

def _make_raw_track(item_id: str, name: str, index: int) -> dict[str, Any]:
    return {
        "Id": item_id,
        "Name": name,
        "Type": "Audio",
        "Album": "Test Album",
        "AlbumArtist": "Test Artist",
        "Artists": ["Test Artist"],
        "IndexNumber": index,
        "ParentIndexNumber": 1,
        "RunTimeTicks": 200_000_000,
    }


def _make_runtime(**overrides: Any) -> JellyfinAssistRuntime:
    base: dict[str, Any] = {
        "client": AsyncMock(),
        "catalog_manager": AsyncMock(),
        "connection_info": None,
        "user_id": "user-1",
        "playback_targets": ("media_player.test",),
        "queue_client": AsyncMock(),
        "playback_sessions": {},
        "playback_write_locks": {},
        "pending_selection": None,
        "album_tracking_store": None,
        "playlist_tracking_store": None,
        "queued_playlist_id": None,
        "queue_advancement_targets": (),
        "last_queue_advancement": None,
    }
    base.update(overrides)
    return JellyfinAssistRuntime(**base)


class _FakePlaylistStore:
    """In-memory playlist tracking store for tests."""

    def __init__(self, completed: set[str] | None = None, playlist_id: str = "playlist-1") -> None:
        self.playlist_id = playlist_id
        self._completed: dict[str, set[str]] = {}
        if completed is not None:
            self._completed[playlist_id] = set(completed)
        self.reset_called_with: list[tuple[str, str]] = []
        self.marked: list[tuple[str, str, str]] = []

    def completed_ids(self, user_id: str, playlist_id: str) -> frozenset[str]:
        return frozenset(self._completed.get(playlist_id, set()))

    async def mark_complete(self, user_id: str, playlist_id: str, item_id: str) -> None:
        self._completed.setdefault(playlist_id, set()).add(item_id)
        self.marked.append((user_id, playlist_id, item_id))

    async def reset_playlist(self, user_id: str, playlist_id: str) -> None:
        self._completed[playlist_id] = set()
        self.reset_called_with.append((user_id, playlist_id))


def _make_fake_hass() -> FakeHass:
    return FakeHass(Path("/tmp/test_root"))


async def _fake_action(
    hass: Any,
    runtime: Any,
    service: str,
    data: Any,
    *,
    context: Any = None,
    playlist_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fake _action returning playlist tracks for SERVICE_GET_PLAYLIST_TRACKS."""
    if service == SERVICE_GET_PLAYLIST_TRACKS:
        return {"status": 200, "content": {"Items": playlist_items}}
    if service == SERVICE_QUEUE_CLEAR:
        return {"status": 200, "content": {"success": True}}
    if service == SERVICE_QUEUE_ADD:
        return {"status": 200, "content": {"success": True}}
    return {"status": 200, "content": {"Items": []}}


# ---------------------------------------------------------------------------
# reset-on-play: MusicPlaylist play clears tracking, queues all, plays track 1
# ---------------------------------------------------------------------------

class TestPlayPlaylistResetOnPlay:
    """Playing a playlist resets the store and queues every track in order."""

    def test_play_resets_store_and_queues_all_tracks_in_order(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
            _make_raw_track("t3", "Track 3", 3),
        ]
        store = _FakePlaylistStore(completed={"t1", "t2", "t3"})
        runtime = _make_runtime(playlist_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, playlist_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = run(async_play_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        assert result["success"] is True
        assert result["status"] == "playing"
        assert result["total_tracks"] == 3
        # All tracks queued in playlist order (no filtering on a play).
        plan_ids = [item["id"] for item in result["playback_plan"]]
        assert plan_ids == ["t1", "t2", "t3"]
        # The store was reset for this (user, playlist).
        assert store.reset_called_with == [("user-1", "playlist-1")]
        assert store.completed_ids("user-1", "playlist-1") == frozenset()
        # First track queued as a playlist member.
        assert result["jellyfin_id"] == "t1"

    def test_play_sets_playlist_queue_origin(self) -> None:
        tracks = [_make_raw_track("t1", "Track 1", 1)]
        store = _FakePlaylistStore(completed=set())
        runtime = _make_runtime(playlist_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, playlist_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            run(async_play_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        # The origin is set once playback has begun, so the completion hook
        # (card 2) marks future completions against this playlist.
        assert runtime.queued_playlist_id == "playlist-1"

    def test_play_empty_playlist_returns_playlist_empty(self) -> None:
        store = _FakePlaylistStore(completed=set())
        runtime = _make_runtime(playlist_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, playlist_items=[]
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = run(async_play_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        assert result["success"] is False
        assert result["status"] == "playlist_empty"
        # An empty lookup must not leave a queue origin behind.
        assert runtime.queued_playlist_id is None

    def test_play_lookup_failure_returns_playlist_lookup_failed(self) -> None:
        store = _FakePlaylistStore(completed=set())
        runtime = _make_runtime(playlist_tracking_store=store)
        hass = _make_fake_hass()

        async def boom(hass, runtime, service, data, *, context=None, **kw):
            return {"status": 404}

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=boom,
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = run(async_play_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        assert result["success"] is False
        assert result["status"] == "playlist_lookup_failed"
        assert runtime.queued_playlist_id is None


# ---------------------------------------------------------------------------
# filter-on-resume: partial completion queues remaining tracks, no reset
# ---------------------------------------------------------------------------

class TestResumePlaylistFilterOnResume:
    """Resuming keeps completed tracks and plays the first remaining one."""

    def test_resume_queues_remaining_tracks_and_does_not_reset(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
            _make_raw_track("t3", "Track 3", 3),
            _make_raw_track("t4", "Track 4", 4),
            _make_raw_track("t5", "Track 5", 5),
        ]
        store = _FakePlaylistStore(completed={"t1", "t2"})
        runtime = _make_runtime(playlist_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, playlist_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = run(async_resume_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        assert result["success"] is True
        assert result["status"] == "playing"
        assert result["total_tracks"] == 5
        assert result["completed_tracks"] == 2
        assert result["remaining_tracks"] == 3
        # The remaining tracks are queued in order, filtered from the store.
        plan_ids = [item["id"] for item in result["playback_plan"]]
        assert plan_ids == ["t3", "t4", "t5"]
        # Resume is a filtered queue, NOT a reset: the store survives.
        assert store.reset_called_with == []
        assert store.completed_ids("user-1", "playlist-1") == {"t1", "t2"}
        # The first remaining track is what is played.
        assert result["jellyfin_id"] == "t3"

    def test_resume_starts_first_remaining_at_zero(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
            _make_raw_track("t3", "Track 3", 3),
        ]
        store = _FakePlaylistStore(completed={"t1"})
        runtime = _make_runtime(playlist_tracking_store=store)
        hass = _make_fake_hass()

        play_item = AsyncMock(return_value={"success": True})
        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, playlist_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=play_item,
        ):
            result = run(async_resume_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        assert result["success"] is True
        # The first item played is the first non-completed track (track 2).
        assert result["jellyfin_id"] == "t2"
        # No start_position is seeked: resume is a filtered queue, not a
        # mid-track seek. assert_called_once confirms the first remaining
        # track is played from 0:00 (no start_position_ticks passed).
        play_item.assert_called_once()
        args, kwargs = play_item.call_args
        played_item = kwargs.get("item", args[2] if len(args) >= 3 else None)
        assert played_item["id"] == "t2"
        # 0:00 resume: no start_position_ticks / seek offset in the plan item.
        assert "start_position_ticks" not in played_item

    def test_resume_all_complete_returns_playlist_complete(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
        ]
        store = _FakePlaylistStore(completed={"t1", "t2"})
        runtime = _make_runtime(playlist_tracking_store=store)
        hass = _make_fake_hass()

        play_item = AsyncMock(return_value={"success": True})
        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, playlist_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=play_item,
        ):
            result = run(async_resume_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        assert result["success"] is False
        assert result["status"] == "playlist_complete"
        assert result["total_tracks"] == 2
        assert result["completed_tracks"] == 2
        # No playback started; the store is preserved for a repeat.
        assert result.get("item") is None
        play_item.assert_not_called()
        assert store.reset_called_with == []
        assert store.completed_ids("user-1", "playlist-1") == {"t1", "t2"}

    def test_resume_no_store_queues_all_tracks(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
        ]
        runtime = _make_runtime(playlist_tracking_store=None)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, playlist_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = run(async_resume_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        assert result["success"] is True
        assert result["remaining_tracks"] == 2
        plan_ids = [item["id"] for item in result["playback_plan"]]
        assert plan_ids == ["t1", "t2"]

    def test_resume_sets_playlist_queue_origin(self) -> None:
        tracks = [_make_raw_track("t1", "Track 1", 1)]
        store = _FakePlaylistStore(completed=set())
        runtime = _make_runtime(playlist_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, playlist_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            run(async_resume_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        assert runtime.queued_playlist_id == "playlist-1"
