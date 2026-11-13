"""Tests for the per-user, per-album song-completion tracking store."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Mapping

import pytest

from custom_components.jellyfin_assist.album_tracking_store import (
    ALBUM_TRACKING_SCHEMA_VERSION,
    AlbumTrackingStore,
    AlbumTrackingStoreError,
)

USER = "user-1"
ALBUM = "album-1"
SONG_A = "song-a"
SONG_B = "song-b"
OTHER_ALBUM = "album-2"


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


def store(backend: MemoryBackend | None = None) -> tuple[AlbumTrackingStore, MemoryBackend]:
    backend = backend or MemoryBackend()
    tracking = AlbumTrackingStore(backend, storage_key="jellyfin_assist.album_tracking.entry")
    run(tracking.async_load())
    return tracking, backend


def test_mark_complete_persists_completed_song_ids() -> None:
    tracking, backend = store()
    run(tracking.mark_complete(USER, ALBUM, SONG_A))
    run(tracking.mark_complete(USER, ALBUM, SONG_B))

    assert tracking.completed_ids(USER, ALBUM) == {SONG_A, SONG_B}
    # Every change persists to the backend.
    assert backend.save_count == 2
    # The persisted payload is the versioned nested shape.
    assert backend.data["schema_version"] == ALBUM_TRACKING_SCHEMA_VERSION
    entry = backend.data["albums"][ALBUM][USER]
    assert set(entry["completed_song_ids"]) == {SONG_A, SONG_B}
    assert isinstance(entry["updated_at"], float)
    assert entry["updated_at"] >= 0


def test_mark_complete_is_idempotent_for_a_song() -> None:
    tracking, backend = store()
    run(tracking.mark_complete(USER, ALBUM, SONG_A))
    run(tracking.mark_complete(USER, ALBUM, SONG_A))

    assert tracking.completed_ids(USER, ALBUM) == {SONG_A}
    # Re-marking the same song must not duplicate it in the stored list.
    assert backend.data["albums"][ALBUM][USER]["completed_song_ids"] == [SONG_A]


def test_completion_state_is_keyed_separately_per_user_and_album() -> None:
    tracking, _ = store()
    run(tracking.mark_complete(USER, ALBUM, SONG_A))
    run(tracking.mark_complete("user-2", ALBUM, SONG_B))
    run(tracking.mark_complete(USER, OTHER_ALBUM, SONG_B))

    assert tracking.completed_ids(USER, ALBUM) == {SONG_A}
    assert tracking.completed_ids("user-2", ALBUM) == {SONG_B}
    assert tracking.completed_ids(USER, OTHER_ALBUM) == {SONG_B}
    # An untouched (user, album) pair has no completions.
    assert tracking.completed_ids("user-3", OTHER_ALBUM) == frozenset()


def test_save_load_round_trip_restores_state() -> None:
    tracking, backend = store()
    run(tracking.mark_complete(USER, ALBUM, SONG_A))
    run(tracking.mark_complete(USER, ALBUM, SONG_B))
    run(tracking.mark_complete("user-2", ALBUM, SONG_B))

    restored = AlbumTrackingStore(backend, storage_key="jellyfin_assist.album_tracking.entry")
    run(restored.async_load())

    assert restored.completed_ids(USER, ALBUM) == {SONG_A, SONG_B}
    assert restored.completed_ids("user-2", ALBUM) == {SONG_B}


def test_reset_album_clears_only_that_users_album() -> None:
    tracking, _ = store()
    run(tracking.mark_complete(USER, ALBUM, SONG_A))
    run(tracking.mark_complete("user-2", ALBUM, SONG_B))
    run(tracking.mark_complete(USER, OTHER_ALBUM, SONG_B))

    run(tracking.reset_album(USER, ALBUM))

    assert tracking.completed_ids(USER, ALBUM) == frozenset()
    # The other user's completions for the same album survive the reset.
    assert tracking.completed_ids("user-2", ALBUM) == {SONG_B}
    # The other album for the same user survives.
    assert tracking.completed_ids(USER, OTHER_ALBUM) == {SONG_B}


def test_reset_album_then_mark_recreates_state() -> None:
    tracking, _ = store()
    run(tracking.mark_complete(USER, ALBUM, SONG_A))
    run(tracking.reset_album(USER, ALBUM))
    run(tracking.mark_complete(USER, ALBUM, SONG_B))

    assert tracking.completed_ids(USER, ALBUM) == {SONG_B}


def test_load_drops_unknown_ids_and_structurally_invalid_entries() -> None:
    backend = MemoryBackend(
        {
            "schema_version": ALBUM_TRACKING_SCHEMA_VERSION,
            "albums": {
                # Unknown album id / unknown user id that contain no valid
                # entries must drop out entirely.
                "junk-album": {
                    "junk-user": {
                        "completed_song_ids": [],
                        "updated_at": -1,
                    }
                },
                # A valid album/user entry coexists with junk that is dropped.
                ALBUM: {
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

    # Only the structurally valid (user, album), songs are kept; junk song
    # ids (empty, None, non-string) are dropped.
    assert tracking.completed_ids(USER, ALBUM) == {SONG_A, SONG_B, "song-x"}
    # The junk album is gone.
    assert tracking.completed_ids("junk-user", "junk-album") == frozenset()
    # The invalid user entries are gone.
    assert tracking.completed_ids("bad-user", ALBUM) == frozenset()
    assert tracking.completed_ids("bad-user-2", ALBUM) == frozenset()
    assert tracking.completed_ids("bad-user-3", ALBUM) == frozenset()


def test_load_drops_entries_when_schema_version_is_unknown() -> None:
    # An unrecognized schema version is treated as empty -- nothing is
    # trusted, so all completion state is discarded on load.
    backend = MemoryBackend(
        {
            "schema_version": 999,
            "albums": {ALBUM: {USER: {"completed_song_ids": [SONG_A], "updated_at": 1.0}}},
        }
    )
    tracking, _ = store(backend)

    assert tracking.completed_ids(USER, ALBUM) == frozenset()


def test_load_tolerates_absent_or_non_mapping_payload() -> None:
    empty, _ = store(MemoryBackend(None))
    assert empty.completed_ids(USER, ALBUM) == frozenset()

    garbage, _ = store(MemoryBackend({"not": "a dict"}))
    assert garbage.completed_ids(USER, ALBUM) == frozenset()


def test_remarks_after_load_preserve_persisted_order() -> None:
    backend = MemoryBackend(
        {
            "schema_version": ALBUM_TRACKING_SCHEMA_VERSION,
            "albums": {ALBUM: {USER: {"completed_song_ids": [SONG_A, SONG_B], "updated_at": 10.0}}},
        }
    )
    tracking, _ = store(backend)
    # Load order is preserved for the surviving entries.
    assert tracking.completed_ids(USER, ALBUM) == {SONG_A, SONG_B}
    assert backend.data["albums"][ALBUM][USER]["completed_song_ids"] == [SONG_A, SONG_B]

    # A new mark appends after the loaded entries.
    run(tracking.mark_complete(USER, ALBUM, "song-c"))
    assert backend.data["albums"][ALBUM][USER]["completed_song_ids"] == [
        SONG_A,
        SONG_B,
        "song-c",
    ]


def test_mark_complete_rejects_blank_ids() -> None:
    tracking, _ = store()
    with pytest.raises(ValueError, match="User id"):
        run(tracking.mark_complete("  ", ALBUM, SONG_A))
    with pytest.raises(ValueError, match="Album id"):
        run(tracking.mark_complete(USER, " ", SONG_A))
    with pytest.raises(ValueError, match="Song id"):
        run(tracking.mark_complete(USER, ALBUM, "   "))
    # A blank id never creates state.
    assert tracking.completed_ids(USER, ALBUM) == frozenset()


def test_completed_ids_rejects_blank_keys_without_state() -> None:
    tracking, _ = store()
    with pytest.raises(ValueError, match="User id"):
        tracking.completed_ids("", ALBUM)
    with pytest.raises(ValueError, match="Album id"):
        tracking.completed_ids(USER, "")


def test_storage_load_failure_uses_album_tracking_error_boundary() -> None:
    tracking = AlbumTrackingStore(BrokenBackend(), storage_key="jellyfin_assist.album_tracking.entry")

    with pytest.raises(AlbumTrackingStoreError, match="Could not load album tracking storage"):
        run(tracking.async_load())
