"""Persistent native queue storage for Jellyfin Media Assistant."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import random
from typing import Any, Protocol


class QueueStoreBackend(Protocol):
    """Minimal Home Assistant Store-compatible backend."""

    async def async_load(self) -> Mapping[str, Any] | None: ...

    async def async_save(self, data: Mapping[str, Any]) -> None: ...


class QueueStoreError(RuntimeError):
    """Raised when native queue state cannot be loaded or saved."""


VALID_MEDIA_TYPES = {
    "Audio",
    "Episode",
    "Movie",
    "Series",
    "MusicAlbum",
    "MusicArtist",
    "MusicVideo",
    "Playlist",
    "Video",
    "BoxSet",
}


def _default_player_state() -> dict[str, Any]:
    return {
        "queue": [],
        "current_index": None,
        "current": None,
        "history": [],
        "last_completed": None,
        "repeat_item": False,
        "repeat_queue": False,
    }


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> int | str:
    if value in (None, ""):
        return ""
    try:
        return int(value)
    except (TypeError, ValueError):
        return ""


def _normalize_item(item: Mapping[str, Any]) -> dict[str, Any]:
    item_id = _text(item.get("id"))
    name = _text(item.get("name"))
    media_type = _text(item.get("type"))
    if not item_id:
        raise ValueError("Queue item requires an id.")
    if not name:
        raise ValueError("Queue item requires a name.")
    if media_type and media_type not in VALID_MEDIA_TYPES:
        raise ValueError(f"Unsupported media type '{media_type}'.")
    return {
        "id": item_id,
        "name": name,
        "type": media_type,
        "artist": _text(item.get("artist")),
        "album": _text(item.get("album")),
        "series": _text(item.get("series")),
        "season": _number(item.get("season")),
        "episode": _number(item.get("episode")),
    }


def _normalize_index(value: Any, queue_length: int) -> int | None:
    if value is None:
        return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if 0 <= index < queue_length else None


def _find_item_index(queue: list[Any], item: Any) -> int | None:
    if not isinstance(item, Mapping):
        return None
    item_id = _text(item.get("id"))
    if not item_id:
        return None
    for index, candidate in enumerate(queue):
        if isinstance(candidate, Mapping) and _text(candidate.get("id")) == item_id:
            return index
    return None


def _normalize_player_state(raw: Any) -> dict[str, Any]:
    state = dict(raw) if isinstance(raw, Mapping) else _default_player_state()
    queue = state.get("queue")
    if not isinstance(queue, list):
        queue = []
    queue = [dict(item) for item in queue if isinstance(item, Mapping)]
    state["queue"] = queue

    history = state.get("history")
    state["history"] = (
        [dict(item) for item in history if isinstance(item, Mapping)]
        if isinstance(history, list)
        else []
    )
    state.setdefault("last_completed", None)
    state["repeat_item"] = _normalize_bool(state.get("repeat_item"))
    state["repeat_queue"] = _normalize_bool(state.get("repeat_queue"))
    if state["repeat_item"]:
        state["repeat_queue"] = False

    if "current_index" not in state:
        if queue:
            found = _find_item_index(queue, state.get("current"))
            state["current_index"] = found if found is not None else 0
        else:
            state["current_index"] = None

    state["current_index"] = _normalize_index(state.get("current_index"), len(queue))
    state["current"] = (
        queue[state["current_index"]] if state["current_index"] is not None else None
    )
    return state


def _previous(state: Mapping[str, Any]) -> dict[str, Any] | None:
    last = state.get("last_completed")
    if isinstance(last, Mapping):
        return dict(last)
    index = state.get("current_index")
    queue = state.get("queue", [])
    if isinstance(index, int) and index > 0 and isinstance(queue, list):
        candidate = queue[index - 1]
        return dict(candidate) if isinstance(candidate, Mapping) else None
    return None


def _next(state: Mapping[str, Any]) -> dict[str, Any] | None:
    index = state.get("current_index")
    queue = state.get("queue", [])
    if not isinstance(index, int) or not isinstance(queue, list):
        return None
    next_index = index + 1
    if next_index >= len(queue):
        return None
    candidate = queue[next_index]
    return dict(candidate) if isinstance(candidate, Mapping) else None


def _upcoming(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    index = state.get("current_index")
    queue = state.get("queue", [])
    if not isinstance(index, int) or not isinstance(queue, list):
        return []
    return [dict(item) for item in queue[index + 1 :] if isinstance(item, Mapping)]


def _payload(
    state: Mapping[str, Any],
    player: str,
    *,
    success: bool = True,
    status: str = "ok",
    message: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    queue = [dict(item) for item in state.get("queue", []) if isinstance(item, Mapping)]
    history = [dict(item) for item in state.get("history", []) if isinstance(item, Mapping)]
    current = state.get("current")
    current = dict(current) if isinstance(current, Mapping) else None
    upcoming = _upcoming(state)
    result: dict[str, Any] = {
        "success": success,
        "status": status,
        "player": player,
        "count": len(queue),
        "current_index": state.get("current_index"),
        "current": current,
        "previous": _previous(state),
        "last_completed": (
            dict(state["last_completed"])
            if isinstance(state.get("last_completed"), Mapping)
            else None
        ),
        "next": _next(state),
        "queue": queue,
        "items": queue,
        "history": history,
        "completed_count": len(history),
        "upcoming": upcoming,
        "upcoming_count": len(upcoming),
        "repeat_item": bool(state.get("repeat_item", False)),
        "repeat_queue": bool(state.get("repeat_queue", False)),
    }
    if message is not None:
        result["message"] = message
    result.update(extra)
    return result


def _response(content: Mapping[str, Any], *, status: int = 200) -> dict[str, Any]:
    return {
        "status": status,
        "content": dict(content),
        "headers": {"Server": "jellyfin-assist-native-queue/1"},
    }


class NativeQueueStore:
    """Persist per-player queue state in Home Assistant's integration storage."""

    def __init__(self, backend: QueueStoreBackend, *, storage_key: str) -> None:
        self._backend = backend
        self.storage_key = storage_key
        self._data: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self.loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._backend.async_load()
        except Exception as err:  # pragma: no cover - HA storage boundary
            raise QueueStoreError("Could not load native queue storage") from err
        self._data = dict(raw) if isinstance(raw, Mapping) else {}
        for player, state in list(self._data.items()):
            self._data[player] = _normalize_player_state(state)
        self.loaded = True

    async def _save(self) -> None:
        try:
            await self._backend.async_save(self._data)
        except Exception as err:  # pragma: no cover - HA storage boundary
            raise QueueStoreError("Could not save native queue storage") from err

    def _state(self, player: str) -> dict[str, Any]:
        normalized_player = _text(player)
        if not normalized_player:
            raise ValueError("Media player is required")
        state = _normalize_player_state(self._data.get(normalized_player))
        self._data[normalized_player] = state
        return state

    async def async_get(self, player: str) -> dict[str, Any]:
        async with self._lock:
            state = self._state(player)
            await self._save()
            return _response(_payload(state, player, status="ok"))

    async def async_add(self, player: str, item: Mapping[str, Any]) -> dict[str, Any]:
        normalized_item = _normalize_item(item)
        async with self._lock:
            state = self._state(player)
            state["queue"].append(normalized_item)
            if state["current_index"] is None:
                state["current_index"] = len(state["queue"]) - 1
                state["current"] = normalized_item
            await self._save()
            return _response(
                _payload(
                    state,
                    player,
                    status="added",
                    message=f"Added {normalized_item['name']} to the queue.",
                    added=normalized_item,
                )
            )

    async def async_next(self, player: str) -> dict[str, Any]:
        async with self._lock:
            state = self._state(player)
            if not state["queue"]:
                state["current_index"] = None
                state["current"] = None
                await self._save()
                return _response(
                    _payload(
                        state,
                        player,
                        success=False,
                        status="empty",
                        message="The queue is empty.",
                    )
                )
            if state["current_index"] is None:
                await self._save()
                return _response(
                    _payload(
                        state,
                        player,
                        success=False,
                        status="complete",
                        message="The queue has already completed.",
                    )
                )

            finished = dict(state["queue"][state["current_index"]])
            state["last_completed"] = finished
            if state["repeat_item"]:
                state["current"] = finished
            elif state["current_index"] + 1 < len(state["queue"]):
                state["history"].append(finished)
                state["current_index"] += 1
                state["current"] = state["queue"][state["current_index"]]
            elif state["repeat_queue"]:
                state["history"] = []
                state["current_index"] = 0
                state["current"] = state["queue"][0]
            else:
                state["history"].append(finished)
                state["current_index"] = None
                state["current"] = None
            await self._save()
            return _response(
                _payload(
                    state,
                    player,
                    status="advanced",
                    message=f"Advanced past {finished['name']}.",
                    finished=finished,
                    completed=finished,
                )
            )

    async def async_remove(self, player: str, position: int) -> dict[str, Any]:
        async with self._lock:
            state = self._state(player)
            if position < 1 or position > len(state["queue"]):
                return _response(
                    {
                        "success": False,
                        "status": "invalid_position",
                        "message": f"Queue position {position} does not exist.",
                        "player": player,
                        "count": len(state["queue"]),
                        "queue": list(state["queue"]),
                    },
                    status=400,
                )
            removed_index = position - 1
            current_index = state["current_index"]
            removed = state["queue"].pop(removed_index)
            if current_index is not None:
                if removed_index < current_index:
                    state["current_index"] = current_index - 1
                elif removed_index == current_index:
                    state["current_index"] = (
                        removed_index if removed_index < len(state["queue"]) else None
                    )
            state["current_index"] = _normalize_index(
                state.get("current_index"), len(state["queue"])
            )
            state["current"] = (
                state["queue"][state["current_index"]]
                if state["current_index"] is not None
                else None
            )
            await self._save()
            return _response(
                _payload(
                    state,
                    player,
                    status="removed",
                    message=f"Removed {removed['name']} from the queue.",
                    removed=removed,
                )
            )

    async def async_clear(self, player: str) -> dict[str, Any]:
        async with self._lock:
            state = self._state(player)
            state.update(
                queue=[],
                current_index=None,
                current=None,
                history=[],
                last_completed=None,
            )
            await self._save()
            return _response(
                _payload(state, player, status="cleared", message="Queue cleared.")
            )

    async def async_settings(
        self,
        player: str,
        *,
        repeat_item: bool,
        repeat_queue: bool,
    ) -> dict[str, Any]:
        async with self._lock:
            state = self._state(player)
            state["repeat_item"] = _normalize_bool(repeat_item)
            state["repeat_queue"] = _normalize_bool(repeat_queue)
            if state["repeat_item"]:
                state["repeat_queue"] = False
            elif state["repeat_queue"]:
                state["repeat_item"] = False
            await self._save()
            return _response(
                _payload(
                    state,
                    player,
                    status="settings_updated",
                    message="Queue settings updated.",
                )
            )

    async def async_shuffle(self, player: str) -> dict[str, Any]:
        async with self._lock:
            state = self._state(player)
            if not state["queue"]:
                state["current_index"] = None
                state["current"] = None
                await self._save()
                return _response(
                    _payload(
                        state,
                        player,
                        success=False,
                        status="empty",
                        message="The queue is empty.",
                        shuffled_count=0,
                        original_upcoming=[],
                        shuffled_upcoming=[],
                        order_changed=False,
                    )
                )
            if state["current_index"] is None:
                await self._save()
                return _response(
                    _payload(
                        state,
                        player,
                        success=False,
                        status="complete",
                        message="The queue has already completed.",
                        shuffled_count=0,
                        original_upcoming=[],
                        shuffled_upcoming=[],
                        order_changed=False,
                    )
                )
            index = state["current_index"]
            original = [dict(item) for item in state["queue"][index + 1 :]]
            if len(original) < 2:
                await self._save()
                message = (
                    "There is only one upcoming item, so the queue order did not change."
                    if len(original) == 1
                    else "There are no upcoming items to shuffle."
                )
                return _response(
                    _payload(
                        state,
                        player,
                        status="unchanged",
                        message=message,
                        shuffled_count=0,
                        original_upcoming=original,
                        shuffled_upcoming=original,
                        order_changed=False,
                    )
                )
            shuffled = list(original)
            random.SystemRandom().shuffle(shuffled)
            if shuffled == original:
                shuffled = shuffled[1:] + shuffled[:1]
            state["queue"] = state["queue"][: index + 1] + shuffled
            state["current"] = state["queue"][index]
            await self._save()
            return _response(
                _payload(
                    state,
                    player,
                    status="shuffled",
                    message=f"Shuffled {len(shuffled)} upcoming items.",
                    shuffled_count=len(shuffled),
                    original_upcoming=original,
                    shuffled_upcoming=shuffled,
                    order_changed=True,
                )
            )


__all__ = ["NativeQueueStore", "QueueStoreBackend", "QueueStoreError"]
