"""Unit tests for the per-playlist completion hook (_async_mark_playlist_completion).

Mirror of ``TestMarkAlbumCompletion`` in
``test_album_resume_and_completion.py`` (plan decision Q5), extended with the
provenance-flag cases that distinguish the playlist hook from the album hook:

- ``queued_playlist_id`` present + completed item is audio  -> marks complete
- ``queued_playlist_id`` absent (album/native-queue path)  -> silent no-op
- completed item is not audio                                -> no-op
- no store / no user / no client / empty item id              -> no-op

The hook only ever marks; it never resets on this path, so the
``completion_rejected`` / skip path (which never calls it) leaves the
playlist store untouched by construction.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from tests.homeassistant.ha_stubs import install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist.advancement import (
    _async_mark_playlist_completion,
)
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime


def run(coro: Any) -> Any:
    return asyncio.run(coro)


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

    def __init__(self, completed: set[str] | None = None) -> None:
        self._completed: dict[str, set[str]] = {}
        if completed is not None:
            self._completed["playlist-1"] = set(completed)
        self.marked: list[tuple[str, str, str]] = []

    def completed_ids(self, user_id: str, playlist_id: str) -> frozenset[str]:
        return frozenset(self._completed.get(playlist_id, set()))

    async def mark_complete(self, user_id: str, playlist_id: str, item_id: str) -> None:
        self._completed.setdefault(playlist_id, set()).add(item_id)
        self.marked.append((user_id, playlist_id, item_id))


class TestMarkPlaylistCompletion:
    """_async_mark_playlist_completion marks only when a playlist is queued."""

    def test_marks_audio_item_when_playlist_queued(self) -> None:
        store = _FakePlaylistStore()
        runtime = _make_runtime(
            playlist_tracking_store=store,
            queued_playlist_id="playlist-1",
        )
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "t1", "Type": "Audio"}
        )

        run(_async_mark_playlist_completion(runtime, "t1"))

        assert store.marked == [("user-1", "playlist-1", "t1")]
        assert "t1" in store.completed_ids("user-1", "playlist-1")

    def test_marks_music_video_when_playlist_queued(self) -> None:
        store = _FakePlaylistStore()
        runtime = _make_runtime(
            playlist_tracking_store=store,
            queued_playlist_id="playlist-1",
        )
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "mv1", "Type": "MusicVideo"}
        )

        run(_async_mark_playlist_completion(runtime, "mv1"))

        assert store.marked == [("user-1", "playlist-1", "mv1")]

    def test_skips_non_audio_even_when_playlist_queued(self) -> None:
        store = _FakePlaylistStore()
        runtime = _make_runtime(
            playlist_tracking_store=store,
            queued_playlist_id="playlist-1",
        )
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "movie-1", "Type": "Movie"}
        )

        run(_async_mark_playlist_completion(runtime, "movie-1"))

        assert store.marked == []

    def test_noop_when_no_playlist_queued(self) -> None:
        # The album/native-queue path: queued_playlist_id is None, so the
        # playlist store is never touched and the album flow stays unchanged.
        store = _FakePlaylistStore()
        runtime = _make_runtime(playlist_tracking_store=store)
        assert runtime.queued_playlist_id is None
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "t1", "Type": "Audio"}
        )

        run(_async_mark_playlist_completion(runtime, "t1"))

        assert store.marked == []

    def test_noop_when_store_is_none(self) -> None:
        runtime = _make_runtime(
            queued_playlist_id="playlist-1",
            playlist_tracking_store=None,
        )
        # Should not raise.
        run(_async_mark_playlist_completion(runtime, "t1"))

    def test_noop_when_no_user_id(self) -> None:
        store = _FakePlaylistStore()
        runtime = _make_runtime(
            playlist_tracking_store=store,
            queued_playlist_id="playlist-1",
            user_id="",
        )
        run(_async_mark_playlist_completion(runtime, "t1"))
        assert store.marked == []

    def test_noop_when_no_client(self) -> None:
        store = _FakePlaylistStore()
        runtime = _make_runtime(
            playlist_tracking_store=store,
            queued_playlist_id="playlist-1",
            client=None,
        )
        run(_async_mark_playlist_completion(runtime, "t1"))
        assert store.marked == []

    def test_noop_for_empty_item_id(self) -> None:
        store = _FakePlaylistStore()
        runtime = _make_runtime(
            playlist_tracking_store=store,
            queued_playlist_id="playlist-1",
        )
        run(_async_mark_playlist_completion(runtime, ""))
        assert store.marked == []

    def test_item_resolution_failure_is_swallowed(self) -> None:
        store = _FakePlaylistStore()
        runtime = _make_runtime(
            playlist_tracking_store=store,
            queued_playlist_id="playlist-1",
        )
        runtime.client.async_get_item = AsyncMock(side_effect=RuntimeError("boom"))

        run(_async_mark_playlist_completion(runtime, "t1"))

        assert store.marked == []

    def test_mark_complete_failure_is_swallowed(self) -> None:
        class _BrokenStore:
            async def mark_complete(self, user_id, playlist_id, item_id):
                raise RuntimeError("boom")

        runtime = _make_runtime(
            playlist_tracking_store=_BrokenStore(),
            queued_playlist_id="playlist-1",
        )
        runtime.client.async_get_item = AsyncMock(
            return_value={"Id": "t1", "Type": "Audio"}
        )

        run(_async_mark_playlist_completion(runtime, "t1"))
        # A storage failure must not raise into the advancement path.
