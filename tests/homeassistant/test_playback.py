"""Tests for native Chromecast playback preparation and HA payloads."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.jellyfin_assist.playback import (
    NoNextUpEpisodeError,
    PreparedPlaybackItem,
    async_prepare_playback_item,
    build_play_media_data,
    playback_mode,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class FakePlaybackClient:
    server_url = "http://jellyfin.local:8096"
    api_key = "secret-token"

    def __init__(self, item: dict[str, Any], next_up: dict[str, Any] | None = None) -> None:
        self.item = item
        self.next_up = next_up
        self.calls: list[tuple[str, str, str]] = []

    async def async_get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        self.calls.append(("get_item", user_id, item_id))
        return dict(self.item)

    async def async_get_next_up_episode(
        self,
        user_id: str,
        series_id: str,
    ) -> dict[str, Any] | None:
        self.calls.append(("next_up", user_id, series_id))
        return dict(self.next_up) if self.next_up is not None else None

    def get_image_url(self, item_id: str, image_type: str = "Primary") -> str:
        return (
            f"{self.server_url}/Items/{item_id}/Images/{image_type}"
            f"?maxHeight=300&quality=90&api_key={self.api_key}"
        )


def runtime_for(client: FakePlaybackClient) -> Any:
    return SimpleNamespace(client=client, user_id="USER-1")


def test_prepare_movie_uses_native_item_without_next_up() -> None:
    client = FakePlaybackClient({"Id": "movie-1", "Name": "Movie", "Type": "Movie"})

    prepared = run(async_prepare_playback_item(runtime_for(client), "movie-1"))

    assert prepared.item_id == "movie-1"
    assert prepared.resolved_from_type is None
    assert client.calls == [("get_item", "USER-1", "movie-1")]


def test_prepare_series_resolves_native_next_up_episode() -> None:
    client = FakePlaybackClient(
        {"Id": "series-1", "Name": "Series", "Type": "Series"},
        {
            "Id": "episode-7",
            "Name": "Episode Seven",
            "Type": "Episode",
            "SeriesName": "Series",
        },
    )

    prepared = run(async_prepare_playback_item(runtime_for(client), "series-1"))

    assert prepared.item_id == "episode-7"
    assert prepared.item_type == "Episode"
    assert prepared.resolved_from_type == "Series"
    assert client.calls == [
        ("get_item", "USER-1", "series-1"),
        ("next_up", "USER-1", "series-1"),
    ]


def test_prepare_season_uses_series_id_for_next_up() -> None:
    client = FakePlaybackClient(
        {
            "Id": "season-2",
            "Name": "Season 2",
            "Type": "Season",
            "SeriesId": "series-1",
        },
        {"Id": "episode-8", "Name": "Episode Eight", "Type": "Episode"},
    )

    prepared = run(async_prepare_playback_item(runtime_for(client), "season-2"))

    assert prepared.item_id == "episode-8"
    assert prepared.resolved_from_type == "Season"
    assert client.calls[-1] == ("next_up", "USER-1", "series-1")


def test_prepare_series_with_no_next_up_surfaces_clear_failure() -> None:
    client = FakePlaybackClient(
        {"Id": "series-1", "Name": "Series", "Type": "Series"},
        None,
    )

    with pytest.raises(NoNextUpEpisodeError, match="No Next Up episode"):
        run(async_prepare_playback_item(runtime_for(client), "series-1"))


def test_episode_play_media_payload_preserves_jellyha_metadata_contract() -> None:
    client = FakePlaybackClient({})
    runtime = runtime_for(client)
    prepared = PreparedPlaybackItem(
        requested_item_id="episode-1",
        item_id="episode-1",
        item={
            "Id": "episode-1",
            "Name": "Pilot",
            "Type": "Episode",
            "SeriesName": "Example Series",
            "ParentIndexNumber": 2,
            "IndexNumber": 3,
            "Container": "mkv",
            "MediaStreams": [
                {"Type": "Video", "Codec": "h264", "Height": 1080, "BitDepth": 8},
                {"Type": "Audio", "Index": 1, "Codec": "aac", "Channels": 2},
            ],
        },
    )

    data, playback_info = build_play_media_data(
        runtime,
        "media_player.example_chromecast",
        prepared,
        "Chromecast Ultra",
    )

    assert data["entity_id"] == "media_player.example_chromecast"
    assert data["media_content_type"] == "video/mp4"
    assert data["media_content_id"].startswith(
        "http://jellyfin.local:8096/Videos/episode-1/stream?"
    )
    assert data["extra"]["title"] == "Pilot"
    assert data["extra"]["autoplay"] is True
    assert data["extra"]["metadata"] == {
        "title": "Pilot",
        "images": [
            {
                "url": "http://jellyfin.local:8096/Items/episode-1/Images/Primary"
                "?maxHeight=300&quality=90&api_key=secret-token"
            }
        ],
        "metadataType": 1,
        "seriesTitle": "Example Series",
        "season": 2,
        "episode": 3,
    }
    assert playback_mode(playback_info) == "direct_play"
