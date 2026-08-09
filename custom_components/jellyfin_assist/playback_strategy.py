"""Chromecast playback strategy compatible with the stable JellyHA path.

Portions of the media-analysis and playback URL selection logic are adapted
from JellyHA 1.2.0 ``media_strategy.py`` (MIT License).

Copyright (c) 2026 zupancicmarko

The upstream reference snapshot and full MIT license are retained under
``reference/current-working/jellyha``.  This module intentionally preserves
that known-working behavior while Jellyfin Media Assistant migrates playback
behind a live-tested rollback boundary.
"""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


class ChromecastPlaybackStrategy:
    """Determine Jellyfin stream URLs compatible with a Chromecast target."""

    @staticmethod
    def analyze_media(item: dict[str, Any]) -> dict[str, Any]:
        """Extract the codec and dimension fields used by the stable strategy."""

        media_streams = item.get("MediaStreams", [])
        info = {
            "container": (item.get("Container") or "unknown").lower(),
            "video_codec": "unknown",
            "video_height": 0,
            "bit_depth": 8,
            "audio_codec": "unknown",
            "audio_channels": 2,
        }

        for stream in media_streams:
            if stream.get("Type") == "Video":
                info["video_codec"] = (stream.get("Codec") or "unknown").lower()
                info["video_height"] = int(stream.get("Height") or 0)
                info["bit_depth"] = int(stream.get("BitDepth") or 8)
            elif stream.get("Type") == "Audio" and stream.get("Index") == 1:
                # Preserve JellyHA's preference for stream index 1 when present.
                info["audio_codec"] = (stream.get("Codec") or "unknown").lower()
                info["audio_channels"] = int(stream.get("Channels") or 2)

        if info["audio_codec"] == "unknown":
            for stream in media_streams:
                if stream.get("Type") == "Audio":
                    info["audio_codec"] = (stream.get("Codec") or "unknown").lower()
                    info["audio_channels"] = int(stream.get("Channels") or 2)
                    break

        return info

    @staticmethod
    def discover_chromecast_model(hass: Any, entity_id: str) -> tuple[str, bool]:
        """Discover the Chromecast model using JellyHA-compatible pychromecast logic.

        This function is blocking and must be called from Home Assistant's executor.
        The boolean return value is retained for exact compatibility with the
        upstream helper even though URL selection currently uses the model string.
        """

        model_name = "Unknown"
        is_legacy = False

        try:
            entity_state = hass.states.get(entity_id)
            if entity_state:
                friendly_name = entity_state.attributes.get("friendly_name")
                if friendly_name:
                    import pychromecast  # type: ignore[import-not-found]

                    chromecasts, browser = pychromecast.get_listed_chromecasts(
                        [friendly_name],
                        discovery_timeout=5.0,
                    )
                    try:
                        if chromecasts:
                            cast_device = chromecasts[0]
                            model_name = cast_device.model_name
                            if model_name == "Chromecast":
                                is_legacy = True
                    finally:
                        if browser:
                            browser.stop_discovery()
        except Exception as err:  # pragma: no cover - exercised through mocks later
            _LOGGER.warning("Could not detect Chromecast model: %s", err)

        return model_name, is_legacy

    @staticmethod
    def get_playback_info(
        server_url: str,
        api_key: str,
        item_id: str,
        media_info: dict[str, Any],
        device_model: str,
        item_type: str = "Video",
    ) -> dict[str, str]:
        """Return the stable JellyHA-compatible media URL and content type."""

        is_legacy_device = device_model == "Chromecast"

        video_codec = media_info["video_codec"]
        video_height = media_info["video_height"]
        bit_depth = media_info["bit_depth"]
        audio_codec = media_info["audio_codec"]
        audio_channels = media_info["audio_channels"]
        container = media_info.get("container", "unknown")

        if item_type == "Audio":
            is_format_standard = audio_codec in ["mp3", "aac", "ac3", "wav"]
            should_direct_play = False

            if is_legacy_device:
                if (
                    is_format_standard
                    and audio_channels <= 2
                    and container not in ["flac", "alac"]
                ):
                    should_direct_play = True
            else:
                should_direct_play = True

            if should_direct_play:
                content_type = "audio/mpeg"
                if container == "flac":
                    content_type = "audio/flac"
                elif container in ["m4a", "aac"]:
                    content_type = "audio/mp4"
                elif container in ["ogg", "oga"]:
                    content_type = "audio/ogg"
                elif container == "wav":
                    content_type = "audio/wav"

                _LOGGER.info(
                    "Strategy Selected: DIRECT PLAY (Audio - %s)", content_type
                )
                return {
                    "media_url": (
                        f"{server_url}/Audio/{item_id}/stream"
                        f"?static=true&api_key={api_key}"
                    ),
                    "content_type": content_type,
                }

            _LOGGER.info("Strategy Selected: TRANSCODE (Legacy Audio HLS)")
            media_url = (
                f"{server_url}/Audio/{item_id}/master.m3u8"
                f"?api_key={api_key}"
                f"&DeviceId=JellyHA_Cast"
                f"&MediaSourceId={item_id}"
                f"&AudioCodec=mp3"
                f"&AudioBitrate=320000"
                f"&TranscodingContainer=ts"
                f"&TranscodingProtocol=hls"
            )
            return {
                "media_url": media_url,
                "content_type": "application/x-mpegURL",
            }

        is_format_standard = (
            video_codec in ["h264", "avc"]
            and bit_depth == 8
            and audio_codec in ["aac", "mp3", "ac3"]
        )

        should_direct_play = False
        if is_legacy_device:
            if is_format_standard and video_height <= 720 and audio_channels <= 2:
                should_direct_play = True
        elif is_format_standard and video_height <= 1080:
            should_direct_play = True

        reason = (
            f"Codec={video_codec}/{audio_codec}, "
            f"H={video_height}p, Ch={audio_channels}, "
            f"Legacy={is_legacy_device}"
        )
        _LOGGER.info(
            "Media Analysis: %s | DirectPlay Decision: %s",
            reason,
            should_direct_play,
        )

        if should_direct_play:
            log_mode = "DIRECT (H.264)"
            media_url = (
                f"{server_url}/Videos/{item_id}/stream"
                f"?Static=true"
                f"&api_key={api_key}"
                f"&VideoCodec=h264"
                f"&AudioCodec=aac"
            )
            content_type = "video/mp4"
        elif is_legacy_device:
            log_mode = "TRANSCODE (Legacy Gen 1 - Force 720p/Stereo)"
            media_url = (
                f"{server_url}/Videos/{item_id}/master.m3u8"
                f"?api_key={api_key}"
                f"&MediaSourceId={item_id}"
                f"&Width=1280"
                f"&Height=720"
                f"&VideoBitrate=18000000"
                f"&MaxStreamingBitrate=18000000"
                f"&EncoderPreset=veryfast"
                f"&VideoCodec=h264"
                f"&h264-profile=high"
                f"&h264-level=41"
                f"&h264-videobitdepth=8"
                f"&AudioCodec=aac"
                f"&AudioBitrate=256000"
                f"&AudioSampleRate=48000"
                f"&TranscodingMaxAudioChannels=2"
                f"&SegmentContainer=ts"
                f"&MinSegments=2"
                f"&BreakOnNonKeyFrames=False"
                f"&CopyTimestamps=true"
                f"&EnableSubtitlesInManifest=false"
            )
            content_type = "application/x-mpegURL"
        else:
            log_mode = "TRANSCODE (Modern HQ)"
            media_url = (
                f"{server_url}/Videos/{item_id}/master.m3u8"
                f"?api_key={api_key}"
                f"&MediaSourceId={item_id}"
                f"&Width=1920"
                f"&Height=1080"
                f"&VideoBitrate=20000000"
                f"&MaxStreamingBitrate=20000000"
                f"&EncoderPreset=medium"
                f"&VideoCodec=h264"
                f"&h264-profile=high"
                f"&h264-level=51"
                f"&h264-videobitdepth=8"
                f"&AudioCodec=aac"
                f"&AudioBitrate=320000"
                f"&TranscodingMaxAudioChannels=6"
                f"&SegmentContainer=ts"
                f"&MinSegments=2"
                f"&BreakOnNonKeyFrames=False"
                f"&CopyTimestamps=true"
                f"&EnableSubtitlesInManifest=false"
            )
            content_type = "application/x-mpegURL"

        safe_url = media_url.replace(api_key, "REDACTED")
        _LOGGER.info("Strategy Selected: %s", log_mode)
        _LOGGER.debug("Target URL: %s", safe_url)

        return {
            "media_url": media_url,
            "content_type": content_type,
            "log_mode": log_mode,
        }


__all__ = ["ChromecastPlaybackStrategy"]
