"""Native automatic queue advancement for configured media players."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import math
import re
from typing import Any, Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .api import JellyfinApiError
from .const import DOMAIN
from .media_actions import async_play_item
from .queue_store import QueueStoreError
from .runtime import JellyfinAssistRuntime

_LOGGER = logging.getLogger(__name__)

COMPLETION_THRESHOLD_PERCENT: Final = 95.0
PLAYBACK_WRITESYNC_INTERVAL_SECONDS: Final = 60.0
_SESSION_UNSET: Final = object()
_CONTENT_ID_PATTERN: Final = re.compile(r"/(?:Videos|Audio)/([A-Za-z0-9]+)(?:/|$)")


def _timestamp(value: Any) -> float:
    """Return a timestamp for Home Assistant datetime-like values."""

    if value is None or value == "":
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return 0.0
        try:
            return float(normalized)
        except ValueError:
            try:
                return datetime.fromisoformat(
                    normalized.replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                return 0.0
    return 0.0


def _estimate_playback_percent(old_state: Any, new_state: Any) -> float:
    """Mirror the proven automation's completion estimate."""

    attrs = getattr(old_state, "attributes", {}) or {}
    duration = float(attrs.get("media_duration") or 0)
    if duration <= 0:
        return 0.0

    reported_position = float(attrs.get("media_position") or 0)
    updated_at = _timestamp(attrs.get("media_position_updated_at"))
    playing_started_at = _timestamp(getattr(old_state, "last_changed", None))
    idle_started_at = _timestamp(getattr(new_state, "last_changed", None))

    position_sample_is_current = (
        updated_at > 0
        and playing_started_at > 0
        and updated_at >= (playing_started_at - 5)
    )
    position_reference_timestamp = (
        updated_at if position_sample_is_current else playing_started_at
    )
    position_reference_value = (
        reported_position if position_sample_is_current else 0.0
    )
    elapsed_since_reference = (
        max(idle_started_at - position_reference_timestamp, 0.0)
        if idle_started_at > 0 and position_reference_timestamp > 0
        else 0.0
    )
    continuous_playing_seconds = (
        max(idle_started_at - playing_started_at, 0.0)
        if idle_started_at > 0 and playing_started_at > 0
        else 0.0
    )
    extrapolated_position = position_reference_value + elapsed_since_reference
    estimated_position = min(
        max(
            reported_position,
            extrapolated_position,
            continuous_playing_seconds,
        ),
        duration,
    )
    return round(estimated_position / duration * 100, 2)


def _extract_jellyfin_id(content_id: Any) -> str:
    """Extract the Jellyfin item id from the media player's content URL."""

    if not content_id:
        return ""
    match = _CONTENT_ID_PATTERN.search(str(content_id))
    return match.group(1) if match else ""


def _update_playback_session(
    runtime: JellyfinAssistRuntime,
    *,
    player: str,
    old_state: Any,
    new_state: Any,
) -> None:
    """Accumulate actual playing time for one Jellyfin-started playback session."""

    session = runtime.playback_sessions.get(player)
    if session is None:
        return

    old_player_state = getattr(old_state, "state", None)
    new_player_state = getattr(new_state, "state", None)
    if old_player_state == new_player_state:
        return
    transition_at = _timestamp(getattr(new_state, "last_changed", None))

    if old_player_state == "playing":
        started_at = _timestamp(session.get("playing_started_at"))
        if started_at <= 0:
            started_at = _timestamp(
                getattr(old_state, "last_changed", None)
            )

        accumulated = float(
            session.get("accumulated_playing_seconds") or 0.0
        )
        if started_at > 0 and transition_at > 0:
            accumulated += max(transition_at - started_at, 0.0)

        session["accumulated_playing_seconds"] = accumulated
        session["playing_started_at"] = None

    if new_player_state == "playing":
        session["playing_started_at"] = getattr(
            new_state,
            "last_changed",
            None,
        )


