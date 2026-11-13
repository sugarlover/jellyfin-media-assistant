"""Unit tests for album reset-on-play, resume_album, and album-complete logic."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from tests.homeassistant.ha_stubs import (
    FakeHass,
    install_homeassistant_stubs,
)

install_homeassistant_stubs()

from custom_components.jellyfin_assist.advancement import (
    _async_handle_album_completion,
    _async_mark_album_completion,
)
from custom_components.jellyfin_assist.const import (
    DOMAIN,
    SERVICE_GET_ALBUM_TRACKS,
    SERVICE_QUEUE_ADD,
    SERVICE_QUEUE_CLEAR,
)
from custom_components.jellyfin_assist.orchestration import (
    async_resolve_media_intent,
    async_resume_album,
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
        "queue_advancement_targets": (),
        "last_queue_advancement": None,
    }
    base.update(overrides)
    return JellyfinAssistRuntime(**base)


class _FakeAlbumStore:
    """In-memory album tracking store for tests."""

    def __init__(self, completed: set[str] | None = None) -> None:
        self._completed: dict[str, set[str]] = {}
        if completed is not None:
            self._completed["album-1"] = set(completed)
        self.reset_called_with: list[tuple[str, str]] = []
        self.marked: list[tuple[str, str, str]] = []

    def completed_ids(self, user_id: str, album_id: str) -> frozenset[str]:
        return frozenset(self._completed.get(album_id, set()))

    async def mark_complete(self, user_id: str, album_id: str, item_id: str) -> None:
        self._completed.setdefault(album_id, set()).add(item_id)
        self.marked.append((user_id, album_id, item_id))

    async def reset_album(self, user_id: str, album_id: str) -> None:
        self._completed[album_id] = set()
        self.reset_called_with.append((user_id, album_id))


def _make_fake_hass() -> FakeHass:
    """Create a FakeHass with a root path."""
    return FakeHass(Path("/tmp/test_root"))


async def _fake_action(
    hass: Any,
    runtime: Any,
    service: str,
    data: Any,
    *,
    context: Any = None,
    album_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fake _action that returns album tracks for SERVICE_GET_ALBUM_TRACKS."""
    if service == SERVICE_GET_ALBUM_TRACKS:
        return {"status": 200, "content": {"Items": album_items}}
    if service == SERVICE_QUEUE_CLEAR:
        return {"status": 200, "content": {"success": True}}
    if service == SERVICE_QUEUE_ADD:
        return {"status": 200, "content": {"success": True}}
    if service == "search":
        return {"items": [
            {
                "id": "album-1",
                "name": "Test Album",
                "type": "MusicAlbum",
                "album_artist": "Test Artist",
                "artist_name": "Test Artist",
            }
        ]}
    return {"status": 200, "content": {"Items": []}}


# ---------------------------------------------------------------------------
# D4: resume_album — partial completion (2/5 done → queue 3,4,5 at 0:00)
# ---------------------------------------------------------------------------

class TestResumeAlbumPartialCompletion:
    """When 2 of 5 tracks are done, resume queues tracks 3,4,5 and plays track 3."""

    def test_resume_queues_remaining_tracks_in_order(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
            _make_raw_track("t3", "Track 3", 3),
            _make_raw_track("t4", "Track 4", 4),
            _make_raw_track("t5", "Track 5", 5),
        ]
        store = _FakeAlbumStore(completed={"t1", "t2"})
        runtime = _make_runtime(album_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, album_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = run(async_resume_album(
                hass,
                runtime,
                album_id="album-1",
                media_player="media_player.test",
            ))

        assert result["success"] is True
        assert result["status"] == "playing"
        assert result["total_tracks"] == 5
        assert result["completed_tracks"] == 2
        assert result["remaining_tracks"] == 3
        # The playback plan should be tracks 3, 4, 5 in album order
        plan_ids = [item["id"] for item in result["playback_plan"]]
        assert plan_ids == ["t3", "t4", "t5"]

    def test_resume_starts_first_remaining_at_zero(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
            _make_raw_track("t3", "Track 3", 3),
        ]
        store = _FakeAlbumStore(completed={"t1"})
        runtime = _make_runtime(album_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, album_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = run(async_resume_album(
                hass,
                runtime,
                album_id="album-1",
                media_player="media_player.test",
            ))

        assert result["success"] is True
        # The first item played should be track 2 (first non-completed)
        first_id = result.get("jellyfin_id")
        assert first_id == "t2"


# ---------------------------------------------------------------------------
# D4: resume_album — all tracks complete
# ---------------------------------------------------------------------------

class TestResumeAlbumAllComplete:
    """When all tracks are completed, resume returns album_complete without playing."""

    def test_all_complete_returns_album_complete(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
        ]
        store = _FakeAlbumStore(completed={"t1", "t2"})
        runtime = _make_runtime(album_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, album_items=tracks
            ),
        ):
            result = run(async_resume_album(
                hass,
                runtime,
                album_id="album-1",
                media_player="media_player.test",
            ))

        assert result["success"] is False
        assert result["status"] == "album_complete"
        assert result["total_tracks"] == 2
        assert result["completed_tracks"] == 2
        # No playback should have started
        assert result.get("item") is None

    def test_empty_album_returns_album_empty(self) -> None:
        store = _FakeAlbumStore(completed=set())
        runtime = _make_runtime(album_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, album_items=[]
            ),
        ):
            result = run(async_resume_album(
                hass,
                runtime,
                album_id="album-1",
                media_player="media_player.test",
            ))

        assert result["success"] is False
        assert result["status"] == "album_empty"


