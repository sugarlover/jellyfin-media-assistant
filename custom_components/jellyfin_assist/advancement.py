"""Native automatic queue advancement for configured media players."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import logging
import re
from typing import Any, Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN
from .queue_store import QueueStoreError
from .media_actions import async_play_item
from .runtime import JellyfinAssistRuntime

_LOGGER = logging.getLogger(__name__)

COMPLETION_THRESHOLD_PERCENT: Final = 95.0
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
                return datetime.fromisoformat(normalized.replace("Z", "+00:00")).timestamp()
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
    position_reference_value = reported_position if position_sample_is_current else 0.0
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
        max(reported_position, extrapolated_position, continuous_playing_seconds),
        duration,
    )
    return round(estimated_position / duration * 100, 2)


def _extract_jellyfin_id(content_id: Any) -> str:
    """Extract the Jellyfin item id from the media player's content URL."""

    if not content_id:
        return ""
    match = _CONTENT_ID_PATTERN.search(str(content_id))
    return match.group(1) if match else ""


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
            {"title": title, "message": message},
            blocking=False,
        )
    except Exception:  # pragma: no cover - notification failure must not break playback
        _LOGGER.exception("Could not create Jellyfin Assist failure notification")


async def _async_process_completion(
    hass: HomeAssistant,
    runtime: JellyfinAssistRuntime,
    *,
    player: str,
    old_state: Any,
    new_state: Any,
) -> None:
    """Verify one playing->idle transition and advance its queue when complete."""

    queue_client = runtime.queue_client
    if queue_client is None:
        return

    attrs = getattr(old_state, "attributes", {}) or {}
    player_name = attrs.get("friendly_name") or player
    previous_title = attrs.get("media_title") or "Unknown"
    playback_percent = _estimate_playback_percent(old_state, new_state)
    jellyfin_id = _extract_jellyfin_id(attrs.get("media_content_id"))

    try:
        queue_response = await queue_client.async_get(player)
    except QueueStoreError as err:
        runtime.last_queue_advancement = {
            "player": player,
            "status": "queue_read_failed",
            "error": str(err),
        }
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

    queue_status = int(queue_response.get("status", 0))
    queue_body = (
        dict(queue_response.get("content", {}))
        if isinstance(queue_response.get("content"), Mapping)
        else {}
    )
    queue_success = bool(queue_body.get("success", False))
    current = queue_body.get("current")
    current_id = str(current.get("id", "")) if isinstance(current, Mapping) else ""

    completion_confirmed = (
        playback_percent >= COMPLETION_THRESHOLD_PERCENT
        and bool(jellyfin_id)
        and queue_status == 200
        and queue_success
        and bool(current_id)
        and jellyfin_id == current_id
    )
    if not completion_confirmed:
        runtime.last_queue_advancement = {
            "player": player,
            "status": "completion_rejected",
            "playback_percent": playback_percent,
            "jellyfin_id": jellyfin_id,
            "queue_current_id": current_id,
        }
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

    try:
        next_response = await queue_client.async_next(player)
    except QueueStoreError as err:
        runtime.last_queue_advancement = {
            "player": player,
            "status": "queue_advance_failed",
            "error": str(err),
        }
        await _async_notify_failure(
            hass,
            title="Jellyfin Assist Queue Advance - FAILED",
            message=(
                "JELLYFIN ASSIST QUEUE ADVANCE FAILED\n\n"
                f"Player: {player_name}\n"
                f"Completed: {previous_title}\n"
                f"Error: {err}\n\n"
                "ACTION TAKEN: Queue advancement failed. No next-item playback was started."
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
    upcoming_count = int(next_body.get("upcoming_count", 0) or 0)

    if (
        next_status == 200
        and next_success
        and next_item is None
        and upcoming_count == 0
    ):
        runtime.last_queue_advancement = {
            "player": player,
            "status": "queue_complete",
            "completed": next_body.get("completed") or next_body.get("finished"),
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
                "ACTION TAKEN: Queue advancement failed. No next-item playback was started."
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
        playback_result = {"success": False, "error": str(err)}

    playback_success = isinstance(playback_result, Mapping) and bool(
        playback_result.get("success", False)
    )
    runtime.last_queue_advancement = {
        "player": player,
        "status": "playing_next" if playback_success else "playback_failed",
        "completed": next_body.get("completed") or next_body.get("finished"),
        "current": next_item_dict,
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


def async_setup_queue_advancement(
    hass: HomeAssistant,
    entry: Any,
    runtime: JellyfinAssistRuntime,
) -> None:
    """Register playing->idle listeners for configured playback targets."""

    targets = tuple(runtime.playback_targets)
    runtime.queue_advancement_targets = targets
    if not targets:
        return

    @callback
    def _async_state_changed(event: Any) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if old_state is None or new_state is None:
            return
        if getattr(old_state, "state", None) != "playing":
            return
        if getattr(new_state, "state", None) != "idle":
            return
        player = str(event.data.get("entity_id") or getattr(new_state, "entity_id", ""))
        if not player:
            return
        entry.async_create_background_task(
            hass,
            _async_process_completion(
                hass,
                runtime,
                player=player,
                old_state=old_state,
                new_state=new_state,
            ),
            f"{DOMAIN} queue advancement {player}",
        )

    unsubscribe = async_track_state_change_event(hass, list(targets), _async_state_changed)
    entry.async_on_unload(unsubscribe)


__all__ = [
    "COMPLETION_THRESHOLD_PERCENT",
    "_estimate_playback_percent",
    "_extract_jellyfin_id",
    "_async_process_completion",
    "async_setup_queue_advancement",
]