def _session_playback_percent(
    session: Mapping[str, Any] | None,
) -> float:
    """Estimate completion from Jellyfin runtime and tracked playing time."""

    if not isinstance(session, Mapping):
        return 0.0

    try:
        duration = float(session.get("duration_seconds") or 0.0)
        accumulated = float(
            session.get("accumulated_playing_seconds") or 0.0
        )
    except (TypeError, ValueError):
        return 0.0

    if duration <= 0:
        return 0.0

    played = min(max(accumulated, 0.0), duration)
    return round(played / duration * 100, 2)


async def _async_notify_failure(
    hass: HomeAssistant,
    *,
    title: str,
    message: str,
) -> None:
    """Create the same failure-only persistent notifications as the old automation."""

    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
            },
            blocking=False,
        )
    except Exception:
        _LOGGER.exception(
            "Could not create Jellyfin Assist failure notification"
        )


async def _async_mark_album_completion(
    runtime: Any,
    completed_item_id: str,
) -> None:
    """Mark a completed song in the album tracking store (if applicable).

    Only marks when the completed item is audio belonging to a tracked
    album. The membership check resolves the item's Jellyfin AlbumId
    (rather than trusting the media type alone), so a confirmed
    completion that is not an album member is silently skipped.
    Failures are best-effort and never raise into the advancement path.
    """

    store = getattr(runtime, "album_tracking_store", None)
    queue_client = runtime.queue_client
    client = runtime.client
    user_id = runtime.user_id

    if store is None or queue_client is None or client is None or not user_id:
        return

    if not completed_item_id:
        return

    try:
        item_response = await client.async_get_item(user_id, completed_item_id)
    except Exception:
        _LOGGER.debug(
            "Album tracking: could not resolve item %s; skipping",
            completed_item_id,
            exc_info=True,
        )
        return

    item_type = item_response.get("Type", "")
    if item_type not in {"Audio", "MusicVideo"}:
        return

    album_id = item_response.get("AlbumId", "")
    if not album_id:
        return

    try:
        await store.mark_complete(user_id, album_id, completed_item_id)
    except Exception:
        _LOGGER.debug(
            "Album tracking: mark_complete failed for %s in album %s; skipping",
            completed_item_id,
            album_id,
            exc_info=True,
        )
        return