# ---------------------------------------------------------------------------
# D4: resume_album — no store (tracking disabled)
# ---------------------------------------------------------------------------

class TestResumeAlbumNoStore:
    """Without an album tracking store, all tracks are queued from the start."""

    def test_no_store_queues_all_tracks(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
        ]
        runtime = _make_runtime(album_tracking_store=None)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, album_items=tracks
            ),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = run(async_resume_album(
                hass,
                runtime,
                album_id="album-1",
                media_player="media_player.test",
            ))

        assert result["success"] is True
        assert result["remaining_tracks"] == 2
        plan_ids = [item["id"] for item in result["playback_plan"]]
        assert plan_ids == ["t1", "t2"]


# ---------------------------------------------------------------------------
# D3: reset-on-play — MusicAlbum resolve path clears tracking
# ---------------------------------------------------------------------------

class TestResetOnPlay:
    """D3: when resolving a MusicAlbum, album tracking is reset before building the plan."""

    def test_music_album_resolve_resets_tracking(self) -> None:
        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
        ]
        store = _FakeAlbumStore(completed={"t1", "t2"})
        runtime = _make_runtime(album_tracking_store=store)
        hass = _make_fake_hass()

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=lambda h, r, s, d, *, c=None, **kw: _fake_action(
                h, r, s, d, context=c, album_items=tracks
            ),
        ):
            result = run(async_resolve_media_intent(
                hass,
                runtime,
                query="Test Album",
                media_type="MusicAlbum",
            ))

        assert result["success"] is True
        assert result["status"] == "resolved"
        # The store should have been reset
        assert store.reset_called_with == [("user-1", "album-1")]
        # Completed tracks should be cleared
        assert store.completed_ids("user-1", "album-1") == frozenset()


# ---------------------------------------------------------------------------
# Album-complete: announce + stop (no repeat)
# ---------------------------------------------------------------------------

class TestAlbumCompleteNoRepeat:
    """When the album is fully complete and repeat is off, announce 'Album complete' and stop."""

    def test_announce_and_stop(self) -> None:
        store = _FakeAlbumStore(completed={"t1", "t2"})
        runtime = _make_runtime(album_tracking_store=store)
        runtime.client = AsyncMock()
        runtime.client.async_get_item = AsyncMock(
            return_value={
                "Id": "t2",
                "Type": "Audio",
                "AlbumId": "album-1",
                "Album": "Test Album",
            }
        )
        runtime.client.async_get_items = AsyncMock(
            return_value={"Items": [
                {"Id": "t1", "Name": "Track 1"},
                {"Id": "t2", "Name": "Track 2"},
            ]}
        )

        hass = _make_fake_hass()

        result = run(_async_handle_album_completion(
            hass,
            runtime,
            player="media_player.test",
            completed_item_id="t2",
            repeat_queue=False,
        ))

        assert result is not None
        assert result["album_complete"] is True
        assert result["album_id"] == "album-1"
        assert result["album_name"] == "Test Album"
        assert result["total_tracks"] == 2
        assert result["repeat_queue"] is False
        assert "repeated" not in result
        # Announce was called
        announce_calls = [
            c for c in hass.services.calls
            if c["domain"] == "media_player" and c["service"] == "announce"
        ]
        assert len(announce_calls) == 1
        assert announce_calls[0]["data"]["message"] == "Album complete"
        # Stop was called
        stop_calls = [
            c for c in hass.services.calls
            if c["domain"] == "media_player" and c["service"] == "stop"
        ]
        assert len(stop_calls) == 1

    def test_partial_album_returns_none(self) -> None:
        """When only some tracks are complete, the helper returns None (not done yet)."""
        store = _FakeAlbumStore(completed={"t1"})
        runtime = _make_runtime(album_tracking_store=store)
        runtime.client = AsyncMock()
        runtime.client.async_get_item = AsyncMock(
            return_value={
                "Id": "t1",
                "Type": "Audio",
                "AlbumId": "album-1",
                "Album": "Test Album",
            }
        )
        runtime.client.async_get_items = AsyncMock(
            return_value={"Items": [
                {"Id": "t1", "Name": "Track 1"},
                {"Id": "t2", "Name": "Track 2"},
            ]}
        )

        hass = _make_fake_hass()

        result = run(_async_handle_album_completion(
            hass,
            runtime,
            player="media_player.test",
            completed_item_id="t1",
            repeat_queue=False,
        ))

        # Only 1 of 2 tracks complete → not album-complete
        assert result is None

    def test_non_audio_returns_none(self) -> None:
        """A non-audio completed item should not trigger album completion."""
        store = _FakeAlbumStore(completed={"t1"})
        runtime = _make_runtime(album_tracking_store=store)
        runtime.client = AsyncMock()
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "movie-1", "Type": "Movie"}
        )
        runtime.client.async_get_items = AsyncMock(return_value={"Items": []})

        hass = _make_fake_hass()

        result = run(_async_handle_album_completion(
            hass,
            runtime,
            player="media_player.test",
            completed_item_id="movie-1",
            repeat_queue=False,
        ))

        assert result is None


