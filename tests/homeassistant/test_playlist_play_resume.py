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
    SERVICE_RESOLVE_MEDIA_PLAYER,
)
from custom_components.jellyfin_assist.orchestration import (
    async_media_orchestrator,
    async_play_pending_media,
    async_play_playlist,
    async_resolve_playlist_id,
    async_resume_playlist,
)
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

def _make_raw_track(
    item_id: str,
    name: str,
    index: int,
    *,
    index_number: int | None = None,
    parent_index: int = 1,
) -> dict[str, Any]:
    """Build a raw media-track mapping.

    ``index`` is the playlist ENTRY position (1-based), while ``index_number``
    is the ALBUM track number (``IndexNumber``). They are deliberately
    decoupled so tests no longer assume entry order == album track order
    (the old fixture prettied the two together, which masked the out-of-order
    playlist bug). When ``index_number`` is not supplied it falls back to
    ``index`` to keep the pre-existing fixtures green.
    """
    return {
        "Id": item_id,
        "Name": name,
        "Type": "Audio",
        "Album": "Test Album",
        "AlbumArtist": "Test Artist",
        "Artists": ["Test Artist"],
        "IndexNumber": index if index_number is None else index_number,
        "ParentIndexNumber": parent_index,
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


# ---------------------------------------------------------------------------
# D1 regression: playlist ENTRY order must be preserved, NOT album track order
# ---------------------------------------------------------------------------


class TestPlaylistEntryOrderRegression:
    """Playing a playlist preserves playlist ENTRY order, not album track order.

    The pre-fix bug: ``async_handle_get_playlist_tracks`` fetched members via
    ``recursive /Items`` sorted by ``ParentIndexNumber,IndexNumber`` (album
    track/disc numbers), so a playlist whose entry order differs from album
    track order played out of order. The fixture here decouples IndexNumber
    (album track number) from playlist position so the regression is real.
    """

    def test_play_preserves_entry_order_not_album_track_order(self) -> None:
        # Entry order: t1, t2, t3, t4 with album track numbers [3, 4, 1, 2]
        # across two albums. Album-track sort would be [t3, t4, t1, t2],
        # which is NOT the entry order; the fix must keep [t1, t2, t3, t4].
        tracks = [
            _make_raw_track("t1", "Track 1", 1, index_number=3, parent_index=2),
            _make_raw_track("t2", "Track 2", 2, index_number=4, parent_index=2),
            _make_raw_track("t3", "Track 3", 3, index_number=1, parent_index=1),
            _make_raw_track("t4", "Track 4", 4, index_number=2, parent_index=1),
        ]
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
            result = run(async_play_playlist(
                hass,
                runtime,
                playlist_id="playlist-1",
                media_player="media_player.test",
            ))

        assert result["success"] is True
        assert result["status"] == "playing"
        # The queue follows the playlist ENTRY order, not album track number.
        plan_ids = [item["id"] for item in result["playback_plan"]]
        assert plan_ids == ["t1", "t2", "t3", "t4"]
        # The first track is the first ENTRY, not the lowest album track number.
        assert result["jellyfin_id"] == "t1"

    def test_resume_preserves_entry_order_not_album_track_order(self) -> None:
        # Entry order: t1, t2, t3, t4 with album track numbers [3, 4, 1, 2]
        # across two albums; complete only t1. The remaining tracks, in
        # ENTRY order, are [t2, t3, t4]. In ALBUM-track order they would be
        # [t3, t4, t2] (t3=album1#1, t4=album1#2, t2=album2#2). These differ,
        # so this is a genuine regression guard: the first remaining track is
        # the second ENTRY (t2), not the lowest album track number (t3).
        tracks = [
            _make_raw_track("t1", "Track 1", 1, index_number=3, parent_index=2),
            _make_raw_track("t2", "Track 2", 2, index_number=4, parent_index=2),
            _make_raw_track("t3", "Track 3", 3, index_number=1, parent_index=1),
            _make_raw_track("t4", "Track 4", 4, index_number=2, parent_index=1),
        ]
        store = _FakePlaylistStore(completed={"t1"})
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
        plan_ids = [item["id"] for item in result["playback_plan"]]
        assert plan_ids == ["t2", "t3", "t4"]
        # First remaining track is the second ENTRY (t2), not reordered by
        # album track number (which would be t3).
        assert result["jellyfin_id"] == "t2"
        # Resume filters completed, does not reset the store.
        assert store.reset_called_with == []


# ---------------------------------------------------------------------------
# pending_selection wiring: playlist multi-match -> "select number one"
# ---------------------------------------------------------------------------

_PLAYER = "media_player.example_chromecast"


async def _resolve_and_playlist_action(
    hass: Any,
    runtime: Any,
    service: str,
    data: Any,
    *,
    context: Any = None,
    tracks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fake _action: resolves the media player, then serves playlist flows."""
    if service == SERVICE_RESOLVE_MEDIA_PLAYER:
        return {
            "success": True,
            "media_player": data["media_player"],
            "query": data["query"],
            "media_type": data["media_type"],
        }
    return await _fake_action(hass, runtime, service, data, context=context, playlist_items=tracks or [])


class TestPlaylistMultiMatchPendingSelection:
    """A MusicPlaylist multi-match sets pending_selection and the spoken
    message ends "Please select a number." so the numbered follow-up routes
    through async_play_pending_media."""

    def test_multi_match_sets_pending_selection_and_message(self) -> None:
        runtime = _make_runtime()
        hass = _make_fake_hass()
        playlists = [
            {"Id": "pl-1", "Name": "Kids Favorites", "Type": "Playlist"},
            {"Id": "pl-2", "Name": "Kids Bedtime", "Type": "Playlist"},
        ]
        runtime.client.async_get_items = AsyncMock(return_value={"Items": playlists})

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=_resolve_and_playlist_action,
        ):
            result = run(async_media_orchestrator(
                hass,
                runtime,
                query="kids",
                media_player=_PLAYER,
                media_type="MusicPlaylist",
                operation="play",
            ))

        assert result["success"] is False
        assert result["status"] == "multiple_matches"
        assert result["message"].endswith("Please select a number.")
        pending = runtime.pending_selection
        assert isinstance(pending, dict)
        assert [item["id"] for item in pending["items"]] == ["pl-1", "pl-2"]
        assert pending["media_player"] == _PLAYER
        assert pending["operation"] == "play"
        assert pending["query"] == "kids"
        assert pending["intent"] == "MusicPlaylist"

    def test_selection_resolves_to_play_playlist_success(self) -> None:
        runtime = _make_runtime(playlist_tracking_store=_FakePlaylistStore(completed=set()))
        hass = _make_fake_hass()
        playlists = [
            {"Id": "pl-1", "Name": "Kids Favorites", "Type": "Playlist"},
            {"Id": "pl-2", "Name": "Kids Bedtime", "Type": "Playlist"},
        ]

        async def fake_get_items(user_id: str, **kwargs: Any) -> dict[str, Any]:
            if kwargs.get("search_term") == "Kids Favorites":
                return {"Items": [playlists[0]]}
            return {"Items": playlists}

        runtime.client.async_get_items = AsyncMock(side_effect=fake_get_items)
        # Real live shape: Type == "Playlist" (not the fake "MusicPlaylist").
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "pl-1", "Name": "Kids Favorites", "Type": "Playlist"}
        )

        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
        ]

        async def _resolve_tracks(h, r, s, d, *, c=None, **kw):
            return await _resolve_and_playlist_action(h, r, s, d, context=c, tracks=tracks)

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=_resolve_tracks,
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            first = run(async_media_orchestrator(
                hass,
                runtime,
                query="kids",
                media_player=_PLAYER,
                media_type="MusicPlaylist",
                operation="play",
            ))
        assert first["success"] is False
        assert isinstance(runtime.pending_selection, dict)
        assert runtime.pending_selection is not None

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=_resolve_tracks,
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = run(async_play_pending_media(hass, runtime, selection=1))

        assert result["success"] is True
        # The selection re-entered the orchestrator as a MusicPlaylist and
        # delegated to async_play_playlist: the first track is queued/played.
        assert result["jellyfin_id"] == "t1"
        assert result["status"] == "playing"
        assert result["intent"] == "MusicPlaylist"
        # Successful resolution clears the pending selection.
        assert runtime.pending_selection is None


# ---------------------------------------------------------------------------
# Bug C (D1): playlist search response is client-side filtered to Playlist
# items only — mixed-type search results (Genre/Audio/Video) are dropped.
# ---------------------------------------------------------------------------

class TestPlaylistResolveFiltersMixedTypes:
    """async_resolve_playlist_id keeps only live Type=='Playlist' items."""

    def test_mixed_type_search_returns_playlist_only(self) -> None:
        runtime = _make_runtime()
        hass = _make_fake_hass()
        mixed = [
            {"Id": "pl-1", "Name": "Kids", "Type": "Playlist"},
            {"Id": "g-1", "Name": "Kids", "Type": "Genre"},
            {"Id": "a-1", "Name": "Kids", "Type": "Audio"},
            {"Id": "v-1", "Name": "Kids", "Type": "Video"},
        ]
        runtime.client.async_get_items = AsyncMock(return_value={"Items": mixed})

        result = run(async_resolve_playlist_id(
            hass,
            runtime,
            query="kids",
        ))

        assert result["success"] is True
        assert result["status"] == "resolved"
        assert result["jellyfin_id"] == "pl-1"
        # Only the Playlist survives; a single match resolves directly.
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == "pl-1"
        # The include_item_types parameter is kept for the server query.
        call_kwargs = runtime.client.async_get_items.call_args.kwargs
        assert call_kwargs["include_item_types"] == "MusicPlaylist"

    def test_multiple_playlist_matches_list_only_playlists(self) -> None:
        runtime = _make_runtime()
        hass = _make_fake_hass()
        mixed = [
            {"Id": "pl-1", "Name": "Kids Favorites", "Type": "Playlist"},
            {"Id": "g-1", "Name": "Kids", "Type": "Genre"},
            {"Id": "a-1", "Name": "Kids", "Type": "Audio"},
            {"Id": "pl-2", "Name": "Kids Bedtime", "Type": "Playlist"},
            {"Id": "v-1", "Name": "Kids", "Type": "Video"},
        ]
        runtime.client.async_get_items = AsyncMock(return_value={"Items": mixed})

        result = run(async_resolve_playlist_id(
            hass,
            runtime,
            query="kids",
        ))

        assert result["success"] is False
        assert result["status"] == "multiple_matches"
        # The spoken message lists only the two playlists.
        assert "Kids Favorites" in result["message"]
        assert "Kids Bedtime" in result["message"]
        assert "Genre" not in result["message"]
        assert "Video" not in result["message"]
        # Pending items carry only playlists (ids pl-1, pl-2).
        pending_ids = [item["id"] for item in result["items"]]
        assert pending_ids == ["pl-1", "pl-2"]
        assert all(item["type"] == "MusicPlaylist" for item in result["items"])
        # Downstream hard-coded type string is preserved for the pending items.


# ---------------------------------------------------------------------------
# Bug A (D2): live Type=='Playlist' is a container item, so a pending
# playlist selection re-enters the orchestrator and plays via
# async_play_playlist.
# ---------------------------------------------------------------------------


class TestPlaylistPendingSelectionRealShape:
    """A live-shape (Type=='Playlist') pending selection plays via
    async_play_playlist, not 'cannot be queued directly'."""

    def test_pending_playlist_selection_plays_via_play_playlist(self) -> None:
        runtime = _make_runtime(playlist_tracking_store=_FakePlaylistStore(completed=set()))
        hass = _make_fake_hass()
        playlists = [
            {"Id": "pl-1", "Name": "Kids Favorites", "Type": "Playlist"},
            {"Id": "pl-2", "Name": "Kids Bedtime", "Type": "Playlist"},
        ]

        async def fake_get_items(user_id: str, **kwargs: Any) -> dict[str, Any]:
            if kwargs.get("search_term") == "Kids Favorites":
                return {"Items": [playlists[0]]}
            return {"Items": playlists}

        runtime.client.async_get_items = AsyncMock(side_effect=fake_get_items)
        # Real live shape: Type == "Playlist" (not the fake "MusicPlaylist").
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "pl-1", "Name": "Kids Favorites", "Type": "Playlist"}
        )

        tracks = [
            _make_raw_track("t1", "Track 1", 1),
            _make_raw_track("t2", "Track 2", 2),
        ]

        async def _resolve_tracks(h, r, s, d, *, c=None, **kw):
            return await _resolve_and_playlist_action(h, r, s, d, context=c, tracks=tracks)

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=_resolve_tracks,
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=AsyncMock(return_value={"success": True}),
        ) as play_item:
            first = run(async_media_orchestrator(
                hass,
                runtime,
                query="kids",
                media_player=_PLAYER,
                media_type="MusicPlaylist",
                operation="play",
            ))
        assert first["success"] is False
        assert isinstance(runtime.pending_selection, dict)
        assert runtime.pending_selection is not None

        with patch(
            "custom_components.jellyfin_assist.orchestration._action",
            new=_resolve_tracks,
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_prepare_play_session",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "custom_components.jellyfin_assist.orchestration.async_play_item",
            new=play_item,
        ):
            result = run(async_play_pending_media(hass, runtime, selection=1))

        assert result["success"] is True
        # The live-shape playlist selection re-entered the orchestrator as a
        # MusicPlaylist and delegated to async_play_playlist: the first
        # track is queued/played (not "cannot be queued directly").
        assert result["jellyfin_id"] == "t1"
        assert result["status"] == "playing"
        assert result["intent"] == "MusicPlaylist"
        # Successful resolution clears the pending selection.
        assert runtime.pending_selection is None


# ---------------------------------------------------------------------------
# D1 acceptance: an exact single Playlist match resolves directly with no
# "Please select a number." prompt.
# ---------------------------------------------------------------------------


class TestPlaylistExactSingleMatchNoPrompt:
    """One surviving Type=='Playlist' item for "Kids" resolves directly."""

    def test_single_playlist_match_resolves_without_prompt(self) -> None:
        runtime = _make_runtime()
        hass = _make_fake_hass()
        mixed = [
            {"Id": "pl-kids", "Name": "Kids", "Type": "Playlist"},
            {"Id": "g-1", "Name": "Kids", "Type": "Genre"},
            {"Id": "a-1", "Name": "Kids", "Type": "Audio"},
            {"Id": "v-1", "Name": "Kids", "Type": "Video"},
        ]
        runtime.client.async_get_items = AsyncMock(return_value={"Items": mixed})

        result = run(async_resolve_playlist_id(
            hass,
            runtime,
            query="Kids",
        ))

        assert result["success"] is True
        assert result["status"] == "resolved"
        assert result["jellyfin_id"] == "pl-kids"
        # No selection prompt: the message does not ask to pick a number.
        assert "Please use a more specific name" not in result["message"]
        assert "select" not in result["message"].lower()


# ---------------------------------------------------------------------------
# Bug B (D3): a RuntimeError("Session is closed") from
# async_post_playing_items must not escape _async_write_session_position.
# ---------------------------------------------------------------------------


class TestSessionClosedRuntimeErrorContained:
    """A closed-aiohttp-session RuntimeError degrades to the debug log."""

    def test_runtime_error_does_not_escape_write_session_position(self) -> None:
        from custom_components.jellyfin_assist.advancement import (
            _async_write_session_position,
        )

        runtime = _make_runtime()
        runtime.playback_sessions["media_player.test"] = {
            "item_id": "item-1",
            "accumulated_playing_seconds": 120.0,
        }
        runtime.client.async_post_playing_items = AsyncMock(
            side_effect=RuntimeError("Session is closed")
        )

        # Must not raise: the RuntimeError is caught and logged at debug.
        run(_async_write_session_position(
            runtime,
            "media_player.test",
            False,
            None,
        ))

        runtime.client.async_post_playing_items.assert_awaited_once()