async def _async_handle_album_completion(
    hass: HomeAssistant,
    runtime: JellyfinAssistRuntime,
    *,
    player: str,
    completed_item_id: str,
    repeat_queue: bool,
) -> dict[str, Any] | None:
    """Detect album completion and handle announce/stop/repeat.

    Called from the ``queue_complete`` branch after the final track of an
    album has been marked complete.  Returns a result dict when the album
    is fully complete, or ``None`` when the completed item does not belong
    to a tracked album or the album is not yet finished.
    """
    store = getattr(runtime, "album_tracking_store", None)
    client = runtime.client
    user_id = runtime.user_id
    queue_client = runtime.queue_client

    if store is None or client is None or not user_id or not completed_item_id:
        return None

    # Resolve the album_id from the completed item.
    try:
        item_response = await client.async_get_item(user_id, completed_item_id)
    except Exception:
        _LOGGER.debug(
            "Album complete: could not resolve item %s",
            completed_item_id,
            exc_info=True,
        )
        return None

    item_type = item_response.get("Type", "")
    if item_type not in {"Audio", "MusicVideo"}:
        return None

    album_id = item_response.get("AlbumId", "")
    if not album_id:
        return None

    # Get completed ids for this album.
    try:
        completed_ids = store.completed_ids(user_id, album_id)
    except Exception:
        _LOGGER.debug(
            "Album complete: completed_ids failed for %s",
            album_id,
            exc_info=True,
        )
        return None

    # Get total track count from Jellyfin.
    try:
        albums_response = await client.async_get_items(
            user_id, parent_id=album_id, recursive=False
        )
    except Exception:
        _LOGGER.debug(
            "Album complete: album tracks fetch failed for %s",
            album_id,
            exc_info=True,
        )
        return None

    album_items = (
        albums_response.get("Items", [])
        if isinstance(albums_response, dict)
        else []
    )
    total_tracks = len(album_items)

    if total_tracks == 0:
        return None

    # Album is complete only when every track has been marked.
    if len(completed_ids) < total_tracks:
        return None

    # Announce "Album complete".
    try:
        await hass.services.async_call(
            "media_player",
            "announce",
            {"entity_id": player, "message": "Album complete"},
            blocking=False,
        )
    except Exception:
        _LOGGER.debug(
            "Album complete: announce failed for %s", player, exc_info=True
        )

    album_name = item_response.get("Album", "Album")
    result: dict[str, Any] = {
        "album_complete": True,
        "album_id": album_id,
        "album_name": album_name,
        "total_tracks": total_tracks,
        "repeat_queue": repeat_queue,
    }

    if repeat_queue:
        # Repeat is enabled: reset the album tracking so the second pass
        # (the queue store already wrapped the index back to track 1)
        # re-marks completions.  No stop — playback continues through
        # the repeated album via the normal queue-advance path.
        try:
            await store.reset_album(user_id, album_id)
        except Exception:
            _LOGGER.debug(
                "Album complete: reset_album failed for %s",
                album_id,
                exc_info=True,
            )
        result["repeated"] = True
    else:
        # No repeat: stop the player — the album finished.
        try:
            await hass.services.async_call(
                "media_player",
                "stop",
                {"entity_id": player},
                blocking=False,
            )
        except Exception:
            _LOGGER.debug(
                "Album complete: stop failed for %s", player, exc_info=True
            )

    return result


async def _async_write_sync_position(
    hass: HomeAssistant,
    runtime: JellyfinAssistRuntime,
    player: str,
    is_paused: bool,
    *,
    session: dict[str, Any] | None = None,
) -> None:
    """Persist a live or snapshotted session; failures never interrupt playback."""

    if player not in runtime.playback_targets:
        _LOGGER.debug("Progress skipped: player=%s reason=unlisted_target", player)
        return
    lock = runtime.playback_write_locks.setdefault(player, asyncio.Lock())
    async with lock:
        await _async_write_session_position(runtime, player, is_paused, session)


async def _async_write_session_position(
    runtime: JellyfinAssistRuntime,
    player: str,
    is_paused: bool,
    session: dict[str, Any] | None,
) -> None:
    """Serialize writes so an earlier timer cannot overwrite a later final position."""

    if session is None:
        session = runtime.playback_sessions.get(player)
    if not isinstance(session, dict) or not session.get("item_id"):
        _LOGGER.debug("Progress skipped: player=%s reason=no_session_or_item", player)
        return
    item_id = session["item_id"]
    accumulated = session.get("accumulated_playing_seconds")
    if not isinstance(accumulated, (int, float)) or not math.isfinite(accumulated):
        _LOGGER.debug(
            "Progress skipped: player=%s item=%s reason=invalid_position",
            player, item_id,
        )
        return
    if not is_paused:
        started_at = _timestamp(session.get("playing_started_at"))
        if started_at > 0:
            accumulated += max(0.0, datetime.now(timezone.utc).timestamp() - started_at)
    # Quantize once to whole seconds; Jellyfin uses 10,000,000 ticks per second.
    ticks = max(0, int(accumulated)) * 10_000_000
    duration = session.get("duration_seconds")
    if (
        isinstance(duration, (int, float))
        and math.isfinite(duration)
        and duration > 0
    ):
        if accumulated / duration * 100 >= COMPLETION_THRESHOLD_PERCENT:
            _LOGGER.debug(
                "Progress skipped: player=%s item=%s ticks=%s reason=completion_threshold",
                player, item_id, ticks,
            )
            return
    else:
        _LOGGER.debug(
            "Progress duration unknown: player=%s item=%s; writing tracked position",
            player, item_id,
        )
    _LOGGER.debug(
        "Progress write: player=%s item=%s user=%s ticks=%s paused=%s",
        player, item_id, runtime.user_id, ticks, is_paused,
    )
    try:
        await runtime.client.async_post_playing_items(
            item_id=item_id,
            position_ticks=ticks,
            is_paused=is_paused,
            device_id=player,
            _async_auth_refresh=runtime.async_trigger_reauth,
        )
    except (OSError, JellyfinApiError, asyncio.TimeoutError) as exc:
        _LOGGER.debug(
            "Progress failed: player=%s item=%s user=%s ticks=%s error=%s",
            player, item_id, runtime.user_id, ticks, exc,
        )
    else:
        _LOGGER.debug(
            "Progress saved: player=%s item=%s user=%s ticks=%s",
            player, item_id, runtime.user_id, ticks,
        )