# ---------------------------------------------------------------------------
# Album-complete: repeat re-marking
# ---------------------------------------------------------------------------

class TestAlbumCompleteRepeat:
    """When the album is fully complete and repeat is on, reset tracking for re-marking."""

    def test_repeat_resets_album_tracking(self) -> None:
        store = _FakeAlbumStore(completed={"t1", "t2"})
        runtime = _make_runtime(album_tracking_store=store)
        runtime.client = AsyncMock()
        runtime.client.async_get_item = AsyncMock(
            return_value={
                "Id": "t2",
                "Type": "Audio",
                "AlbumId": "album-1",
                "Album": "Test Album",
            }
        )
        runtime.client.async_get_items = AsyncMock(
            return_value={"Items": [
                {"Id": "t1", "Name": "Track 1"},
                {"Id": "t2", "Name": "Track 2"},
            ]}
        )

        hass = _make_fake_hass()

        result = run(_async_handle_album_completion(
            hass,
            runtime,
            player="media_player.test",
            completed_item_id="t2",
            repeat_queue=True,
        ))

        assert result is not None
        assert result["album_complete"] is True
        assert result["repeat_queue"] is True
        assert result["repeated"] is True
        # Announce was called
        announce_calls = [
            c for c in hass.services.calls
            if c["domain"] == "media_player" and c["service"] == "announce"
        ]
        assert len(announce_calls) == 1
        assert announce_calls[0]["data"]["message"] == "Album complete"
        # Stop was NOT called (playback continues)
        stop_calls = [
            c for c in hass.services.calls
            if c["domain"] == "media_player" and c["service"] == "stop"
        ]
        assert len(stop_calls) == 0
        # Album tracking was reset
        assert store.reset_called_with == [("user-1", "album-1")]
        # Completed ids are now empty
        assert store.completed_ids("user-1", "album-1") == frozenset()


# ---------------------------------------------------------------------------
# _async_mark_album_completion — marks only audio items
# ---------------------------------------------------------------------------

class TestMarkAlbumCompletion:
    """_async_mark_album_completion marks only Audio/MusicVideo items with an AlbumId."""

    def test_marks_audio_item(self) -> None:
        store = _FakeAlbumStore()
        runtime = _make_runtime(album_tracking_store=store)
        runtime.client = AsyncMock()
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "t1", "Type": "Audio", "AlbumId": "album-1"}
        )

        run(_async_mark_album_completion(runtime, "t1"))

        assert store.marked == [("user-1", "album-1", "t1")]
        assert "t1" in store.completed_ids("user-1", "album-1")

    def test_skips_non_audio(self) -> None:
        store = _FakeAlbumStore()
        runtime = _make_runtime(album_tracking_store=store)
        runtime.client = AsyncMock()
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "movie-1", "Type": "Movie"}
        )

        run(_async_mark_album_completion(runtime, "movie-1"))

        assert store.marked == []

    def test_skips_no_album_id(self) -> None:
        store = _FakeAlbumStore()
        runtime = _make_runtime(album_tracking_store=store)
        runtime.client = AsyncMock()
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "t1", "Type": "Audio"}
        )

        run(_async_mark_album_completion(runtime, "t1"))

        assert store.marked == []

    def test_no_store_is_noop(self) -> None:
        runtime = _make_runtime(album_tracking_store=None)
        # Should not raise
        run(_async_mark_album_completion(runtime, "t1"))
