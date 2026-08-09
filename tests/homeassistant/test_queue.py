"""Tests for the native persistent queue store."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Mapping

import pytest

from custom_components.jellyfin_assist.queue_store import NativeQueueStore, QueueStoreError


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class MemoryBackend:
    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self.data = deepcopy(dict(data or {}))
        self.save_count = 0

    async def async_load(self) -> dict[str, Any] | None:
        return deepcopy(self.data) if self.data else None

    async def async_save(self, data: Mapping[str, Any]) -> None:
        self.data = deepcopy(dict(data))
        self.save_count += 1


class BrokenBackend(MemoryBackend):
    async def async_load(self) -> dict[str, Any] | None:
        raise OSError("storage unavailable")


ITEM_1 = {
    "id": "song-1",
    "name": "Bullets",
    "type": "Audio",
    "artist": "Creed",
    "album": "Weathered",
}
ITEM_2 = {
    "id": "song-2",
    "name": "Freedom Fighter",
    "type": "Audio",
    "artist": "Creed",
    "album": "Weathered",
}
ITEM_3 = {
    "id": "song-3",
    "name": "Who's Got My Back?",
    "type": "Audio",
    "artist": "Creed",
    "album": "Weathered",
}
PLAYER = "media_player.attic_tv"


def store(backend: MemoryBackend | None = None) -> tuple[NativeQueueStore, MemoryBackend]:
    backend = backend or MemoryBackend()
    queue = NativeQueueStore(backend, storage_key="jellyfin_assist.queue.entry")
    run(queue.async_load())
    return queue, backend


def content(response: dict[str, Any]) -> dict[str, Any]:
    assert response["status"] == 200
    assert response["headers"]["Server"] == "jellyfin-assist-native-queue/1"
    return response["content"]


def test_empty_queue_preserves_existing_response_contract() -> None:
    queue, backend = store()

    body = content(run(queue.async_get(PLAYER)))

    assert body == {
        "success": True,
        "status": "ok",
        "player": PLAYER,
        "count": 0,
        "current_index": None,
        "current": None,
        "previous": None,
        "last_completed": None,
        "next": None,
        "queue": [],
        "items": [],
        "history": [],
        "completed_count": 0,
        "upcoming": [],
        "upcoming_count": 0,
        "repeat_item": False,
        "repeat_queue": False,
    }
    assert backend.save_count == 1


def test_add_and_next_preserve_session_history_and_current_item() -> None:
    queue, _ = store()
    content(run(queue.async_add(PLAYER, ITEM_1)))
    added = content(run(queue.async_add(PLAYER, ITEM_2)))

    assert added["current"] == {
        **ITEM_1,
        "series": "",
        "season": "",
        "episode": "",
    }
    assert added["next"]["id"] == "song-2"
    assert added["upcoming_count"] == 1

    advanced = content(run(queue.async_next(PLAYER)))
    assert advanced["status"] == "advanced"
    assert advanced["completed"]["id"] == "song-1"
    assert advanced["last_completed"]["id"] == "song-1"
    assert advanced["current"]["id"] == "song-2"
    assert advanced["history"][0]["id"] == "song-1"
    assert advanced["completed_count"] == 1

    finished = content(run(queue.async_next(PLAYER)))
    assert finished["current"] is None
    assert finished["current_index"] is None
    assert finished["completed_count"] == 2
    assert finished["last_completed"]["id"] == "song-2"
    assert finished["count"] == 2


def test_repeat_item_and_repeat_queue_match_external_queue_semantics() -> None:
    queue, _ = store()
    run(queue.async_add(PLAYER, ITEM_1))
    run(queue.async_add(PLAYER, ITEM_2))

    repeated = content(
        run(queue.async_settings(PLAYER, repeat_item=True, repeat_queue=False))
    )
    assert repeated["repeat_item"] is True
    assert repeated["repeat_queue"] is False

    same = content(run(queue.async_next(PLAYER)))
    assert same["current"]["id"] == "song-1"
    assert same["completed_count"] == 0
    assert same["last_completed"]["id"] == "song-1"

    run(queue.async_settings(PLAYER, repeat_item=False, repeat_queue=True))
    run(queue.async_next(PLAYER))
    wrapped = content(run(queue.async_next(PLAYER)))
    assert wrapped["current"]["id"] == "song-1"
    assert wrapped["current_index"] == 0
    assert wrapped["history"] == []
    assert wrapped["last_completed"]["id"] == "song-2"
    assert wrapped["repeat_item"] is False
    assert wrapped["repeat_queue"] is True


def test_shuffle_never_moves_current_item_and_changes_upcoming_order() -> None:
    queue, _ = store()
    for item in (ITEM_1, ITEM_2, ITEM_3):
        run(queue.async_add(PLAYER, item))

    shuffled = content(run(queue.async_shuffle(PLAYER)))

    assert shuffled["status"] == "shuffled"
    assert shuffled["current"]["id"] == "song-1"
    assert shuffled["queue"][0]["id"] == "song-1"
    assert shuffled["order_changed"] is True
    assert shuffled["shuffled_count"] == 2
    assert {item["id"] for item in shuffled["upcoming"]} == {"song-2", "song-3"}


def test_clear_resets_session_but_settings_remain_compatible() -> None:
    queue, _ = store()
    run(queue.async_add(PLAYER, ITEM_1))
    run(queue.async_settings(PLAYER, repeat_item=True, repeat_queue=False))

    cleared = content(run(queue.async_clear(PLAYER)))

    assert cleared["status"] == "cleared"
    assert cleared["items"] == []
    assert cleared["current"] is None
    # The legacy /queue/clear endpoint intentionally did not reset repeat modes.
    assert cleared["repeat_item"] is True
    assert cleared["repeat_queue"] is False


def test_remove_exists_only_as_internal_store_capability_for_future_feature() -> None:
    queue, _ = store()
    run(queue.async_add(PLAYER, ITEM_1))
    run(queue.async_add(PLAYER, ITEM_2))

    removed = content(run(queue.async_remove(PLAYER, 2)))

    assert removed["status"] == "removed"
    assert removed["removed"]["id"] == "song-2"
    assert [item["id"] for item in removed["items"]] == ["song-1"]


def test_invalid_item_and_position_are_rejected_without_corrupting_state() -> None:
    queue, _ = store()

    with pytest.raises(ValueError, match="requires an id"):
        run(queue.async_add(PLAYER, {"name": "Missing ID"}))
    with pytest.raises(ValueError, match="Unsupported media type"):
        run(queue.async_add(PLAYER, {"id": "x", "name": "X", "type": "Unknown"}))

    run(queue.async_add(PLAYER, ITEM_1))
    response = run(queue.async_remove(PLAYER, 7))
    assert response["status"] == 400
    assert response["content"]["status"] == "invalid_position"
    assert content(run(queue.async_get(PLAYER)))["current"]["id"] == "song-1"


def test_persisted_state_survives_native_store_recreation() -> None:
    queue, backend = store()
    run(queue.async_add(PLAYER, ITEM_1))
    run(queue.async_add(PLAYER, ITEM_2))
    run(queue.async_next(PLAYER))
    run(queue.async_settings(PLAYER, repeat_item=False, repeat_queue=True))

    restored = NativeQueueStore(backend, storage_key="jellyfin_assist.queue.entry")
    run(restored.async_load())
    body = content(run(restored.async_get(PLAYER)))

    assert body["current"]["id"] == "song-2"
    assert body["completed_count"] == 1
    assert body["last_completed"]["id"] == "song-1"
    assert body["repeat_queue"] is True


def test_legacy_queue_current_shape_is_normalized_on_load() -> None:
    backend = MemoryBackend(
        {
            PLAYER: {
                "queue": [ITEM_1, ITEM_2],
                "current": ITEM_2,
                "history": [],
                "repeat_item": False,
                "repeat_queue": False,
            }
        }
    )
    queue, _ = store(backend)

    body = content(run(queue.async_get(PLAYER)))

    assert body["current_index"] == 1
    assert body["current"]["id"] == "song-2"


def test_storage_load_failure_uses_native_queue_error_boundary() -> None:
    queue = NativeQueueStore(BrokenBackend(), storage_key="jellyfin_assist.queue.entry")

    with pytest.raises(QueueStoreError, match="Could not load native queue storage"):
        run(queue.async_load())
