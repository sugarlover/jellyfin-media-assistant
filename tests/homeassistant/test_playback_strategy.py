"""Parity tests for the native Chromecast playback strategy."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from custom_components.jellyfin_assist.playback_strategy import (
    ChromecastPlaybackStrategy,
)

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
LEGACY_STRATEGY_PATH: Final = (
    REPOSITORY_ROOT
    / "reference"
    / "current-working"
    / "jellyha"
    / "media_strategy.py"
)


def _load_legacy_strategy() -> type[Any]:
    spec = importlib.util.spec_from_file_location(
        "jellyha_reference_media_strategy",
        LEGACY_STRATEGY_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert isinstance(module, ModuleType)
    spec.loader.exec_module(module)
    return module.MediaStrategy


LEGACY_STRATEGY = _load_legacy_strategy()


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
    ("item", "device_model", "item_type"),
    [
        (_video_item(), "Chromecast Ultra", "Movie"),
        (_video_item(video_codec="hevc"), "Chromecast Ultra", "Movie"),
        (_video_item(video_height=720), "Chromecast", "Movie"),
        (_video_item(video_height=1080), "Chromecast", "Movie"),
        (_video_item(bit_depth=10), "Chromecast Ultra", "Episode"),
        (_audio_item(container="flac", audio_codec="flac"), "Chromecast Ultra", "Audio"),
        (_audio_item(container="flac", audio_codec="flac"), "Chromecast", "Audio"),
        (_audio_item(container="mp3", audio_codec="mp3"), "Chromecast", "Audio"),
        (_audio_item(container="m4a", audio_codec="aac"), "Chromecast Ultra", "Audio"),
    ],
)
def test_native_strategy_matches_frozen_jellyha_reference(
    item: dict[str, Any],
    device_model: str,
    item_type: str,
) -> None:
    native_media = ChromecastPlaybackStrategy.analyze_media(item)
    legacy_media = LEGACY_STRATEGY.analyze_media(item)

    assert native_media == legacy_media

    native = ChromecastPlaybackStrategy.get_playback_info(
        "http://jellyfin:8096",
        "secret-token",
        "item-123",
        native_media,
        device_model,
        item_type=item_type,
    )
    legacy = LEGACY_STRATEGY.get_playback_info(
        "http://jellyfin:8096",
        "secret-token",
        "item-123",
        legacy_media,
        device_model,
        item_type=item_type,
    )

    assert native == legacy


def test_audio_stream_selection_matches_legacy_index_one_preference() -> None:
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
    assert ChromecastPlaybackStrategy.analyze_media(item) == LEGACY_STRATEGY.analyze_media(item)


def test_audio_stream_falls_back_to_first_audio_when_index_one_is_missing() -> None:
    item = {
        "Container": "mp3",
        "MediaStreams": [
            {"Type": "Audio", "Codec": "mp3", "Channels": 2, "Index": 0},
        ],
    }

    assert ChromecastPlaybackStrategy.analyze_media(item) == LEGACY_STRATEGY.analyze_media(item)
    assert ChromecastPlaybackStrategy.analyze_media(item)["audio_codec"] == "mp3"