async def _async_finish_incomplete_session(
    hass: HomeAssistant,
    runtime: JellyfinAssistRuntime,
    player: str,
    session: dict[str, Any] | None,
) -> None:
    """Save an incomplete session before discarding it, without popping a new one."""

    if isinstance(session, dict):
        await _async_write_sync_position(
            hass, runtime, player, True, session=dict(session)
        )
    if runtime.playback_sessions.get(player) is session:
        runtime.playback_sessions.pop(player, None)


async def _async_process_completion(
    hass: HomeAssistant,
    runtime: JellyfinAssistRuntime,
    *,
    player: str,
    old_state: Any,
    new_state: Any,
    expected_session: Any = _SESSION_UNSET,
) -> None:
    """Verify one playing->idle transition and advance its queue when complete."""

    if player not in runtime.playback_targets:
        _LOGGER.debug("Completion skipped: player=%s reason=unlisted_target", player)
        return
    playback_session = runtime.playback_sessions.get(player)
    if expected_session is not _SESSION_UNSET and playback_session is not expected_session:
        _LOGGER.debug("Completion skipped: player=%s reason=session_replaced", player)
        return
    queue_client = runtime.queue_client
    if queue_client is None:
        await _async_finish_incomplete_session(hass, runtime, player, playback_session)
        return

    attrs = getattr(old_state, "attributes", {}) or {}
    player_name = attrs.get("friendly_name") or player
    previous_title = attrs.get("media_title") or "Unknown"
    playback_percent = _estimate_playback_percent(
        old_state,
        new_state,
    )
    jellyfin_id = _extract_jellyfin_id(
        attrs.get("media_content_id")
    )

    playback_session = runtime.playback_sessions.get(player)
    session_playback_percent = _session_playback_percent(
        playback_session
    )
    session_item_id = (
        str(playback_session.get("item_id") or "")
        if isinstance(playback_session, Mapping)
        else ""
    )

    try:
        queue_response = await queue_client.async_get(player)
    except QueueStoreError as err:
        runtime.last_queue_advancement = {
            "player": player,
            "status": "queue_read_failed",
            "error": str(err),
            "session_playback_percent": session_playback_percent,
            "session_item_id": session_item_id,
        }

        await _async_finish_incomplete_session(hass, runtime, player, playback_session)

        await _async_notify_failure(
            hass,
            title="Jellyfin Assist Queue Read - FAILED",
            message=(
                "JELLYFIN ASSIST QUEUE READ FAILED\n\n"
                f"Player: {player_name} {player}\n"
                f"Completed candidate: {previous_title}\n"
                f"Error: {err}\n\n"
                "ACTION TAKEN: Queue state could not be verified, so no queue "
                "advancement was attempted."
            ),
        )
        return

    if runtime.playback_sessions.get(player) is not playback_session:
        return

    queue_status = int(queue_response.get("status", 0))
    queue_body = (
        dict(queue_response.get("content", {}))
        if isinstance(queue_response.get("content"), Mapping)
        else {}
    )
    queue_success = bool(queue_body.get("success", False))
    current = queue_body.get("current")
    current_id = (
        str(current.get("id", ""))
        if isinstance(current, Mapping)
        else ""
    )

    metadata_completion_confirmed = (
        playback_percent >= COMPLETION_THRESHOLD_PERCENT
        and bool(jellyfin_id)
        and queue_status == 200
        and queue_success
        and bool(current_id)
        and jellyfin_id == current_id
    )

    session_completion_confirmed = (
        playback_percent == 0.0
        and not jellyfin_id
        and session_playback_percent >= COMPLETION_THRESHOLD_PERCENT
        and bool(session_item_id)
        and queue_status == 200
        and queue_success
        and bool(current_id)
        and session_item_id == current_id
    )

    completion_confirmed = (
        metadata_completion_confirmed
        or session_completion_confirmed
    )

    completion_method = (
        "player_metadata"
        if metadata_completion_confirmed
        else "tracked_session"
        if session_completion_confirmed
        else None
    )

    if not completion_confirmed:
        runtime.last_queue_advancement = {
            "player": player,
            "status": "completion_rejected",
            "playback_percent": playback_percent,
            "jellyfin_id": jellyfin_id,
            "session_playback_percent": session_playback_percent,
            "session_item_id": session_item_id,
            "queue_current_id": current_id,
        }

        await _async_finish_incomplete_session(hass, runtime, player, playback_session)

        if queue_status != 200 or not queue_success:
            await _async_notify_failure(
                hass,
                title="Jellyfin Assist Queue Read - FAILED",
                message=(
                    "JELLYFIN ASSIST QUEUE READ FAILED\n\n"
                    f"Player: {player_name} {player}\n"
                    f"Completed candidate: {previous_title}\n"
                    f"Queue HTTP status: {queue_status}\n"
                    f"Queue response: {queue_body}\n\n"
                    "ACTION TAKEN: Queue state could not be verified, so no queue "
                    "advancement was attempted."
                ),
            )
        return

    if runtime.playback_sessions.get(player) is playback_session:
        runtime.playback_sessions.pop(player, None)

    await _async_mark_album_completion(runtime, current_id)

    # Album completion check: if every track in the album has been marked
    # complete, announce and either stop (no repeat) or reset tracking
    # (repeat — the queue store has already wrapped the index to track 1,
    # so ``async_next`` below will advance to track 1 and the caller will
    # play it).
    repeat_queue = bool(queue_body.get("repeat_queue", False))
    album_result = await _async_handle_album_completion(
        hass,
        runtime,
        player=player,
        completed_item_id=current_id,
        repeat_queue=repeat_queue,
    )
    if album_result is not None and not repeat_queue:
        # No repeat: the album finished and the player was stopped.
        # Do NOT advance the queue (``async_next`` would log queue_complete
        # on an already-finished album).
        runtime.last_queue_advancement = {
            "player": player,
            "status": "album_complete",
            "completed": current_id,
            "completion_method": completion_method,
            "album": album_result,
        }
        runtime.playback_sessions.pop(player, None)
        return

    try:
        next_response = await queue_client.async_next(player)
    except QueueStoreError as err:
        runtime.last_queue_advancement = {
            "player": player,
            "status": "queue_advance_failed",
            "error": str(err),
            "completion_method": completion_method,
        }
        await _async_notify_failure(
            hass,
            title="Jellyfin Assist Queue Advance - FAILED",
            message=(
                "JELLYFIN ASSIST QUEUE ADVANCE FAILED\n\n"
                f"Player: {player_name}\n"
                f"Completed: {previous_title}\n"
                f"Error: {err}\n\n"
                "ACTION TAKEN: Queue advancement failed. "
                "No next-item playback was started."
            ),
        )
        return

    next_status = int(next_response.get("status", 0))
    next_body = (
        dict(next_response.get("content", {}))
        if isinstance(next_response.get("content"), Mapping)
        else {}
    )
    next_success = bool(next_body.get("success", False))
    next_item = next_body.get("current")
    upcoming_count = int(
        next_body.get("upcoming_count", 0) or 0
    )

    if (
        next_status == 200
        and next_success
        and next_item is None
        and upcoming_count == 0
    ):
        runtime.last_queue_advancement = {
            "player": player,
            "status": "queue_complete",
            "completed": (
                next_body.get("completed")
                or next_body.get("finished")
            ),
            "completion_method": completion_method,
        }
        return

    if (
        next_status != 200
        or not next_success
        or (next_item is None and upcoming_count != 0)
        or not isinstance(next_item, Mapping)
    ):
        runtime.last_queue_advancement = {
            "player": player,
            "status": "queue_advance_failed",
            "queue_status": next_status,
            "queue_response": next_body,
            "completion_method": completion_method,
        }
        await _async_notify_failure(
            hass,
            title="Jellyfin Assist Queue Advance - FAILED",
            message=(
                "JELLYFIN ASSIST QUEUE ADVANCE FAILED\n\n"
                f"Player: {player_name}\n"
                f"Completed: {previous_title}\n"
                f"Queue HTTP status: {next_status}\n"
                f"Queue status: {next_body.get('status', '')}\n"
                f"Queue response: {next_body}\n\n"
                "ACTION TAKEN: Queue advancement failed. "
                "No next-item playback was started."
            ),
        )
        return

    next_item_dict = dict(next_item)

    try:
        playback_result = await async_play_item(
            hass,
            runtime,
            item=next_item_dict,
            media_player=player,
        )
    except Exception as err:
        playback_result = {
            "success": False,
            "error": str(err),
        }

    playback_success = (
        isinstance(playback_result, Mapping)
        and bool(playback_result.get("success", False))
    )

    runtime.last_queue_advancement = {
        "player": player,
        "status": (
            "playing_next"
            if playback_success
            else "playback_failed"
        ),
        "completed": (
            next_body.get("completed")
            or next_body.get("finished")
        ),
        "current": next_item_dict,
        "completion_method": completion_method,
    }

    if not playback_success:
        await _async_notify_failure(
            hass,
            title="Jellyfin Assist Next Item Playback - FAILED",
            message=(
                "JELLYFIN ASSIST NEXT ITEM PLAYBACK FAILED\n\n"
                f"Player: {player_name}\n"
                f"Completed: {previous_title}\n"
                f"Next queue item: {next_item_dict.get('name', '')}\n"
                f"Next item ID: {next_item_dict.get('id', '')}\n\n"
                "Queue advancement succeeded, but playback of the next item failed.\n"
                f"Playback response: {playback_result}"
            ),
        )


