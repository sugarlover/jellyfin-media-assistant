"""Persistent per-user, per-playlist song-completion tracking store.

This module is the storage foundation for the JMA playlist-track-tracking
feature (plan decision Q5). It persists, for each (Jellyfin user id,
playlist id) pair, the set of song ids the user has completed listening to,
plus a timestamp of the last change.

The shape is a versioned HA Store payload::

    {
        "schema_version": 1,
        "playlists": {
            "<playlist_id>": {
                "<user_id>": {
                    "completed_song_ids": ["<song_id>", ...],
                    "updated_at": <epoch-seconds float>,
                },
            },
        },
    }

Only boolean completion is stored (no song position/time). Loading the
payload drops any entry that does not match the expected nested shape --
unknown playlist ids, unknown user ids, non-string song ids,
missing/invalid ``updated_at`` -- so a corrupted or older-version store file
degrades safely rather than corrupting playback.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import time
from typing import Any, Protocol

PLAYLIST_TRACKING_SCHEMA_VERSION = 1


class PlaylistTrackingStoreBackend(Protocol):
    """Minimal Home Assistant Store-compatible backend."""

    async def async_load(self) -> Mapping[str, Any] | None: ...

    async def async_save(self, data: Mapping[str, Any]) -> None: ...


class PlaylistTrackingStoreError(RuntimeError):
    """Raised when playlist-completion state cannot be loaded or saved."""


def _text(value: Any) -> str:
    stripped = "" if value is None else str(value).strip()
    return stripped


def _normalized_playlist_entry(raw: Any) -> dict[str, Any] | None:
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


def _normalized_playlists(raw: Any) -> dict[str, Any]:
    """Reduce a raw ``"playlists"`` payload to only structurally valid entries."""

    if not isinstance(raw, Mapping):
        return {}
    playlists: dict[str, Any] = {}
    for raw_playlist, raw_playlist_state in raw.items():
        playlist_id = _text(raw_playlist)
        if not playlist_id:
            continue
        normalized = _normalized_playlist_entry(raw_playlist_state)
        # A playlist entry with zero valid user states is unknown/empty: drop it.
        if normalized:
            playlists[playlist_id] = normalized
    return playlists


def _load_document(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a loaded payload, dropping everything for an unknown version."""

    playlists: dict[str, Any] = {}
    # A payload without the current schema version is not trusted: nothing is
    # carried forward, so a legacy/corrupted file degrades to a clean state.
    if isinstance(raw, Mapping) and raw.get("schema_version") == PLAYLIST_TRACKING_SCHEMA_VERSION:
        playlists = _normalized_playlists(raw.get("playlists"))
    return {"schema_version": PLAYLIST_TRACKING_SCHEMA_VERSION, "playlists": playlists}


class PlaylistTrackingStore:
    """Persist per-(user, playlist) completed-song-id sets in HA storage."""

    def __init__(self, backend: PlaylistTrackingStoreBackend, *, storage_key: str) -> None:
        self._backend = backend
        self.storage_key = storage_key
        self._data: dict[str, Any] = {
            "schema_version": PLAYLIST_TRACKING_SCHEMA_VERSION,
            "playlists": {},
        }
        self._lock = asyncio.Lock()
        self.loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._backend.async_load()
        except Exception as err:  # pragma: no cover - HA storage boundary
            raise PlaylistTrackingStoreError(
                "Could not load playlist tracking storage"
            ) from err
        self._data = _load_document(raw)
        self.loaded = True

    async def _save(self) -> None:
        try:
            await self._backend.async_save(self._data)
        except Exception as err:  # pragma: no cover - HA storage boundary
            raise PlaylistTrackingStoreError(
                "Could not save playlist tracking storage"
            ) from err

    def _entry(self, user_id: str, playlist_id: str) -> dict[str, Any]:
        playlists = self._data["playlists"]
        playlist_state = playlists.get(playlist_id)
        if not isinstance(playlist_state, dict):
            playlist_state = {}
            playlists[playlist_id] = playlist_state
        entry = playlist_state.get(user_id)
        if not isinstance(entry, dict):
            entry = {"completed_song_ids": [], "updated_at": 0.0}
            playlist_state[user_id] = entry
        return entry

    async def mark_complete(self, user_id: str, playlist_id: str, song_id: str) -> None:
        """Mark ``song_id`` completed for (``user_id``, ``playlist_id``)."""

        normalized_user = _text(user_id)
        normalized_playlist = _text(playlist_id)
        normalized_song = _text(song_id)
        if not normalized_user:
            raise ValueError("User id is required")
        if not normalized_playlist:
            raise ValueError("Playlist id is required")
        if not normalized_song:
            raise ValueError("Song id is required")
        async with self._lock:
            entry = self._entry(normalized_user, normalized_playlist)
            if normalized_song not in entry["completed_song_ids"]:
                entry["completed_song_ids"].append(normalized_song)
            entry["updated_at"] = time.time()
            await self._save()

    async def reset_playlist(self, user_id: str, playlist_id: str) -> None:
        """Clear all completion state for (``user_id``, ``playlist_id``)."""

        normalized_user = _text(user_id)
        normalized_playlist = _text(playlist_id)
        if not normalized_user:
            raise ValueError("User id is required")
        if not normalized_playlist:
            raise ValueError("Playlist id is required")
        async with self._lock:
            playlists = self._data["playlists"]
            playlist_state = playlists.get(normalized_playlist)
            if isinstance(playlist_state, dict):
                playlist_state.pop(normalized_user, None)
                if not playlist_state:
                    playlists.pop(normalized_playlist, None)
            await self._save()

    def completed_ids(self, user_id: str, playlist_id: str) -> frozenset[str]:
        """Return the set of completed song ids for (``user_id``, ``playlist_id``)."""

        normalized_user = _text(user_id)
        normalized_playlist = _text(playlist_id)
        if not normalized_user:
            raise ValueError("User id is required")
        if not normalized_playlist:
            raise ValueError("Playlist id is required")
        playlists = self._data["playlists"]
        playlist_state = playlists.get(normalized_playlist)
        if not isinstance(playlist_state, dict):
            return frozenset()
        entry = playlist_state.get(normalized_user)
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
    "PlaylistTrackingStore",
    "PlaylistTrackingStoreBackend",
    "PlaylistTrackingStoreError",
    "PLAYLIST_TRACKING_SCHEMA_VERSION",
]
