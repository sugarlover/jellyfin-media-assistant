"""Regression tests for the supported Chromecast playback strategy."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.jellyfin_assist.playback_strategy import (
    ChromecastPlaybackStrategy,
)


def _video_item(
    *,
    container: str = "mp4",
    video_codec: str = "h264",
    video_height: int = 1080,
    bit_depth: int = 8,
    audio_codec: str = "aac",
    audio_channels: int = 2,
) -> dict[str, Any]:
    return {
        "Container": container,
        "MediaStreams": [
            {
                "Type": "Video",
                "Codec": video_codec,
                "Height": video_height,
                "BitDepth": bit_depth,
                "Index": 0,
            },
            {
                "Type": "Audio",
                "Codec": audio_codec,
                "Channels": audio_channels,
                "Index": 1,
            },
        ],
    }


def _audio_item(
    *,
    container: str,
    audio_codec: str,
    audio_channels: int = 2,
    index: int = 1,
) -> dict[str, Any]:
    return {
        "Container": container,
        "MediaStreams": [
            {
                "Type": "Audio",
                "Codec": audio_codec,
                "Channels": audio_channels,
                "Index": index,
            }
        ],
    }


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (
            _video_item(),
            {
                "container": "mp4",
                "video_codec": "h264",
                "video_height": 1080,
                "bit_depth": 8,
                "audio_codec": "aac",
                "audio_channels": 2,
            },
        ),
        (
            _video_item(container="MKV", video_codec="HEVC", bit_depth=10, audio_codec="AC3", audio_channels=6),
            {
                "container": "mkv",
                "video_codec": "hevc",
                "video_height": 1080,
                "bit_depth": 10,
                "audio_codec": "ac3",
                "audio_channels": 6,
            },
        ),
        (
            _audio_item(container="flac", audio_codec="flac"),
            {
                "container": "flac",
                "video_codec": "unknown",
                "video_height": 0,
                "bit_depth": 8,
                "audio_codec": "flac",
                "audio_channels": 2,
            },
        ),
    ],
)
def test_analyze_media_returns_stable_strategy_inputs(
    item: dict[str, Any], expected: dict[str, Any]
) -> None:
    assert ChromecastPlaybackStrategy.analyze_media(item) == expected


@pytest.mark.parametrize(
    (
        "item",
        "device_model",
        "item_type",
        "expected_content_type",
        "expected_path",
        "expected_mode",
    ),
    [
        (
            _video_item(),
            "Chromecast Ultra",
            "Movie",
            "video/mp4",
            "/Videos/item-123/stream?",
            "DIRECT (H.264)",
        ),
        (
            _video_item(video_codec="hevc"),
            "Chromecast Ultra",
            "Movie",
            "application/x-mpegURL",
            "/Videos/item-123/master.m3u8?",
            "TRANSCODE (Modern HQ)",
        ),
        (
            _video_item(video_height=720),
            "Chromecast",
            "Movie",
            "video/mp4",
            "/Videos/item-123/stream?",
            "DIRECT (H.264)",
        ),
        (
            _video_item(video_height=1080),
            "Chromecast",
            "Movie",
            "application/x-mpegURL",
            "/Videos/item-123/master.m3u8?",
            "TRANSCODE (Legacy Gen 1 - Force 720p/Stereo)",
        ),
        (
            _video_item(bit_depth=10),
            "Chromecast Ultra",
            "Episode",
            "application/x-mpegURL",
            "/Videos/item-123/master.m3u8?",
            "TRANSCODE (Modern HQ)",
        ),
        (
            _audio_item(container="flac", audio_codec="flac"),
            "Chromecast Ultra",
            "Audio",
            "audio/flac",
            "/Audio/item-123/stream?",
            None,
        ),
        (
            _audio_item(container="flac", audio_codec="flac"),
            "Chromecast",
            "Audio",
            "application/x-mpegURL",
            "/Audio/item-123/master.m3u8?",
            None,
        ),
        (
            _audio_item(container="mp3", audio_codec="mp3"),
            "Chromecast",
            "Audio",
            "audio/mpeg",
            "/Audio/item-123/stream?",
            None,
        ),
        (
            _audio_item(container="m4a", audio_codec="aac"),
            "Chromecast Ultra",
            "Audio",
            "audio/mp4",
            "/Audio/item-123/stream?",
            None,
        ),
    ],
)
def test_playback_strategy_regression_contract(
    item: dict[str, Any],
    device_model: str,
    item_type: str,
    expected_content_type: str,
    expected_path: str,
    expected_mode: str | None,
) -> None:
    media_info = ChromecastPlaybackStrategy.analyze_media(item)
    result = ChromecastPlaybackStrategy.get_playback_info(
        "http://jellyfin:8096",
        "secret-token",
        "item-123",
        media_info,
        device_model,
        item_type=item_type,
    )

    assert result["content_type"] == expected_content_type
    assert expected_path in result["media_url"]
    assert "api_key=secret-token" in result["media_url"]
    if expected_mode is None:
        assert "log_mode" not in result
    else:
        assert result["log_mode"] == expected_mode


def test_audio_stream_selection_prefers_index_one() -> None:
    item = {
        "Container": "mkv",
        "MediaStreams": [
            {"Type": "Audio", "Codec": "ac3", "Channels": 6, "Index": 0},
            {"Type": "Audio", "Codec": "aac", "Channels": 2, "Index": 1},
        ],
    }

    assert ChromecastPlaybackStrategy.analyze_media(item) == {
        "container": "mkv",
        "video_codec": "unknown",
        "video_height": 0,
        "bit_depth": 8,
        "audio_codec": "aac",
        "audio_channels": 2,
    }


def test_audio_stream_falls_back_to_first_audio_when_index_one_is_missing() -> None:
    item = {
        "Container": "mp3",
        "MediaStreams": [
            {"Type": "Audio", "Codec": "mp3", "Channels": 2, "Index": 0},
        ],
    }

    assert ChromecastPlaybackStrategy.analyze_media(item)["audio_codec"] == "mp3"


@pytest.mark.parametrize(
    ("item", "device_model", "item_type", "start_position_ticks"),
    [
        (_video_item(bit_depth=10), "Chromecast Ultra", "Episode", 0),
        (
            _audio_item(container="mp3", audio_codec="mp3"),
            "Chromecast Ultra",
            "Audio",
            67_890_123,
        ),
    ],
)
def test_playback_info_appends_start_position_ticks(
    item: dict[str, Any],
    device_model: str,
    item_type: str,
    start_position_ticks: int,
) -> None:
    """Resume position is threaded to transcode and audio stream URLs (not direct-play video)."""
    media_info = ChromecastPlaybackStrategy.analyze_media(item)
    result = ChromecastPlaybackStrategy.get_playback_info(
        "http://jellyfin:8096",
        "secret-token",
        "item-123",
        media_info,
        device_model,
        item_type=item_type,
        start_position_ticks=start_position_ticks,
    )

    assert f"StartPositionTicks={start_position_ticks}" in result["media_url"]
    assert result["media_url"].count("StartPositionTicks") == 1


def test_direct_play_video_url_has_no_start_position_ticks() -> None:
    """D2: StartPositionTicks is removed from the direct-play Static=true video URL.

    The Cast receiver ignores this query param; the resume offset travels
    as extra.current_time in the play_media payload instead.
    """
    media_info = ChromecastPlaybackStrategy.analyze_media(_video_item())
    result = ChromecastPlaybackStrategy.get_playback_info(
        "http://jellyfin:8096",
        "secret-token",
        "item-123",
        media_info,
        "Chromecast Ultra",
        item_type="Movie",
        start_position_ticks=12_345_678,
    )

    assert result["content_type"] == "video/mp4"
    assert "StartPositionTicks" not in result["media_url"]
    assert "/Videos/item-123/stream?Static=true" in result["media_url"]


def test_playback_info_omits_start_position_ticks_when_not_passed() -> None:
    media_info = ChromecastPlaybackStrategy.analyze_media(_video_item())
    result = ChromecastPlaybackStrategy.get_playback_info(
        "http://jellyfin:8096",
        "secret-token",
        "item-123",
        media_info,
        "Chromecast Ultra",
        item_type="Movie",
    )

    assert "StartPositionTicks" not in result["media_url"]
