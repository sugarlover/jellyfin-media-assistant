"""Tests for the per-user, per-playlist song-completion tracking store.

Verbatim mirror of ``test_album_tracking_store.py`` (plan decision Q5):
same backend protocol, same load/save/normalize discipline, same
blank-id and schema-version guards -- keyed on ``(user id, playlist id)``
instead of ``(user id, album id)``.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Mapping

import pytest

from custom_components.jellyfin_assist.playlist_tracking_store import (
    PLAYLIST_TRACKING_SCHEMA_VERSION,
    PlaylistTrackingStore,
    PlaylistTrackingStoreError,
)

USER = "user-1"
PLAYLIST = "playlist-1"
SONG_A = "song-a"
SONG_B = "song-b"
OTHER_PLAYLIST = "playlist-2"


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class MemoryBackend:
    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self.data = deepcopy(dict(data) if data is not None else None)
        self.save_count = 0

    async def async_load(self) -> dict[str, Any] | None:
        return deepcopy(self.data)

    async def async_save(self, data: Mapping[str, Any]) -> None:
        self.data = deepcopy(dict(data))
        self.save_count += 1


class BrokenBackend(MemoryBackend):
    async def async_load(self) -> dict[str, Any] | None:
        raise OSError("storage unavailable")


def store(backend: MemoryBackend | None = None) -> tuple[PlaylistTrackingStore, MemoryBackend]:
    backend = backend or MemoryBackend()
    tracking = PlaylistTrackingStore(backend, storage_key="jellyfin_assist.playlist_tracking.entry")
    run(tracking.async_load())
    return tracking, backend


def test_mark_complete_persists_completed_song_ids() -> None:
    tracking, backend = store()
    run(tracking.mark_complete(USER, PLAYLIST, SONG_A))
    run(tracking.mark_complete(USER, PLAYLIST, SONG_B))

    assert tracking.completed_ids(USER, PLAYLIST) == {SONG_A, SONG_B}
    # Every change persists to the backend.
    assert backend.save_count == 2
    # The persisted payload is the versioned nested shape.
    assert backend.data["schema_version"] == PLAYLIST_TRACKING_SCHEMA_VERSION
    entry = backend.data["playlists"][PLAYLIST][USER]
    assert set(entry["completed_song_ids"]) == {SONG_A, SONG_B}
    assert isinstance(entry["updated_at"], float)
    assert entry["updated_at"] >= 0


def test_mark_complete_is_idempotent_for_a_song() -> None:
    tracking, backend = store()
    run(tracking.mark_complete(USER, PLAYLIST, SONG_A))
    run(tracking.mark_complete(USER, PLAYLIST, SONG_A))

    assert tracking.completed_ids(USER, PLAYLIST) == {SONG_A}
    # Re-marking the same song must not duplicate it in the stored list.
    assert backend.data["playlists"][PLAYLIST][USER]["completed_song_ids"] == [SONG_A]


def test_completion_state_is_keyed_separately_per_user_and_playlist() -> None:
    tracking, _ = store()
    run(tracking.mark_complete(USER, PLAYLIST, SONG_A))
    run(tracking.mark_complete("user-2", PLAYLIST, SONG_B))
    run(tracking.mark_complete(USER, OTHER_PLAYLIST, SONG_B))

    assert tracking.completed_ids(USER, PLAYLIST) == {SONG_A}
    assert tracking.completed_ids("user-2", PLAYLIST) == {SONG_B}
    assert tracking.completed_ids(USER, OTHER_PLAYLIST) == {SONG_B}
    # An untouched (user, playlist) pair has no completions.
    assert tracking.completed_ids("user-3", OTHER_PLAYLIST) == frozenset()


def test_save_load_round_trip_restores_state() -> None:
    tracking, backend = store()
    run(tracking.mark_complete(USER, PLAYLIST, SONG_A))
    run(tracking.mark_complete(USER, PLAYLIST, SONG_B))
    run(tracking.mark_complete("user-2", PLAYLIST, SONG_B))

    restored = PlaylistTrackingStore(backend, storage_key="jellyfin_assist.playlist_tracking.entry")
    run(restored.async_load())

    assert restored.completed_ids(USER, PLAYLIST) == {SONG_A, SONG_B}
    assert restored.completed_ids("user-2", PLAYLIST) == {SONG_B}


def test_reset_playlist_clears_only_that_users_playlist() -> None:
    tracking, _ = store()
    run(tracking.mark_complete(USER, PLAYLIST, SONG_A))
    run(tracking.mark_complete("user-2", PLAYLIST, SONG_B))
    run(tracking.mark_complete(USER, OTHER_PLAYLIST, SONG_B))

    run(tracking.reset_playlist(USER, PLAYLIST))

    assert tracking.completed_ids(USER, PLAYLIST) == frozenset()
    # The other user's completions for the same playlist survive the reset.
    assert tracking.completed_ids("user-2", PLAYLIST) == {SONG_B}
    # The other playlist for the same user survives.
    assert tracking.completed_ids(USER, OTHER_PLAYLIST) == {SONG_B}


def test_reset_playlist_then_mark_recreates_state() -> None:
    tracking, _ = store()
    run(tracking.mark_complete(USER, PLAYLIST, SONG_A))
    run(tracking.reset_playlist(USER, PLAYLIST))
    run(tracking.mark_complete(USER, PLAYLIST, SONG_B))

    assert tracking.completed_ids(USER, PLAYLIST) == {SONG_B}


def test_load_drops_unknown_ids_and_structurally_invalid_entries() -> None:
    backend = MemoryBackend(
        {
            "schema_version": PLAYLIST_TRACKING_SCHEMA_VERSION,
            "playlists": {
                # Unknown playlist id / unknown user id that contain no valid
                # entries must drop out entirely.
                "junk-playlist": {
                    "junk-user": {
                        "completed_song_ids": [],
                        "updated_at": -1,
                    }
                },
                # A valid playlist/user entry coexists with junk that is dropped.
                PLAYLIST: {
                    USER: {
                        "completed_song_ids": [SONG_A, "  ", None, 7, "song-x", SONG_B],
                        "updated_at": 123.0,
                    },
                    # Non-mapping user state is dropped.
                    "bad-user": "not-a-mapping",
                    # Missing/invalid updated_at is dropped.
                    "bad-user-2": {"completed_song_ids": [SONG_A]},
                    "bad-user-3": {"completed_song_ids": [SONG_A], "updated_at": "nope"},
                },
            },
        }
    )
    tracking, _ = store(backend)

    # Only the structurally valid (user, playlist), songs are kept; junk song
    # ids (empty, None, non-string) are dropped.
    assert tracking.completed_ids(USER, PLAYLIST) == {SONG_A, SONG_B, "song-x"}
    # The junk playlist is gone.
    assert tracking.completed_ids("junk-user", "junk-playlist") == frozenset()
    # The invalid user entries are gone.
    assert tracking.completed_ids("bad-user", PLAYLIST) == frozenset()
    assert tracking.completed_ids("bad-user-2", PLAYLIST) == frozenset()
    assert tracking.completed_ids("bad-user-3", PLAYLIST) == frozenset()


def test_load_drops_entries_when_schema_version_is_unknown() -> None:
    # An unrecognized schema version is treated as empty -- nothing is
    # trusted, so all completion state is discarded on load.
    backend = MemoryBackend(
        {
            "schema_version": 999,
            "playlists": {PLAYLIST: {USER: {"completed_song_ids": [SONG_A], "updated_at": 1.0}}},
        }
    )
    tracking, _ = store(backend)

    assert tracking.completed_ids(USER, PLAYLIST) == frozenset()


def test_load_tolerates_absent_or_non_mapping_payload() -> None:
    empty, _ = store(MemoryBackend(None))
    assert empty.completed_ids(USER, PLAYLIST) == frozenset()

    garbage, _ = store(MemoryBackend({"not": "a dict"}))
    assert garbage.completed_ids(USER, PLAYLIST) == frozenset()


def test_remarks_after_load_preserve_persisted_order() -> None:
    backend = MemoryBackend(
        {
            "schema_version": PLAYLIST_TRACKING_SCHEMA_VERSION,
            "playlists": {PLAYLIST: {USER: {"completed_song_ids": [SONG_A, SONG_B], "updated_at": 10.0}}},
        }
    )
    tracking, _ = store(backend)
    # Load order is preserved for the surviving entries.
    assert tracking.completed_ids(USER, PLAYLIST) == {SONG_A, SONG_B}
    assert backend.data["playlists"][PLAYLIST][USER]["completed_song_ids"] == [SONG_A, SONG_B]

    # A new mark appends after the loaded entries.
    run(tracking.mark_complete(USER, PLAYLIST, "song-c"))
    assert backend.data["playlists"][PLAYLIST][USER]["completed_song_ids"] == [
        SONG_A,
        SONG_B,
        "song-c",
    ]


def test_mark_complete_rejects_blank_ids() -> None:
    tracking, _ = store()
    with pytest.raises(ValueError, match="User id"):
        run(tracking.mark_complete("  ", PLAYLIST, SONG_A))
    with pytest.raises(ValueError, match="Playlist id"):
        run(tracking.mark_complete(USER, " ", SONG_A))
    with pytest.raises(ValueError, match="Song id"):
        run(tracking.mark_complete(USER, PLAYLIST, "   "))
    # A blank id never creates state.
    assert tracking.completed_ids(USER, PLAYLIST) == frozenset()


def test_completed_ids_rejects_blank_keys_without_state() -> None:
    tracking, _ = store()
    with pytest.raises(ValueError, match="User id"):
        tracking.completed_ids("", PLAYLIST)
    with pytest.raises(ValueError, match="Playlist id"):
        tracking.completed_ids(USER, "")


def test_storage_load_failure_uses_playlist_tracking_error_boundary() -> None:
    tracking = PlaylistTrackingStore(BrokenBackend(), storage_key="jellyfin_assist.playlist_tracking.entry")

    with pytest.raises(PlaylistTrackingStoreError, match="Could not load playlist tracking storage"):
        run(tracking.async_load())
