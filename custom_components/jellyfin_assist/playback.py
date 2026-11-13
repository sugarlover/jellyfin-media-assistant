"""Native Chromecast playback orchestration for Jellyfin Media Assistant.

Portions of the orchestration are adapted from JellyHA 1.2.0 ``services.py``
(MIT License), Copyright (c) 2026 zupancicmarko. JellyHA is not a runtime
dependency; retained attribution and source provenance live under
``THIRD_PARTY_NOTICES.md`` and ``docs/provenance/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Mapping

from .configuration import require_playback_target
from .playback_strategy import ChromecastPlaybackStrategy
from .runtime import JellyfinAssistRuntime


_LOGGER = logging.getLogger(__name__)


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


def _resume_ticks(item: Mapping[str, Any], override: int | None) -> int | None:
    """Use the same effective offset for the media URL and tracking session."""

    if override is not None:
        if override < 0:
            raise ValueError("Start position cannot be negative")
        return int(override)
    user_data = item.get("UserData")
    ticks = user_data.get("PlaybackPositionTicks") if isinstance(user_data, Mapping) else None
    return int(ticks) if isinstance(ticks, (int, float)) and ticks > 0 else None


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

    start_position_ticks = _resume_ticks(prepared.item, force_start_position_ticks)

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

    # D1: resume offset travels as extra.current_time (seconds).
    # Absent for fresh playback; present when a resume tick exists.
    resume_offset_seconds: float | None = (
        start_position_ticks / 10_000_000
        if start_position_ticks is not None
        else None
    )

    extra: dict[str, Any] = {
        "title": metadata["title"],
        "thumb": metadata["images"][0]["url"],
        "autoplay": True,
        "metadata": metadata,
    }
    if resume_offset_seconds is not None:
        extra["current_time"] = resume_offset_seconds

    # T1: pychromecast 14.0.10 defaults stream_type to "LIVE"; the Google
    # default media receiver ignores currentTime on LIVE streams.
    # BUFFERED is required for direct-play VOD so the seek takes effect.
    if playback_info["content_type"].startswith("video/"):
        extra["stream_type"] = "BUFFERED"

    service_data = {
        "entity_id": target_entity_id,
        "media_content_id": playback_info["media_url"],
        "media_content_type": playback_info["content_type"],
        "extra": extra,
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

    require_playback_target(runtime.playback_targets, normalized_target)

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

    start_position_ticks = _resume_ticks(prepared.item, start_position_ticks)

    service_data, playback_info = build_play_media_data(
        runtime,
        normalized_target,
        prepared,
        model_name,
        force_start_position_ticks=start_position_ticks,
    )

    resume_offset_seconds = (
        start_position_ticks / 10_000_000
        if start_position_ticks is not None
        else 0.0
    )

    # T3: guard the accumulated offset when the receiver will not honour
    # the seek. The Cast receiver honours the seek in two cases:
    #   1. Direct-play video: extra.current_time + stream_type=BUFFERED
    #      are both sent (T2).
    #   2. Audio: the URL StartPositionTicks param is honoured (T1).
    # For transcode video (m3u8), the receiver runs a LIVE stream and
    # ignores extra.current_time (T1 evidence), so the seek is NOT
    # supported. In that case, do NOT seed the session with the resume
    # offset; start at 0 so we never over-report progress.
    seek_supported = (
        start_position_ticks is not None
        and (
            (
                playback_info["content_type"].startswith("video/")
                and "/master.m3u8" not in playback_info["media_url"]
            )
            or playback_info["content_type"].startswith("audio/")
        )
    )
    accumulated_initial = (
        resume_offset_seconds if seek_supported else 0.0
    )

    requested_at = datetime.now(timezone.utc)
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

    playing_started_at = None
    if getattr(current_state, "state", None) == "playing":
        state_started_at = getattr(current_state, "last_changed", None)
        playing_started_at = (
            max(requested_at, state_started_at)
            if isinstance(state_started_at, datetime)
            else datetime.now(timezone.utc)
        )

    runtime.playback_sessions[normalized_target] = {
        "item_id": prepared.item_id,
        "requested_item_id": prepared.requested_item_id,
        "duration_seconds": duration_seconds,
        "start_position_ticks": start_position_ticks,
        "accumulated_playing_seconds": accumulated_initial,
        "playing_started_at": playing_started_at,
    }

    _LOGGER.debug(
        "Tracking initialized: player=%s item=%s user=%s duration_seconds=%s "
        "resume_ticks=%s state=%s playing_started_at=%s targets=%s",
        normalized_target, prepared.item_id, runtime.user_id, duration_seconds,
        start_position_ticks, getattr(current_state, "state", None),
        playing_started_at, runtime.playback_targets,
    )

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