async def _async_periodic_write_sync_tasks(
    hass: HomeAssistant, runtime: JellyfinAssistRuntime
) -> None:
    """Write the tracked position for every player currently playing."""
    _LOGGER.debug(
        "Periodic progress callback: targets=%s sessions=%s",
        runtime.playback_targets, tuple(runtime.playback_sessions),
    )
    for player in runtime.playback_targets:
        state = hass.states.get(player)
        if state is None or state.state != "playing":
            _LOGGER.debug(
                "Periodic progress skipped: player=%s reason=not_playing state=%s",
                player, getattr(state, "state", None),
            )
            continue
        await _async_write_sync_position(
            hass, runtime, player=player, is_paused=False
        )


def _build_queue_advancement_handler(
    hass: HomeAssistant,
    entry: Any,
    runtime: JellyfinAssistRuntime,
) -> Any:
    """Build the state-change handler for the configured targets."""
    @callback
    def _async_state_changed(event: Any) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")

        if new_state is None:
            return

        player = str(
            event.data.get("entity_id")
            or getattr(new_state, "entity_id", "")
        )
        if player not in runtime.playback_targets:
            _LOGGER.debug("Tracking event skipped: player=%s reason=unlisted_target", player)
            return
        _LOGGER.debug(
            "Tracking event: player=%s old=%s new=%s session=%s",
            player, getattr(old_state, "state", None), getattr(new_state, "state", None),
            player in runtime.playback_sessions,
        )

        _update_playback_session(
            runtime,
            player=player,
            old_state=old_state,
            new_state=new_state,
        )

        new_player_state = getattr(new_state, "state", None)

        if new_player_state in {"off", "unavailable"}:
            # Capture the position before removing the session; the task runs later.
            session = runtime.playback_sessions.get(player)
            entry.async_create_background_task(
                hass,
                _async_write_sync_position(
                    hass,
                    runtime,
                    player=player,
                    is_paused=True,
                    session=dict(session) if isinstance(session, dict) else {},
                ),
                f"{DOMAIN} play sync {player}",
            )
            runtime.playback_sessions.pop(player, None)
            return

        # Pause write sync: when playback stops to a pause (not off/idle),
        # push the tracked position to PlayingItems. ``is_paused=True``.
        if getattr(old_state, "state", None) == "playing" and new_player_state in {
            "paused",
            "buffering",
        }:
            entry.async_create_background_task(
                hass,
                _async_write_sync_position(
                    hass,
                    runtime,
                    player=player,
                    is_paused=True,
                    session=dict(runtime.playback_sessions.get(player) or {}),
                ),
                f"{DOMAIN} play sync {player}",
            )
            return

        # Preserve the original explicit source-level completion guardrails.
        if getattr(old_state, "state", None) != "playing":
            if new_player_state == "idle":
                # Preserve the final position even after a pause followed by stop.
                session = runtime.playback_sessions.get(player)
                entry.async_create_background_task(
                    hass,
                    _async_write_sync_position(
                        hass,
                        runtime,
                        player=player,
                        is_paused=True,
                        session=dict(session) if isinstance(session, dict) else {},
                    ),
                    f"{DOMAIN} play sync {player}",
                )
                runtime.playback_sessions.pop(player, None)
            return

        if getattr(new_state, "state", None) != "idle":
            return

        entry.async_create_background_task(
            hass,
            _async_process_completion(
                hass,
                runtime,
                player=player,
                old_state=old_state,
                new_state=new_state,
                expected_session=runtime.playback_sessions.get(player),
            ),
            f"{DOMAIN} queue advancement {player}",
        )

    return _async_state_changed


