"""High-level media actions formerly implemented as Home Assistant scripts."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from .item_lookup import async_get_native_item
from .playback import async_play_on_chromecast
from .queue_store import QueueStoreError
from .runtime import JellyfinAssistRuntime


def _text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _player_name(hass: Any, media_player: str) -> str:
    state = hass.states.get(media_player) if getattr(hass, "states", None) else None
    attrs = getattr(state, "attributes", {}) or {}
    return _text(attrs.get("friendly_name")) or media_player


def _body(response: Mapping[str, Any]) -> dict[str, Any]:
    content = response.get("content")
    return dict(content) if isinstance(content, Mapping) else {}


async def _queue_call(runtime: JellyfinAssistRuntime, operation: str, **kwargs: Any) -> dict[str, Any]:
    client = runtime.queue_client
    if client is None:
        return {
            "status": 503,
            "content": {
                "success": False,
                "status": "unavailable",
                "message": "Queue service is not configured.",
            },
            "headers": {},
        }
    try:
        return await getattr(client, f"async_{operation}")(**kwargs)
    except (QueueStoreError, ValueError) as err:
        return {
            "status": 503,
            "content": {
                "success": False,
                "status": "unavailable",
                "message": str(err),
            },
            "headers": {},
        }


async def async_play_item(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    item: Mapping[str, Any],
    media_player: str,
) -> dict[str, Any]:
    """Turn on a target and play one resolved Jellyfin item."""

    item_id = _text(item.get("id"))
    title = _text(item.get("name"))
    media_type = _text(item.get("type"))
    year = item.get("year")
    if not item_id:
        return {
            "success": False,
            "status": "invalid_item",
            "message": "The media item does not contain a Jellyfin ID.",
            "item": dict(item),
            "media_player": media_player,
        }
    if not title:
        return {
            "success": False,
            "status": "invalid_item",
            "message": "The media item does not contain a name.",
            "item": dict(item),
            "media_player": media_player,
        }

    try:
        await hass.services.async_call(
            "media_player",
            "turn_on",
            {"entity_id": media_player},
            blocking=True,
        )
    except Exception:
        # Preserve the historical script's focus on the playback result. Some
        # integrations do not implement turn_on but are still playable.
        pass

    for _ in range(120):
        state = hass.states.get(media_player) if getattr(hass, "states", None) else None
        if state is None or getattr(state, "state", None) != "unavailable":
            break
        await asyncio.sleep(0.25)
    else:
        return {
            "success": False,
            "status": "player_unavailable",
            "message": f"{_player_name(hass, media_player)} did not become available.",
            "item": dict(item),
            "media_player": media_player,
        }

    try:
        playback = await async_play_on_chromecast(
            hass,
            runtime,
            target_entity_id=media_player,
            item_id=item_id,
        )
    except Exception as err:
        return {
            "success": False,
            "status": "playback_failed",
            "message": f"I found {title}, but playback failed.",
            "item": dict(item),
            "media_player": media_player,
            "error": str(err),
        }

    player_name = _player_name(hass, media_player)
    year_text = f" ({year})" if year not in (None, "") else ""
    message = f"Playing {title}{year_text} on {player_name}."
    return {
        "success": True,
        "status": "playing",
        "message": message,
        "speak": message,
        "display": message,
        "item_id": item_id,
        "item_name": title,
        "item_type": media_type,
        "item_year": year,
        "media_player": media_player,
        "playback_response": playback,
    }


async def async_prepare_play_session(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    media_player: str,
) -> dict[str, Any]:
    """Reset repeat state before a new play request replaces a queue."""

    player_name = _player_name(hass, media_player)
    response = await _queue_call(
        runtime,
        "settings",
        player=media_player,
        repeat_item=False,
        repeat_queue=False,
    )
    body = _body(response)
    success = (
        int(response.get("status", 0) or 0) == 200
        and bool(body.get("success", False))
        and not bool(body.get("repeat_item", False))
        and not bool(body.get("repeat_queue", False))
    )
    if not success:
        message = f"I could not reset the repeat settings for {player_name}."
        return {
            "success": False,
            "status": "repeat_reset_failed",
            "operation": "play",
            "intent": None,
            "query": None,
            "message": message,
            "speak": message,
            "display": message,
            "media_player": media_player,
            "repeat_item": bool(body.get("repeat_item", False)),
            "repeat_queue": bool(body.get("repeat_queue", False)),
            "queue_response": response,
        }
    message = f"Repeat settings reset for {player_name}."
    return {
        "success": True,
        "status": "ready",
        "operation": "play",
        "intent": None,
        "query": None,
        "message": message,
        "speak": message,
        "display": message,
        "media_player": media_player,
        "repeat_item": False,
        "repeat_queue": False,
        "queue_response": response,
    }


def _episode_number(item: Mapping[str, Any], raw: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    for key in keys:
        # Raw Jellyfin keys differ from normalized script keys.
        raw_key = {"season_number": "ParentIndexNumber", "parent_index_number": "ParentIndexNumber", "season": "ParentIndexNumber", "episode_number": "IndexNumber", "index_number": "IndexNumber", "episode": "IndexNumber"}.get(key)
        if raw_key and raw.get(raw_key) not in (None, ""):
            return raw.get(raw_key)
    return ""


async def async_queue_add_item(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    item: Mapping[str, Any],
    media_player: str,
) -> dict[str, Any]:
    """Add one resolved item while preserving the historical script contract."""

    normalized = dict(item)
    item_id = _text(normalized.get("id"))
    title = _text(normalized.get("name"))
    media_type = _text(normalized.get("type"))
    year = normalized.get("year", "")
    player_name = _player_name(hass, media_player)
    if not item_id:
        return {
            "success": False,
            "status": "invalid_item",
            "message": "The media item does not contain a Jellyfin ID.",
            "speak": "I couldn't add that media because it does not have a valid Jellyfin ID.",
            "display": "I couldn't add that media because it does not have a valid Jellyfin ID.",
            "item": normalized,
            "media_player": media_player,
        }
    if not title:
        return {
            "success": False,
            "status": "invalid_item",
            "message": "The media item does not contain a name.",
            "speak": "I couldn't add that media because its name is missing.",
            "display": "I couldn't add that media because its name is missing.",
            "item": normalized,
            "media_player": media_player,
        }

    raw: dict[str, Any] = {}
    if media_type == "Episode":
        try:
            raw = await async_get_native_item(runtime, item_id)
        except Exception:
            raw = {}

    artist = (
        _text(normalized.get("artist_name"))
        or _text(normalized.get("album_artist"))
        or _text(normalized.get("artist"))
    )
    album = _text(normalized.get("album"))
    series = (
        _text(normalized.get("series_name"))
        or _text(normalized.get("series"))
        or _text(raw.get("SeriesName"))
    )
    if media_type == "Episode":
        season = _episode_number(normalized, raw, "season_number", "parent_index_number", "season")
        episode = _episode_number(normalized, raw, "episode_number", "index_number", "episode")
    elif media_type == "Audio":
        season = episode = ""
    else:
        season = normalized.get("season", "")
        episode = normalized.get("episode", "")

    before = await _queue_call(runtime, "get", player=media_player)
    before_body = _body(before)
    add = await _queue_call(
        runtime,
        "add",
        player=media_player,
        item={
            "id": item_id,
            "name": title,
            "type": media_type,
            "artist": artist,
            "album": album,
            "series": series,
            "season": season,
            "episode": episode,
        },
    )
    add_body = _body(add)
    add_status = int(add.get("status", 0) or 0)
    if add_status != 200 or not bool(add_body.get("success", False)):
        message = f"I found {title}, but I couldn't add it to the Jellyfin Assist queue for {player_name}."
        spoken = f"I found {title}, but I couldn't add it to the queue for {player_name}."
        return {
            "success": False,
            "status": "add_failed",
            "message": message,
            "speak": spoken,
            "display": spoken,
            "item": normalized,
            "media_player": media_player,
            "queue_http_status": add_status,
            "queue_response": add_body,
        }

    display_title = f"{title} ({year})" if year not in (None, "") else title
    spoken_title = f"{title} from {year}" if year not in (None, "") else title
    message = f"Added {display_title} to the Jellyfin Assist queue for {player_name}."
    return {
        "success": True,
        "status": "added",
        "message": message,
        "speak": f"Added {spoken_title} to the queue for {player_name}.",
        "display": f"Added {display_title} to the queue for {player_name}.",
        "item": normalized,
        "item_id": item_id,
        "item_name": title,
        "item_type": media_type,
        "item_year": year,
        "media_player": media_player,
        "queue_before_count": int(before_body.get("count", 0) or 0),
        "queue_before_current": (before_body.get("current") or {}).get("name", "") if isinstance(before_body.get("current"), Mapping) else "",
        "queue_add_http_status": add_status,
        "queue_add_status": _text(add_body.get("status")),
        "queue_after_count": int(add_body.get("count", 0) or 0),
        "queue_after_current": (add_body.get("current") or {}).get("name", "") if isinstance(add_body.get("current"), Mapping) else "",
    }


__all__ = [
    "async_play_item",
    "async_prepare_play_session",
    "async_queue_add_item",
]
