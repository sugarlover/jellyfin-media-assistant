"""Persistent per-user, per-album song-completion tracking store.

This module is the storage foundation for the JMA album-track-tracking
feature (plan decision D1/D5). It persists, for each (Jellyfin user id,
album id) pair, the set of song ids the user has completed listening to,
plus a timestamp of the last change.

The shape is a versioned HA Store payload::

    {
        "schema_version": 1,
        "albums": {
            "<album_id>": {
                "<user_id>": {
                    "completed_song_ids": ["<song_id>", ...],
                    "updated_at": <epoch-seconds float>,
                },
            },
        },
    }

Only boolean completion is stored (no song position/time). Loading the
payload drops any entry that does not match the expected nested shape --
unknown album ids, unknown user ids, non-string song ids, missing/invalid
``updated_at`` -- so a corrupted or older-version store file degrades safely
rather than corrupting playback.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import time
from typing import Any, Protocol

ALBUM_TRACKING_SCHEMA_VERSION = 1


class AlbumTrackingStoreBackend(Protocol):
    """Minimal Home Assistant Store-compatible backend."""

    async def async_load(self) -> Mapping[str, Any] | None: ...

    async def async_save(self, data: Mapping[str, Any]) -> None: ...


class AlbumTrackingStoreError(RuntimeError):
    """Raised when album-completion state cannot be loaded or saved."""


def _text(value: Any) -> str:
    stripped = "" if value is None else str(value).strip()
    return stripped


def _normalized_album_entry(raw: Any) -> dict[str, Any] | None:
    """Return a normalized ``{user_id: {...}}`` dict, or ``None`` if invalid."""

    if not isinstance(raw, Mapping):
        return None
    users: dict[str, Any] = {}
    for raw_user, raw_state in raw.items():
        user_id = _text(raw_user)
        if not user_id or not isinstance(raw_state, Mapping):
            continue
        completed = raw_state.get("completed_song_ids")
        if not isinstance(completed, list):
            continue
        song_ids = [
            candidate
            for candidate in completed
            if isinstance(candidate, str) and candidate.strip()
        ]
        updated_at = raw_state.get("updated_at")
        if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)):
            continue
        if updated_at < 0:
            continue
        users[user_id] = {
            "completed_song_ids": song_ids,
            "updated_at": float(updated_at),
        }
    return users


def _normalized_albums(raw: Any) -> dict[str, Any]:
    """Reduce a raw ``"albums"`` payload to only structurally valid entries."""

    if not isinstance(raw, Mapping):
        return {}
    albums: dict[str, Any] = {}
    for raw_album, raw_album_state in raw.items():
        album_id = _text(raw_album)
        if not album_id:
            continue
        normalized = _normalized_album_entry(raw_album_state)
        # An album entry with zero valid user states is unknown/empty: drop it.
        if normalized:
            albums[album_id] = normalized
    return albums


def _load_document(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a loaded payload, dropping everything for an unknown version."""

    albums: dict[str, Any] = {}
    # A payload without the current schema version is not trusted: nothing is
    # carried forward, so a legacy/corrupted file degrades to a clean state.
    if isinstance(raw, Mapping) and raw.get("schema_version") == ALBUM_TRACKING_SCHEMA_VERSION:
        albums = _normalized_albums(raw.get("albums"))
    return {"schema_version": ALBUM_TRACKING_SCHEMA_VERSION, "albums": albums}


class AlbumTrackingStore:
    """Persist per-(user, album) completed-song-id sets in HA storage."""

    def __init__(self, backend: AlbumTrackingStoreBackend, *, storage_key: str) -> None:
        self._backend = backend
        self.storage_key = storage_key
        self._data: dict[str, Any] = {
            "schema_version": ALBUM_TRACKING_SCHEMA_VERSION,
            "albums": {},
        }
        self._lock = asyncio.Lock()
        self.loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._backend.async_load()
        except Exception as err:  # pragma: no cover - HA storage boundary
            raise AlbumTrackingStoreError(
                "Could not load album tracking storage"
            ) from err
        self._data = _load_document(raw)
        self.loaded = True

    async def _save(self) -> None:
        try:
            await self._backend.async_save(self._data)
        except Exception as err:  # pragma: no cover - HA storage boundary
            raise AlbumTrackingStoreError(
                "Could not save album tracking storage"
            ) from err

    def _entry(self, user_id: str, album_id: str) -> dict[str, Any]:
        albums = self._data["albums"]
        album_state = albums.get(album_id)
        if not isinstance(album_state, dict):
            album_state = {}
            albums[album_id] = album_state
        entry = album_state.get(user_id)
        if not isinstance(entry, dict):
            entry = {"completed_song_ids": [], "updated_at": 0.0}
            album_state[user_id] = entry
        return entry

    async def mark_complete(self, user_id: str, album_id: str, song_id: str) -> None:
        """Mark ``song_id`` completed for (``user_id``, ``album_id``)."""

        normalized_user = _text(user_id)
        normalized_album = _text(album_id)
        normalized_song = _text(song_id)
        if not normalized_user:
            raise ValueError("User id is required")
        if not normalized_album:
            raise ValueError("Album id is required")
        if not normalized_song:
            raise ValueError("Song id is required")
        async with self._lock:
            entry = self._entry(normalized_user, normalized_album)
            if normalized_song not in entry["completed_song_ids"]:
                entry["completed_song_ids"].append(normalized_song)
            entry["updated_at"] = time.time()
            await self._save()

    async def reset_album(self, user_id: str, album_id: str) -> None:
        """Clear all completion state for (``user_id``, ``album_id``)."""

        normalized_user = _text(user_id)
        normalized_album = _text(album_id)
        if not normalized_user:
            raise ValueError("User id is required")
        if not normalized_album:
            raise ValueError("Album id is required")
        async with self._lock:
            albums = self._data["albums"]
            album_state = albums.get(normalized_album)
            if isinstance(album_state, dict):
                album_state.pop(normalized_user, None)
                if not album_state:
                    albums.pop(normalized_album, None)
            await self._save()

    def completed_ids(self, user_id: str, album_id: str) -> frozenset[str]:
        """Return the set of completed song ids for (``user_id``, ``album_id``)."""

        normalized_user = _text(user_id)
        normalized_album = _text(album_id)
        if not normalized_user:
            raise ValueError("User id is required")
        if not normalized_album:
            raise ValueError("Album id is required")
        albums = self._data["albums"]
        album_state = albums.get(normalized_album)
        if not isinstance(album_state, dict):
            return frozenset()
        entry = album_state.get(normalized_user)
        if not isinstance(entry, dict):
            return frozenset()
        completed = entry.get("completed_song_ids")
        if not isinstance(completed, list):
            return frozenset()
        return frozenset(
            candidate for candidate in completed
            if isinstance(candidate, str) and candidate.strip()
        )


__all__ = [
    "AlbumTrackingStore",
    "AlbumTrackingStoreBackend",
    "AlbumTrackingStoreError",
    "ALBUM_TRACKING_SCHEMA_VERSION",
]