def async_setup_queue_advancement(
    hass: HomeAssistant,
    entry: Any,
    runtime: JellyfinAssistRuntime,
) -> None:
    """Register state listeners for configured playback targets."""

    targets = tuple(runtime.playback_targets)
    runtime.queue_advancement_targets = targets
    _LOGGER.debug(
        "Tracking setup: entry=%s targets=%s interval_seconds=%s",
        runtime.entry_id, targets, PLAYBACK_WRITESYNC_INTERVAL_SECONDS,
    )
    if not targets:
        return

    handler = _build_queue_advancement_handler(hass, entry, runtime)

    unsubscribe = async_track_state_change_event(
        hass,
        list(targets),
        handler,
    )
    entry.async_on_unload(unsubscribe)

    @callback
    def _async_periodic_write_sync(_now: Any) -> None:
        # Only write for players that are actively playing; the position is
        # read from the existing ``accumulated_playing_seconds`` accumulator.
        entry.async_create_background_task(
            hass,
            _async_periodic_write_sync_tasks(
                hass,
                runtime,
            ),
            f"{DOMAIN} play sync periodic",
        )

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            interval=timedelta(seconds=PLAYBACK_WRITESYNC_INTERVAL_SECONDS),
            action=_async_periodic_write_sync,
        )
    )


__all__ = [
    "COMPLETION_THRESHOLD_PERCENT",
    "_estimate_playback_percent",
    "_extract_jellyfin_id",
    "_update_playback_session",
    "_session_playback_percent",
    "_async_process_completion",
    "async_setup_queue_advancement",
]
