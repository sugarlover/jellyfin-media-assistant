"""Native Chromecast playback orchestration for Jellyfin Media Assistant.

Portions of the orchestration are adapted from JellyHA 1.2.0 ``services.py``
(MIT License), Copyright (c) 2026 zupancicmarko. JellyHA is not a runtime
dependency; retained attribution and source provenance live under
``THIRD_PARTY_NOTICES.md`` and ``docs/provenance/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from homeassistant.helpers.event import async_track_state_change_event

from .playback_strategy import ChromecastPlaybackStrategy
from .runtime import JellyfinAssistRuntime


class ChromecastPlaybackError(RuntimeError):
    """Base class for native Chromecast playback preparation failures."""


class NoNextUpEpisodeError(ChromecastPlaybackError):
    """Raised when a Series/Season has no Jellyfin Next Up episode."""


@dataclass(frozen=True, slots=True)
class PreparedPlaybackItem:
    """One concrete Jellyfin item ready for Chromecast strategy selection."""

    requested_item_id: str
    item_id: str
    item: dict[str, Any]
    resolved_from_type: str | None = None

    @property
    def item_type(self) -> str:
        """Return the Jellyfin item type used by playback strategy selection."""

        return str(self.item.get("Type") or "Video")


async def async_prepare_playback_item(
    runtime: JellyfinAssistRuntime,
    item_id: str,
) -> PreparedPlaybackItem:
    """Fetch one item natively and resolve Series/Season through Jellyfin Next Up."""

    requested_item_id = item_id.strip()
    if not requested_item_id:
        raise ValueError("Jellyfin item ID is required")

    raw_item = await runtime.client.async_get_item(
        runtime.user_id,
        requested_item_id,
    )
    if not isinstance(raw_item, Mapping):
        raise ChromecastPlaybackError("Jellyfin item response was not an object")

    item = dict(raw_item)
    item_type = str(item.get("Type") or "")

    if item_type in {"Series", "Season"}:
        series_id = (
            requested_item_id
            if item_type == "Series"
            else str(item.get("SeriesId") or "").strip()
        )
        if series_id:
            next_episode = await runtime.client.async_get_next_up_episode(
                runtime.user_id,
                series_id,
            )
            if next_episode is None:
                raise NoNextUpEpisodeError(
                    f"No Next Up episode is available for Jellyfin "
                    f"{item_type.lower()} {requested_item_id}."
                )

            item = dict(next_episode)
            resolved_item_id = str(item.get("Id") or "").strip()
            if not resolved_item_id:
                raise ChromecastPlaybackError(
                    "Jellyfin Next Up response did not include an item ID"
                )

            return PreparedPlaybackItem(
                requested_item_id=requested_item_id,
                item_id=resolved_item_id,
                item=item,
                resolved_from_type=item_type,
            )

    return PreparedPlaybackItem(
        requested_item_id=requested_item_id,
        item_id=requested_item_id,
        item=item,
    )


def build_play_media_data(
    runtime: JellyfinAssistRuntime,
    target_entity_id: str,
    prepared: PreparedPlaybackItem,
    device_model: str,
    *,
    force_start_position_ticks: int | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the exact Home Assistant play_media payload used for native casting."""

    media_info = ChromecastPlaybackStrategy.analyze_media(prepared.item)
    metadata: dict[str, Any] = {
        "title": prepared.item.get("Name", "Jellyfin Media"),
        "images": [
            {
                "url": runtime.client.get_image_url(
                    prepared.item_id,
                    "Primary",
                )
            }
        ],
    }

    # Extract PlaybackPositionTicks from UserData for resume support.
    start_position_ticks: int | None = None
    if force_start_position_ticks is not None:
        start_position_ticks = force_start_position_ticks
    else:
        user_data = prepared.item.get("UserData")
        if isinstance(user_data, Mapping):
            raw_ticks = user_data.get("PlaybackPositionTicks")
            if isinstance(raw_ticks, (int, float)) and raw_ticks > 0:
                start_position_ticks = int(raw_ticks)

    playback_info = ChromecastPlaybackStrategy.get_playback_info(
        runtime.client.server_url,
        runtime.client.api_key,
        prepared.item_id,
        media_info,
        device_model,
        item_type=prepared.item_type,
        start_position_ticks=start_position_ticks,
    )

    if prepared.item_type == "Episode":
        metadata.update(
            {
                "metadataType": 1,
                "seriesTitle": prepared.item.get("SeriesName"),
                "season": prepared.item.get("ParentIndexNumber"),
                "episode": prepared.item.get("IndexNumber"),
            }
        )

    service_data = {
        "entity_id": target_entity_id,
        "media_content_id": playback_info["media_url"],
        "media_content_type": playback_info["content_type"],
        "extra": {
            "title": metadata["title"],
            "thumb": metadata["images"][0]["url"],
            "autoplay": True,
            "metadata": metadata,
        },
    }

    return service_data, playback_info


