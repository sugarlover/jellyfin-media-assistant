"""Native Chromecast playback orchestration for Jellyfin Media Assistant.

The playback sequence intentionally preserves the installed JellyHA 1.2.0
``play_on_chromecast`` contract while keeping the live production script on
JellyHA until household parity testing is complete.

Portions of the orchestration are adapted from JellyHA 1.2.0 ``services.py``
(MIT License), Copyright (c) 2026 zupancicmarko. The frozen reference and
license remain under ``reference/current-working/jellyha``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

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

    raw_item = await runtime.client.async_get_item(runtime.user_id, requested_item_id)
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
                    f"No Next Up episode is available for Jellyfin {item_type.lower()} {requested_item_id}."
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
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the exact Home Assistant play_media payload used for native casting."""

    media_info = ChromecastPlaybackStrategy.analyze_media(prepared.item)
    playback_info = ChromecastPlaybackStrategy.get_playback_info(
        runtime.client.server_url,
        runtime.client.api_key,
        prepared.item_id,
        media_info,
        device_model,
        item_type=prepared.item_type,
    )

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
) -> dict[str, Any]:
    """Execute the proven native Chromecast playback path."""

    normalized_target = str(target_entity_id or "").strip()
    normalized_item_id = str(item_id or "").strip()
    if not normalized_target.startswith("media_player."):
        raise ValueError("Choose a Home Assistant media_player entity.")
    if not normalized_item_id:
        raise ValueError("Jellyfin item ID is required")

    prepared = await async_prepare_playback_item(runtime, normalized_item_id)
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
    )
    await hass.services.async_call(
        "media_player",
        "play_media",
        service_data,
        blocking=True,
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
