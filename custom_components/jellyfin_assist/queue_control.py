"""High-level queue control formerly implemented as Home Assistant scripts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import DOMAIN, SERVICE_RESOLVE_MEDIA_PLAYER
from .media_actions import async_play_item
from .queue_store import QueueStoreError
from .runtime import JellyfinAssistRuntime


def _text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _player_name(hass: Any, media_player: str) -> str:
    state = hass.states.get(media_player) if getattr(hass, "states", None) else None
    attrs = getattr(state, "attributes", {}) or {}
    return _text(attrs.get("friendly_name")) or media_player


def _player_state(hass: Any, media_player: str) -> str:
    state = hass.states.get(media_player) if getattr(hass, "states", None) else None
    return _text(getattr(state, "state", "unknown")).lower() or "unknown"


def _body(response: Mapping[str, Any]) -> dict[str, Any]:
    content = response.get("content")
    return dict(content) if isinstance(content, Mapping) else {}


async def _queue_call(runtime: JellyfinAssistRuntime, operation: str, **kwargs: Any) -> dict[str, Any]:
    client = runtime.queue_client
    if client is None:
        return {
            "status": 503,
            "content": {"success": False, "status": "unavailable", "message": "Queue service is not configured."},
            "headers": {},
        }
    try:
        return await getattr(client, f"async_{operation}")(**kwargs)
    except (QueueStoreError, ValueError) as err:
        return {
            "status": 503,
            "content": {"success": False, "status": "unavailable", "message": str(err)},
            "headers": {},
        }


def _description(item: Any, *, include_album: bool = True) -> str:
    if not isinstance(item, Mapping) or not item.get("id"):
        return ""
    text = _text(item.get("name")) or "Unknown media"
    media_type = _text(item.get("type"))
    if media_type == "Episode":
        series = _text(item.get("series"))
        season = item.get("season")
        episode = item.get("episode")
        if series:
            text += f" from {series}"
        if season not in (None, ""):
            text += f", Season {season}"
        if episode not in (None, ""):
            text += f", Episode {episode}"
    elif media_type == "Audio":
        artist = _text(item.get("artist"))
        album = _text(item.get("album"))
        if artist:
            text += f" by {artist}"
        if include_album and album:
            text += f" from {album}"
    return text


def _snapshot(body: Mapping[str, Any]) -> dict[str, Any]:
    items = body.get("items", body.get("queue", [])) or []
    if not isinstance(items, list):
        items = []
    history = body.get("history", []) or []
    if not isinstance(history, list):
        history = []
    current = body.get("current") if isinstance(body.get("current"), Mapping) else None
    previous = body.get("previous") if isinstance(body.get("previous"), Mapping) else None
    completed = body.get("last_completed") if isinstance(body.get("last_completed"), Mapping) else None
    next_item = body.get("next") if isinstance(body.get("next"), Mapping) else None
    index = body.get("current_index")
    try:
        total = int(body.get("count", len(items)) or 0)
    except (TypeError, ValueError):
        total = len(items)
    try:
        completed_count = int(body.get("completed_count", len(history)) or 0)
    except (TypeError, ValueError):
        completed_count = len(history)
    upcoming = body.get("upcoming", []) or []
    try:
        upcoming_count = int(body.get("upcoming_count", len(upcoming) if isinstance(upcoming, list) else 0) or 0)
    except (TypeError, ValueError):
        upcoming_count = 0
    try:
        current_position = int(index) + 1 if index not in (None, "") else None
    except (TypeError, ValueError):
        current_position = None
    return {
        "items": items,
        "history": history,
        "current_item": current,
        "previous_item": previous,
        "completed_item": completed,
        "next_item": next_item,
        "current_index": index,
        "current_position": current_position,
        "total_count": total,
        "completed_count": completed_count,
        "upcoming_count": upcoming_count,
        "repeat_item": bool(body.get("repeat_item", False)),
        "repeat_queue": bool(body.get("repeat_queue", False)),
    }


def _common_result(
    *,
    success: bool,
    status: str,
    operation: str,
    intent: str,
    message: str,
    media_player: str,
    response: Mapping[str, Any],
    snapshot: Mapping[str, Any] | None = None,
    item: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    snap = dict(snapshot or {})
    current = item if item is not None else snap.get("current_item")
    current_id = current.get("id") if isinstance(current, Mapping) else None
    return {
        "success": success,
        "status": status,
        "operation": operation,
        "intent": intent,
        "query": None,
        "message": message,
        "speak": message,
        "display": message,
        "jellyfin_id": current_id,
        "item": current,
        "items": snap.get("items", []),
        "playback_plan": [current] if current is not None and operation in {"whats_playing", "next"} else [],
        "media_player": media_player,
        **{k: v for k, v in snap.items() if k != "items"},
        "queue_response": dict(response),
        **extra,
    }


def _queue_unavailable(
    hass: Any,
    *,
    media_player: str,
    operation: str,
    intent: str,
    response: Mapping[str, Any],
    wording: str = "retrieve the Jellyfin Assist queue",
    spoken_wording: str = "retrieve the media queue",
) -> dict[str, Any]:
    name = _player_name(hass, media_player)
    message = f"I couldn't {wording} for {name}."
    result = _common_result(
        success=False,
        status="queue_unavailable",
        operation=operation,
        intent=intent,
        message=message,
        media_player=media_player,
        response=response,
        snapshot={},
        item=None,
    )
    result["speak"] = f"I couldn't {spoken_wording} for {name}."
    return result


async def async_whats_playing(hass: Any, runtime: JellyfinAssistRuntime, *, media_player: str) -> dict[str, Any]:
    name = _player_name(hass, media_player)
    state = _player_state(hass, media_player)
    response = await _queue_call(runtime, "get", player=media_player)
    body = _body(response)
    if int(response.get("status", 0) or 0) != 200:
        result = _queue_unavailable(hass, media_player=media_player, operation="whats_playing", intent="QueueWhatsPlaying", response=response)
        result["player_state"] = state
        return result
    snap = _snapshot(body)
    current = snap["current_item"]
    if current is None:
        complete = _text(body.get("status")) == "complete" or (
            snap["total_count"] > 0 and snap["completed_count"] >= snap["total_count"]
        )
        message = (
            f"The queue for {name} has finished. Nothing is currently playing."
            if complete
            else f"Nothing is currently playing on {name}."
        )
        result = _common_result(
            success=False,
            status="complete" if complete else "empty",
            operation="whats_playing",
            intent="QueueWhatsPlaying",
            message=message,
            media_player=media_player,
            response=response,
            snapshot=snap,
            item=None,
        )
        result["player_state"] = state
        return result
    desc = _description(current)
    if state == "playing":
        success, status, message = True, "playing", f"{desc} is playing on {name}."
    elif state == "paused":
        success, status, message = True, "paused", f"{desc} is paused on {name}."
    elif state == "buffering":
        success, status, message = True, "buffering", f"{desc} is loading on {name}."
    elif state in {"unavailable", "unknown"}:
        success, status, message = False, "player_unavailable", f"I can't confirm what is playing on {name}. The queue is positioned at {desc}."
    else:
        success, status, message = False, "not_playing", f"Nothing is currently playing on {name}. The queue is positioned at {desc}."
    result = _common_result(
        success=success,
        status=status,
        operation="whats_playing",
        intent="QueueWhatsPlaying",
        message=message,
        media_player=media_player,
        response=response,
        snapshot=snap,
        item=current,
    )
    result["player_state"] = state
    return result


async def async_what_just_played(hass: Any, runtime: JellyfinAssistRuntime, *, media_player: str) -> dict[str, Any]:
    name = _player_name(hass, media_player)
    response = await _queue_call(runtime, "get", player=media_player)
    body = _body(response)
    if int(response.get("status", 0) or 0) != 200:
        return _queue_unavailable(hass, media_player=media_player, operation="what_just_played", intent="QueueWhatJustPlayed", response=response)
    snap = _snapshot(body)
    completed = snap["completed_item"]
    if completed is None and snap["history"]:
        candidate = snap["history"][-1]
        completed = candidate if isinstance(candidate, Mapping) else None
    if completed is None:
        message = f"Nothing has completed in the Jellyfin Assist queue for {name} yet."
        return _common_result(
            success=False,
            status="no_history",
            operation="what_just_played",
            intent="QueueWhatJustPlayed",
            message=message,
            media_player=media_player,
            response=response,
            snapshot=snap,
            item=None,
        )
    message = f"{_description(completed)} was the last thing played on {name}."
    result = _common_result(
        success=True,
        status="played",
        operation="what_just_played",
        intent="QueueWhatJustPlayed",
        message=message,
        media_player=media_player,
        response=response,
        snapshot=snap,
        item=completed,
        completed_item=completed,
    )
    result["playback_plan"] = []
    return result


async def async_queue_status(hass: Any, runtime: JellyfinAssistRuntime, *, media_player: str) -> dict[str, Any]:
    name = _player_name(hass, media_player)
    response = await _queue_call(runtime, "get", player=media_player)
    body = _body(response)
    if int(response.get("status", 0) or 0) != 200:
        return _queue_unavailable(hass, media_player=media_player, operation="queue_status", intent="QueueStatus", response=response)
    snap = _snapshot(body)
    total = snap["total_count"]
    completed_count = snap["completed_count"]
    current = snap["current_item"]
    completed = snap["completed_item"]
    if completed is None and snap["history"]:
        candidate = snap["history"][-1]
        completed = candidate if isinstance(candidate, Mapping) else None
    if total == 0:
        state = "empty"
    elif current is not None:
        state = "active"
    elif completed_count >= total:
        state = "complete"
    else:
        state = "inactive"
    current_text = _description(current)
    completed_text = _description(completed)
    next_text = _description(snap["next_item"])
    if state == "empty":
        message = f"The queue for {name} is empty."
    elif state == "complete":
        item_word = "item is" if total == 1 else "items are"
        message = f"The queue for {name} has finished. {completed_count} of {total} {item_word} complete."
        if completed_text:
            message += f" {completed_text} was last completed."
    elif state == "active":
        message = f"The queue for {name} is positioned at {current_text}, item {snap['current_position']} of {total}."
        if completed_text:
            message += f" {completed_text} was last completed."
        message += f" {next_text} is next." if next_text else " Nothing is next."
        if snap["upcoming_count"] == 1:
            message += " There is 1 item remaining after the current item."
        elif snap["upcoming_count"] > 1:
            message += f" There are {snap['upcoming_count']} items remaining after the current item."
        if snap["repeat_item"]:
            message += " Repeat item is on."
        if snap["repeat_queue"]:
            message += " Repeat queue is on."
    else:
        item_word = "item" if total == 1 else "items"
        message = f"The queue for {name} contains {total} {item_word}, but it does not currently have an active position."
        if completed_text:
            message += f" {completed_text} was last completed."
    return _common_result(
        success=True,
        status=state,
        operation="queue_status",
        intent="QueueStatus",
        message=message,
        media_player=media_player,
        response=response,
        snapshot=snap,
        item=current,
        completed_item=completed,
    )


async def async_clear_queue(hass: Any, runtime: JellyfinAssistRuntime, *, media_player: str) -> dict[str, Any]:
    name = _player_name(hass, media_player)
    before = await _queue_call(runtime, "get", player=media_player)
    before_body = _body(before)
    if int(before.get("status", 0) or 0) != 200:
        return _queue_unavailable(hass, media_player=media_player, operation="clear", intent="QueueClear", response=before)
    before_snap = _snapshot(before_body)
    if before_snap["total_count"] == 0:
        message = f"The queue for {name} is already empty."
        return _common_result(success=True, status="already_empty", operation="clear", intent="QueueClear", message=message, media_player=media_player, response=before, snapshot=before_snap, item=None)
    cleared = await _queue_call(runtime, "clear", player=media_player)
    clear_body = _body(cleared)
    if int(cleared.get("status", 0) or 0) != 200 or not bool(clear_body.get("success", False)):
        message = f"I couldn't clear the queue for {name}."
        result = _common_result(success=False, status="queue_clear_failed", operation="clear", intent="QueueClear", message=message, media_player=media_player, response=cleared, snapshot=before_snap, item=before_snap["current_item"])
        result["speak"] = f"I couldn't clear the media queue for {name}."
        return result
    after = await _queue_call(runtime, "get", player=media_player)
    after_body = _body(after)
    if int(after.get("status", 0) or 0) != 200:
        message = f"The clear request was accepted for {name}, but I couldn't verify the resulting queue."
        result = _common_result(success=False, status="queue_verification_failed", operation="clear", intent="QueueClear", message=message, media_player=media_player, response=after, snapshot=before_snap, item=None, clear_response=cleared)
        result["speak"] = f"I cleared the media queue for {name}, but I couldn't verify it."
        return result
    after_snap = _snapshot(after_body)
    if after_snap["total_count"] != 0:
        message = f"I sent the clear request, but the queue for {name} is not empty."
        result = _common_result(success=False, status="queue_not_empty", operation="clear", intent="QueueClear", message=message, media_player=media_player, response=after, snapshot=after_snap, item=after_snap["current_item"], clear_response=cleared)
        result["speak"] = f"I couldn't completely clear the media queue for {name}."
        return result
    count = before_snap["total_count"]
    message = f"Cleared {count} item{'s' if count != 1 else ''} from the queue for {name}."
    return _common_result(success=True, status="cleared", operation="clear", intent="QueueClear", message=message, media_player=media_player, response=after, snapshot=after_snap, item=None, cleared_count=count, clear_response=cleared)


async def async_shuffle_queue(hass: Any, runtime: JellyfinAssistRuntime, *, media_player: str) -> dict[str, Any]:
    name = _player_name(hass, media_player)
    response = await _queue_call(runtime, "shuffle", player=media_player)
    body = _body(response)
    if int(response.get("status", 0) or 0) != 200:
        message = f"I couldn't shuffle the queue for {name} because the Jellyfin Assist queue service was unavailable."
        result = _common_result(success=False, status="queue_unavailable", operation="shuffle", intent="QueueShuffle", message=message, media_player=media_player, response=response, snapshot={})
        result["speak"] = f"I couldn't shuffle the media queue for {name}."
        return result
    snap = _snapshot(body)
    status = _text(body.get("status"))
    if status == "empty":
        message = f"The queue for {name} is empty, so there is nothing to shuffle."
        return _common_result(success=False, status="empty", operation="shuffle", intent="QueueShuffle", message=message, media_player=media_player, response=response, snapshot=snap, item=None)
    if status == "complete":
        message = f"The queue for {name} has already finished, so there are no upcoming items to shuffle."
        return _common_result(success=False, status="complete", operation="shuffle", intent="QueueShuffle", message=message, media_player=media_player, response=response, snapshot=snap, item=None)
    shuffled_count = int(body.get("shuffled_count", 0) or 0)
    order_changed = bool(body.get("order_changed", False))
    if status == "unchanged":
        if snap["upcoming_count"] == 1:
            message = f"There is only one upcoming item in the queue for {name}, so the order did not change."
        else:
            message = f"There are no upcoming items to shuffle in the queue for {name}."
        return _common_result(success=True, status="unchanged", operation="shuffle", intent="QueueShuffle", message=message, media_player=media_player, response=response, snapshot=snap, item=snap["current_item"], shuffled_count=shuffled_count, order_changed=order_changed)
    if status != "shuffled" or not bool(body.get("success", False)) or not order_changed:
        message = f"I couldn't confirm that the upcoming queue for {name} was shuffled."
        result = _common_result(success=False, status="shuffle_failed", operation="shuffle", intent="QueueShuffle", message=message, media_player=media_player, response=response, snapshot=snap, item=snap["current_item"], shuffled_count=shuffled_count, order_changed=order_changed)
        result["speak"] = f"I couldn't confirm that the media queue for {name} was shuffled."
        return result
    current_text = _description(snap["current_item"])
    next_text = _description(snap["next_item"])
    message = f"Shuffled {shuffled_count} upcoming items in the queue for {name}."
    if current_text:
        message += f" {current_text} remains the current item."
    if next_text:
        message += f" {next_text} is now next."
    return _common_result(success=True, status="shuffled", operation="shuffle", intent="QueueShuffle", message=message, media_player=media_player, response=response, snapshot=snap, item=snap["current_item"], shuffled_count=shuffled_count, original_upcoming=body.get("original_upcoming", []), shuffled_upcoming=body.get("shuffled_upcoming", []), order_changed=order_changed)


async def async_queue_next_command(hass: Any, runtime: JellyfinAssistRuntime, *, media_player: str) -> dict[str, Any]:
    name = _player_name(hass, media_player)
    response = await _queue_call(runtime, "next", player=media_player)
    body = _body(response)
    http_status = int(response.get("status", 0) or 0)
    status = _text(body.get("status")) or "unknown"
    if http_status != 200:
        message = f"I could not advance the queue for {name}."
        return _common_result(success=False, status="queue_advance_failed", operation="next", intent="QueueNext", message=message, media_player=media_player, response=response, snapshot=_snapshot(body), item=None)
    snap = _snapshot(body)
    if status == "empty":
        message = f"The queue for {name} is empty."
        return _common_result(success=False, status="empty", operation="next", intent="QueueNext", message=message, media_player=media_player, response=response, snapshot=snap, item=None)
    if status == "complete":
        message = f"The queue for {name} has already finished."
        return _common_result(success=False, status="complete", operation="next", intent="QueueNext", message=message, media_player=media_player, response=response, snapshot=snap, item=None)
    if not bool(body.get("success", False)):
        message = _text(body.get("message")) or "I could not advance the media queue."
        return _common_result(success=False, status="queue_advance_failed", operation="next", intent="QueueNext", message=message, media_player=media_player, response=response, snapshot=snap, item=None)
    completed = body.get("completed") if isinstance(body.get("completed"), Mapping) else body.get("finished") if isinstance(body.get("finished"), Mapping) else None
    next_item = snap["current_item"]
    if next_item is None:
        try:
            await hass.services.async_call("media_player", "media_stop", {"entity_id": media_player}, blocking=False)
        except Exception:
            pass
        completed_name = _text(completed.get("name")) if isinstance(completed, Mapping) else ""
        message = (
            f"Finished {completed_name}. There is nothing else in the queue for {name}."
            if completed_name
            else f"There is nothing else in the queue for {name}."
        )
        return _common_result(success=True, status="queue_complete", operation="next", intent="QueueNext", message=message, media_player=media_player, response=response, snapshot=snap, item=None, completed_item=completed)
    playback = await async_play_item(hass, runtime, item=next_item, media_player=media_player)
    success = bool(playback.get("success", False))
    desc = _description(next_item, include_album=False)
    message = (
        f"Playing {desc} on {name}."
        if success
        else f"The queue advanced to {_text(next_item.get('name'))}, but playback could not be started on {name}."
    )
    return _common_result(success=success, status="playing" if success else "playback_failed", operation="next", intent="QueueNext", message=message, media_player=media_player, response=response, snapshot=snap, item=next_item, completed_item=completed, playback_response=playback)


async def _toggle_repeat(hass: Any, runtime: JellyfinAssistRuntime, *, media_player: str, mode: str) -> dict[str, Any]:
    name = _player_name(hass, media_player)
    before = await _queue_call(runtime, "get", player=media_player)
    body = _body(before)
    if int(before.get("status", 0) or 0) != 200 or not bool(body.get("success", False)):
        wording = "queue settings"
        return _queue_unavailable(hass, media_player=media_player, operation=f"repeat_{mode}", intent="QueueRepeatItem" if mode == "item" else "QueueRepeatQueue", response=before, wording=f"retrieve the {wording}", spoken_wording=f"retrieve the media {wording}")
    snap = _snapshot(body)
    prev_item = snap["repeat_item"]
    prev_queue = snap["repeat_queue"]
    if mode == "item":
        requested_item = not prev_item
        requested_queue = False if requested_item else prev_queue
    else:
        requested_queue = not prev_queue
        requested_item = False if requested_queue else prev_item
    updated = await _queue_call(runtime, "settings", player=media_player, repeat_item=requested_item, repeat_queue=requested_queue)
    updated_body = _body(updated)
    updated_success = int(updated.get("status", 0) or 0) == 200 and bool(updated_body.get("success", False))
    if not updated_success:
        label = "Repeat Item" if mode == "item" else "Repeat Queue"
        message = f"I couldn't update {label} for {name}."
        result = _common_result(success=False, status="settings_update_failed", operation=f"repeat_{mode}", intent="QueueRepeatItem" if mode == "item" else "QueueRepeatQueue", message=message, media_player=media_player, response=updated, snapshot=snap, item=snap["current_item"], enabled=prev_item if mode == "item" else prev_queue, previous_enabled=prev_item if mode == "item" else prev_queue, queue_before_response=before)
        return result
    new_snap = _snapshot(updated_body)
    current_text = _description(new_snap["current_item"])
    if mode == "item":
        enabled = new_snap["repeat_item"]
        if enabled:
            message = f"Repeat Item enabled for {current_text} on {name}." if current_text else f"Repeat Item enabled for {name}. It will apply when an item is current."
        else:
            message = f"Repeat Item disabled for {current_text} on {name}." if current_text else f"Repeat Item disabled for {name}."
        status = "repeat_item_on" if enabled else "repeat_item_off"
        intent = "QueueRepeatItem"
    else:
        enabled = new_snap["repeat_queue"]
        if enabled:
            if new_snap["total_count"] == 0:
                message = f"Repeat Queue enabled for {name}. It will apply when the queue contains media."
            elif current_text:
                message = f"Repeat Queue enabled for {name}. The queue will restart after its final item. {current_text} remains the current item."
            else:
                message = f"Repeat Queue enabled for {name}. The queue will restart after its final item."
        else:
            message = f"Repeat Queue disabled for {name}. {current_text} remains the current item." if current_text else f"Repeat Queue disabled for {name}."
        status = "repeat_queue_on" if enabled else "repeat_queue_off"
        intent = "QueueRepeatQueue"
    return _common_result(success=True, status=status, operation=f"repeat_{mode}", intent=intent, message=message, media_player=media_player, response=updated, snapshot=new_snap, item=new_snap["current_item"], enabled=enabled, previous_enabled=prev_item if mode == "item" else prev_queue, queue_before_response=before)


async def async_repeat_set(hass: Any, runtime: JellyfinAssistRuntime, *, media_player: str, repeat_mode: str) -> dict[str, Any]:
    requested = _text(repeat_mode).lower() or "off"
    name = _player_name(hass, media_player)
    response = await _queue_call(runtime, "get", player=media_player)
    body = _body(response)
    if int(response.get("status", 0) or 0) != 200 or not bool(body.get("success", False)):
        return _queue_unavailable(hass, media_player=media_player, operation="repeat", intent="QueueRepeat", response=response, wording="retrieve the repeat settings", spoken_wording="retrieve the repeat settings")
    snap = _snapshot(body)
    if requested == "item":
        if snap["repeat_item"]:
            message = f"Repeat Item is already enabled for {name}."
            return _common_result(success=True, status="repeat_item_on", operation="repeat_item", intent="QueueRepeatItem", message=message, media_player=media_player, response=response, snapshot=snap, item=snap["current_item"], enabled=True, previous_enabled=True)
        return await _toggle_repeat(hass, runtime, media_player=media_player, mode="item")
    if requested == "queue":
        if snap["repeat_queue"]:
            message = f"Repeat Queue is already enabled for {name}."
            return _common_result(success=True, status="repeat_queue_on", operation="repeat_queue", intent="QueueRepeatQueue", message=message, media_player=media_player, response=response, snapshot=snap, item=snap["current_item"], enabled=True, previous_enabled=True)
        return await _toggle_repeat(hass, runtime, media_player=media_player, mode="queue")
    if requested == "off":
        if not snap["repeat_item"] and not snap["repeat_queue"]:
            message = f"Repeat is already off for {name}."
            return _common_result(success=True, status="repeat_off", operation="repeat_off", intent="QueueRepeatOff", message=message, media_player=media_player, response=response, snapshot=snap, item=snap["current_item"], enabled=False, previous_enabled=False)
        if snap["repeat_item"]:
            return await _toggle_repeat(hass, runtime, media_player=media_player, mode="item")
        return await _toggle_repeat(hass, runtime, media_player=media_player, mode="queue")
    message = "I couldn't understand the requested repeat mode."
    return _common_result(success=False, status="invalid_repeat_mode", operation="repeat", intent="QueueRepeat", message=message, media_player=media_player, response=response, snapshot=snap, item=snap["current_item"], enabled=False, previous_enabled=False)


async def async_execute_queue_operation(hass: Any, runtime: JellyfinAssistRuntime, *, operation: str, media_player: str) -> dict[str, Any]:
    dispatch = {
        "queue_next": async_queue_next_command,
        "whats_playing": async_whats_playing,
        "what_just_played": async_what_just_played,
        "queue_status": async_queue_status,
        "queue_clear": async_clear_queue,
        "queue_shuffle": async_shuffle_queue,
    }
    if operation in dispatch:
        return await dispatch[operation](hass, runtime, media_player=media_player)
    if operation == "repeat_item_enable":
        return await async_repeat_set(hass, runtime, media_player=media_player, repeat_mode="item")
    if operation == "repeat_queue_enable":
        return await async_repeat_set(hass, runtime, media_player=media_player, repeat_mode="queue")
    if operation == "repeat_off":
        return await async_repeat_set(hass, runtime, media_player=media_player, repeat_mode="off")
    if operation == "repeat_item_toggle":
        return await _toggle_repeat(hass, runtime, media_player=media_player, mode="item")
    if operation == "repeat_queue_toggle":
        return await _toggle_repeat(hass, runtime, media_player=media_player, mode="queue")
    return {
        "success": False,
        "status": "invalid_queue_operation",
        "operation": operation,
        "message": "That queue command is not supported.",
        "speak": "That queue command is not supported.",
        "display": "That queue command is not supported.",
        "media_player": media_player,
    }


async def async_queue_command(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    operation: str,
    media_player: str = "",
    media_player_display_name: str = "",
    context: Any = None,
) -> dict[str, Any]:
    """Resolve a spoken/default player and execute one high-level queue command."""

    requested = _text(media_player)
    requested_display = _text(media_player_display_name)
    requested_entity_name = ""
    if requested.startswith("media_player."):
        requested_entity_name = requested.split(".", 1)[1].replace("_", " ").title().replace(" Tv", " TV")

    resolution_data = {"media_player": requested, "operation": operation}
    if runtime.entry_id:
        resolution_data["config_entry_id"] = runtime.entry_id
    resolution = await hass.services.async_call(
        DOMAIN,
        SERVICE_RESOLVE_MEDIA_PLAYER,
        resolution_data,
        blocking=True,
        return_response=True,
        context=context,
    )
    if not isinstance(resolution, Mapping) or not resolution.get("success", False):
        reason = _text(resolution.get("reason")) if isinstance(resolution, Mapping) else ""
        message = (
            "I found more than one matching media player. Which one would you like me to use?"
            if reason == "explicit_player_ambiguous"
            else "I could not use that media player. Which media player would you like me to use?"
            if reason == "explicit_player_not_found"
            else "Which media player would you like me to use?"
        )
        return {
            "success": False,
            "status": "media_player_required",
            "operation": operation,
            "intent": "QueueCommand",
            "query": None,
            "message": message,
            "speak": message,
            "display": message,
            "jellyfin_id": None,
            "item": None,
            "items": [],
            "playback_plan": [],
            "media_player": None,
            "player_resolution": dict(resolution) if isinstance(resolution, Mapping) else {},
        }
    resolved = _text(resolution.get("media_player"))
    display_name = requested_display or requested_entity_name or _text(resolution.get("media_player_name")) or _player_name(hass, resolved)
    result = await async_execute_queue_operation(hass, runtime, operation=operation, media_player=resolved)
    canonical_name = _player_name(hass, resolved)
    for key in ("message", "speak", "display"):
        value = _text(result.get(key))
        if value and canonical_name and display_name:
            result[key] = value.replace(canonical_name, display_name)
    result["media_player"] = resolved
    result["media_player_name"] = display_name
    result["player_resolution"] = resolution.get("player_resolution", {})
    return result


__all__ = [
    "async_clear_queue",
    "async_execute_queue_operation",
    "async_queue_command",
    "async_queue_next_command",
    "async_queue_status",
    "async_repeat_set",
    "async_shuffle_queue",
    "async_what_just_played",
    "async_whats_playing",
]