async def async_play_on_chromecast(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    target_entity_id: str,
    item_id: str,
    start_position_ticks: int | None = None,
) -> dict[str, Any]:
    """Execute the proven native Chromecast playback path."""

    normalized_target = str(target_entity_id or "").strip()
    normalized_item_id = str(item_id or "").strip()

    if not normalized_target.startswith("media_player."):
        raise ValueError("Choose a Home Assistant media_player entity.")

    if not normalized_item_id:
        raise ValueError("Jellyfin item ID is required")

    prepared = await async_prepare_playback_item(
        runtime,
        normalized_item_id,
    )

    model_name, is_legacy = await hass.async_add_executor_job(
        ChromecastPlaybackStrategy.discover_chromecast_model,
        hass,
        normalized_target,
    )

    service_data, playback_info = build_play_media_data(
        runtime,
        normalized_target,
        prepared,
        model_name,
        force_start_position_ticks=start_position_ticks,
    )

    # D2: build_play_media_data already computes start_position_ticks
    # (playback.py:125-133) from UserData.PlaybackPositionTicks. Thread
    # it into the session dict so accumulated_playing_seconds starts
    # at the resume offset instead of 0.
    resume_offset_seconds = (
        start_position_ticks / 10_000_000
        if start_position_ticks is not None
        else 0.0
    )

    await hass.services.async_call(
        "media_player",
        "play_media",
        service_data,
        blocking=True,
    )

    run_time_ticks = prepared.item.get("RunTimeTicks")
    try:
        duration_seconds = max(
            float(run_time_ticks or 0) / 10_000_000,
            0.0,
        )
    except (TypeError, ValueError):
        duration_seconds = 0.0

    current_state = (
        hass.states.get(normalized_target)
        if getattr(hass, "states", None)
        else None
    )

    playing_started_at = (
        datetime.now(timezone.utc)
        if getattr(current_state, "state", None) == "playing"
        else None
    )

    runtime.playback_sessions[normalized_target] = {
        "item_id": prepared.item_id,
        "requested_item_id": prepared.requested_item_id,
        "duration_seconds": duration_seconds,
        "start_position_ticks": start_position_ticks,
        "accumulated_playing_seconds": resume_offset_seconds,
        "playing_started_at": playing_started_at,
    }

    # D4: if this target is not in the statically-configured playback
    # targets, dynamically register a state-change listener so the
    # session is tracked even for unlisted targets. The handler is the
    # same one built for configured targets (advancement.py module-level
    # factory), so sessions advance, pause-write, and off/idle pop just
    # like a configured target. The listener is released on every pop
    # path (handler-driven) plus at entry unload (registered in
    # async_setup_queue_advancement), so nothing leaks.
    if (
        normalized_target not in runtime.playback_targets
        and normalized_target not in runtime.playback_session_listeners
    ):
        entry = getattr(runtime, "_config_entry", None)
        if entry is not None:
            # Lazy import: advancement imports media_actions -> playback
            # (this module) -> back to advancement would be a circular
            # import at module load time. Deferring to call time avoids it.
            from .advancement import _build_queue_advancement_handler

            handler = _build_queue_advancement_handler(hass, entry, runtime)
            unsubscribe = async_track_state_change_event(
                hass,
                [normalized_target],
                handler,
            )
            runtime.playback_session_listeners[normalized_target] = unsubscribe

    return {
        "success": True,
        "status": "playing",
        "entity_id": normalized_target,
        "requested_item_id": prepared.requested_item_id,
        "item_id": prepared.item_id,
        "item_name": prepared.item.get("Name"),
        "item_type": prepared.item_type,
        "resolved_from_type": prepared.resolved_from_type,
        "device_model": model_name,
        "legacy_chromecast": is_legacy,
        "playback_mode": playback_mode(playback_info),
        "media_content_type": playback_info["content_type"],
        "start_position_ticks": start_position_ticks,
    }


def playback_mode(playback_info: Mapping[str, str]) -> str:
    """Return a non-secret diagnostic label for the chosen playback path."""

    media_url = str(playback_info.get("media_url") or "")
    return "transcode" if "/master.m3u8" in media_url else "direct_play"


__all__ = [
    "ChromecastPlaybackError",
    "NoNextUpEpisodeError",
    "PreparedPlaybackItem",
    "async_prepare_playback_item",
    "async_play_on_chromecast",
    "build_play_media_data",
    "playback_mode",
]