"""Tests for native Chromecast playback preparation and HA payloads."""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from tests.homeassistant.ha_stubs import install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist.playback import (
    NoNextUpEpisodeError,
    PreparedPlaybackItem,
    async_play_on_chromecast,
    async_prepare_playback_item,
    build_play_media_data,
    playback_mode,
)
from custom_components.jellyfin_assist.playback_strategy import (
    ChromecastPlaybackStrategy,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class FakePlaybackClient:
    server_url = "http://jellyfin.local:8096"
    api_key = "secret-token"

    def __init__(
        self,
        item: dict[str, Any],
        next_up: dict[str, Any] | None = None,
    ) -> None:
        self.item = item
        self.next_up = next_up
        self.calls: list[tuple[str, str, str]] = []

    async def async_get_item(
        self,
        user_id: str,
        item_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("get_item", user_id, item_id))
        return dict(self.item)

    async def async_get_next_up_episode(
        self,
        user_id: str,
        series_id: str,
    ) -> dict[str, Any] | None:
        self.calls.append(("next_up", user_id, series_id))
        return dict(self.next_up) if self.next_up is not None else None

    def get_image_url(
        self,
        item_id: str,
        image_type: str = "Primary",
    ) -> str:
        return (
            f"{self.server_url}/Items/{item_id}/Images/{image_type}"
            f"?maxHeight=300&quality=90&api_key={self.api_key}"
        )


class FakePlaybackStates:
    def __init__(self, state: Any) -> None:
        self.state = state

    def get(self, entity_id: str) -> Any:
        return self.state


class FakePlaybackServices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any], bool]] = []

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        blocking: bool,
    ) -> None:
        self.calls.append(
            (
                domain,
                service,
                dict(data),
                blocking,
            )
        )


class FakePlaybackHass:
    def __init__(self, state: Any) -> None:
        self.states = FakePlaybackStates(state)
        self.services = FakePlaybackServices()
        self.tracked_state_changes: list[tuple[tuple[str, ...], Any]] = []

    async def async_add_executor_job(
        self,
        func: Any,
        *args: Any,
    ) -> Any:
        return func(*args)


def runtime_for(client: FakePlaybackClient) -> Any:
    return SimpleNamespace(
        client=client,
        user_id="USER-1",
        playback_targets=("media_player.example",),
        playback_sessions={},
        _config_entry=None,
    )


def test_prepare_movie_uses_native_item_without_next_up() -> None:
    client = FakePlaybackClient(
        {
            "Id": "movie-1",
            "Name": "Movie",
            "Type": "Movie",
        }
    )

    prepared = run(
        async_prepare_playback_item(
            runtime_for(client),
            "movie-1",
        )
    )

    assert prepared.item_id == "movie-1"
    assert prepared.resolved_from_type is None
    assert client.calls == [
        ("get_item", "USER-1", "movie-1"),
    ]


def test_prepare_series_resolves_native_next_up_episode() -> None:
    client = FakePlaybackClient(
        {
            "Id": "series-1",
            "Name": "Series",
            "Type": "Series",
        },
        {
            "Id": "episode-7",
            "Name": "Episode Seven",
            "Type": "Episode",
            "SeriesName": "Series",
        },
    )

    prepared = run(
        async_prepare_playback_item(
            runtime_for(client),
            "series-1",
        )
    )

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
        {
            "Id": "episode-8",
            "Name": "Episode Eight",
            "Type": "Episode",
        },
    )

    prepared = run(
        async_prepare_playback_item(
            runtime_for(client),
            "season-2",
        )
    )

    assert prepared.item_id == "episode-8"
    assert prepared.resolved_from_type == "Season"
    assert client.calls[-1] == (
        "next_up",
        "USER-1",
        "series-1",
    )


def test_prepare_series_with_no_next_up_surfaces_clear_failure() -> None:
    client = FakePlaybackClient(
        {
            "Id": "series-1",
            "Name": "Series",
            "Type": "Series",
        },
        None,
    )

    with pytest.raises(
        NoNextUpEpisodeError,
        match="No Next Up episode",
    ):
        run(
            async_prepare_playback_item(
                runtime_for(client),
                "series-1",
            )
        )


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
                {
                    "Type": "Video",
                    "Codec": "h264",
                    "Height": 1080,
                    "BitDepth": 8,
                },
                {
                    "Type": "Audio",
                    "Index": 1,
                    "Codec": "aac",
                    "Channels": 2,
                },
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
                "url": (
                    "http://jellyfin.local:8096/Items/"
                    "episode-1/Images/Primary"
                    "?maxHeight=300&quality=90&api_key=secret-token"
                )
            }
        ],
        "metadataType": 1,
        "seriesTitle": "Example Series",
        "season": 2,
        "episode": 3,
    }
    assert playback_mode(playback_info) == "direct_play"


def test_play_media_extra_asserts_exact_resume_dict() -> None:
    """D1/T2: a resume tick yields the exact extra dict with current_time (s)
    and stream_type BUFFERED for direct-play video.

    10:26 == 626 s == 6_260_000_000 ticks -> extra.current_time == 626.0.
    """
    client = FakePlaybackClient({})
    runtime = runtime_for(client)

    ticks = 6_260_000_000  # 10:26
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
            "UserData": {"PlaybackPositionTicks": ticks},
            "MediaStreams": [
                {"Type": "Video", "Codec": "h264", "Height": 1080, "BitDepth": 8},
                {"Type": "Audio", "Index": 1, "Codec": "aac", "Channels": 2},
            ],
        },
    )

    data, _playback_info = build_play_media_data(
        runtime,
        "media_player.example_chromecast",
        prepared,
        "Chromecast Ultra",
    )

    thumb_url = (
        "http://jellyfin.local:8096/Items/episode-1/Images/Primary"
        "?maxHeight=300&quality=90&api_key=secret-token"
    )
    assert data["extra"] == {
        "title": "Pilot",
        "thumb": thumb_url,
        "autoplay": True,
        "metadata": {
            "title": "Pilot",
            "images": [{"url": thumb_url}],
            "metadataType": 1,
            "seriesTitle": "Example Series",
            "season": 2,
            "episode": 3,
        },
        "current_time": 626.0,
        "stream_type": "BUFFERED",
    }


def test_play_media_extra_omits_current_time_on_fresh_playback() -> None:
    """D1/T2: no resume tick -> exact extra dict has no current_time, but
    still carries stream_type BUFFERED for direct-play video."""
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

    data, _playback_info = build_play_media_data(
        runtime,
        "media_player.example_chromecast",
        prepared,
        "Chromecast Ultra",
    )

    thumb_url = (
        "http://jellyfin.local:8096/Items/episode-1/Images/Primary"
        "?maxHeight=300&quality=90&api_key=secret-token"
    )
    extra = data["extra"]
    assert "current_time" not in extra
    assert extra == {
        "title": "Pilot",
        "thumb": thumb_url,
        "autoplay": True,
        "metadata": {
            "title": "Pilot",
            "images": [{"url": thumb_url}],
            "metadataType": 1,
            "seriesTitle": "Example Series",
            "season": 2,
            "episode": 3,
        },
        "stream_type": "BUFFERED",
    }


def test_successful_playback_creates_fresh_tracking_session(
    monkeypatch: Any,
) -> None:
    """Successful playback records the concrete Jellyfin item and runtime."""

    client = FakePlaybackClient({})
    runtime = runtime_for(client)

    runtime.playback_sessions["media_player.example"] = {
        "item_id": "old-item",
        "requested_item_id": "old-item",
        "duration_seconds": 999.0,
        "accumulated_playing_seconds": 500.0,
        "playing_started_at": None,
    }

    prepared = PreparedPlaybackItem(
        requested_item_id="series-1",
        item_id="episode-7",
        item={
            "Id": "episode-7",
            "Name": "Episode Seven",
            "Type": "Episode",
            "RunTimeTicks": 1_850_000_000,
        },
        resolved_from_type="Series",
    )

    async def prepare(
        runtime_arg: Any,
        item_id: str,
    ) -> PreparedPlaybackItem:
        assert runtime_arg is runtime
        assert item_id == "series-1"
        return prepared

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback.async_prepare_playback_item",
        prepare,
    )

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback."
        "ChromecastPlaybackStrategy.discover_chromecast_model",
        lambda hass, target: (
            "Home Assistant Voice",
            False,
        ),
    )

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback.build_play_media_data",
        lambda runtime_arg, target, prepared_arg, model, **_kwargs: (
            {
                "entity_id": target,
                "media_content_id": (
                    "http://jellyfin.local:8096/"
                    "Audio/episode-7/stream"
                ),
                "media_content_type": "audio/mpeg",
            },
            {
                "media_url": (
                    "http://jellyfin.local:8096/"
                    "Audio/episode-7/stream"
                ),
                "content_type": "audio/mpeg",
            },
        ),
    )

    hass = FakePlaybackHass(
        SimpleNamespace(
            entity_id="media_player.example",
            state="playing",
            attributes={},
        )
    )

    result = run(
        async_play_on_chromecast(
            hass,
            runtime,
            target_entity_id="media_player.example",
            item_id="series-1",
        )
    )

    assert hass.services.calls == [
        (
            "media_player",
            "play_media",
            {
                "entity_id": "media_player.example",
                "media_content_id": (
                    "http://jellyfin.local:8096/"
                    "Audio/episode-7/stream"
                ),
                "media_content_type": "audio/mpeg",
            },
            True,
        )
    ]

    session = runtime.playback_sessions["media_player.example"]

    assert session["item_id"] == "episode-7"
    assert session["requested_item_id"] == "series-1"
    assert session["duration_seconds"] == 185.0
    assert session["accumulated_playing_seconds"] == 0.0
    assert isinstance(session["playing_started_at"], datetime)
    assert session["playing_started_at"].tzinfo is not None

    assert result["success"] is True
    assert result["status"] == "playing"
    assert result["requested_item_id"] == "series-1"
    assert result["item_id"] == "episode-7"
    assert result["resolved_from_type"] == "Series"


def test_resume_session_initializes_accumulated_with_offset(
    monkeypatch: Any,
) -> None:
    """UserData resume ticks reach the session without an explicit override."""

    client = FakePlaybackClient(
        {
            "Id": "episode-7",
            "Name": "Episode Seven",
            "Type": "Episode",
            "RunTimeTicks": 1_850_000_000,
            "UserData": {
                "PlaybackPositionTicks": 3_600_000_000,  # 360s offset
            },
        }
    )
    runtime = runtime_for(client)

    prepared = PreparedPlaybackItem(
        requested_item_id="episode-7",
        item_id="episode-7",
        item={
            "Id": "episode-7",
            "Name": "Episode Seven",
            "Type": "Episode",
            "RunTimeTicks": 1_850_000_000,
            "UserData": {
                "PlaybackPositionTicks": 3_600_000_000,
            },
        },
        resolved_from_type="Episode",
    )

    async def prepare(
        runtime_arg: Any,
        item_id: str,
    ) -> PreparedPlaybackItem:
        assert runtime_arg is runtime
        assert item_id == "episode-7"
        return prepared

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback.async_prepare_playback_item",
        prepare,
    )

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback."
        "ChromecastPlaybackStrategy.discover_chromecast_model",
        lambda hass, target: (
            "Home Assistant Voice",
            False,
        ),
    )

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback.build_play_media_data",
        lambda runtime_arg, target, prepared_arg, model, **_kwargs: (
            {
                "entity_id": target,
                "media_content_id": (
                    "http://jellyfin.local:8096/"
                    "Audio/episode-7/stream"
                ),
                "media_content_type": "audio/mpeg",
            },
            {
                "media_url": (
                    "http://jellyfin.local:8096/"
                    "Audio/episode-7/stream"
                ),
                "content_type": "audio/mpeg",
            },
        ),
    )

    hass = FakePlaybackHass(
        SimpleNamespace(
            entity_id="media_player.example",
            state="playing",
            attributes={},
        )
    )

    result = run(
        async_play_on_chromecast(
            hass,
            runtime,
            target_entity_id="media_player.example",
            item_id="episode-7",
        )
    )

    session = runtime.playback_sessions["media_player.example"]

    assert session["start_position_ticks"] == 3_600_000_000
    # 3_600_000_000 ticks / 10_000_000 ticks/sec = 360.0 seconds
    assert session["accumulated_playing_seconds"] == 360.0
    assert result["success"] is True
    assert result["status"] == "playing"
    assert result["start_position_ticks"] == 3_600_000_000


def test_fresh_session_starts_accumulated_at_zero(
    monkeypatch: Any,
) -> None:
    """D2: without a resume offset, accumulated_playing_seconds is 0.0."""
    client = FakePlaybackClient(
        {
            "Id": "episode-7",
            "Name": "Episode Seven",
            "Type": "Episode",
            "RunTimeTicks": 1_850_000_000,
        }
    )
    runtime = runtime_for(client)

    prepared = PreparedPlaybackItem(
        requested_item_id="episode-7",
        item_id="episode-7",
        item={
            "Id": "episode-7",
            "Name": "Episode Seven",
            "Type": "Episode",
            "RunTimeTicks": 1_850_000_000,
        },
        resolved_from_type="Episode",
    )

    async def prepare(
        runtime_arg: Any,
        item_id: str,
    ) -> PreparedPlaybackItem:
        assert runtime_arg is runtime
        assert item_id == "episode-7"
        return prepared

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback.async_prepare_playback_item",
        prepare,
    )

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback."
        "ChromecastPlaybackStrategy.discover_chromecast_model",
        lambda hass, target: (
            "Home Assistant Voice",
            False,
        ),
    )

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback.build_play_media_data",
        lambda runtime_arg, target, prepared_arg, model, **_kwargs: (
            {
                "entity_id": target,
                "media_content_id": (
                    "http://jellyfin.local:8096/"
                    "Audio/episode-7/stream"
                ),
                "media_content_type": "audio/mpeg",
            },
            {
                "media_url": (
                    "http://jellyfin.local:8096/"
                    "Audio/episode-7/stream"
                ),
                "content_type": "audio/mpeg",
            },
        ),
    )

    hass = FakePlaybackHass(
        SimpleNamespace(
            entity_id="media_player.example",
            state="playing",
            attributes={},
        )
    )

    run(
        async_play_on_chromecast(
            hass,
            runtime,
            target_entity_id="media_player.example",
            item_id="episode-7",
        )
    )

    session = runtime.playback_sessions["media_player.example"]

    assert session["start_position_ticks"] is None
    assert session["accumulated_playing_seconds"] == 0.0


def _install_pychromecast_spy(monkeypatch: Any) -> list[dict[str, Any]]:
    """Install a fake pychromecast module and return the spy call log."""

    calls: list[dict[str, Any]] = []

    def get_listed_chromecasts(
        friendly_names: list[str], *, discovery_timeout: float
    ) -> tuple[list[Any], Any]:
        calls.append(
            {"friendly_names": list(friendly_names), "discovery_timeout": discovery_timeout}
        )
        device = SimpleNamespace(model_name="Chromecast Ultra")
        return [device], None

    pychromecast = types.ModuleType("pychromecast")
    pychromecast.get_listed_chromecasts = get_listed_chromecasts
    monkeypatch.setitem(sys.modules, "pychromecast", pychromecast)
    return calls


def _hass_with_registry(platform: str | None, entity_id: str) -> Any:
    """Build a FakeHass whose entity registry reports the given platform."""

    entry = SimpleNamespace(entity_id=entity_id, platform=platform)
    registry = SimpleNamespace(async_get=lambda eid: entry)
    fake_hass = types.SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: SimpleNamespace(
            attributes={"friendly_name": "Example Chromecast"}, state="idle",
        )),
        entity_registry=registry,
    )
    return fake_hass


def test_non_chromecast_target_skips_discovery_without_pychromecast(
    monkeypatch: Any,
) -> None:
    """A non-chromecast registry entry (or missing entry) skips discovery entirely:
    the real discover_chromecast_model returns ("Unknown", False) and pychromecast
    is never imported/called."""

    for platform in (None, "cast", "media_player"):
        calls = _install_pychromecast_spy(monkeypatch)
        entity_id = "media_player.voice"

        hass = _hass_with_registry(platform, entity_id)

        result = ChromecastPlaybackStrategy.discover_chromecast_model(hass, entity_id)

        assert result == ("Unknown", False)
        assert calls == [], (
            f"pychromecast was called for non-chromecast platform {platform!r}: {calls}"
        )


def test_missing_registry_entry_skips_discovery_without_pychromecast(
    monkeypatch: Any,
) -> None:
    """No registry entry at all -> skip discovery, pychromecast never called."""

    calls = _install_pychromecast_spy(monkeypatch)
    entity_id = "media_player.example"

    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: None),
        entity_registry=SimpleNamespace(async_get=lambda hass_: None),
    )

    result = ChromecastPlaybackStrategy.discover_chromecast_model(hass, entity_id)

    assert result == ("Unknown", False)
    assert calls == []


def test_chromecast_target_reaches_pychromecast_discovery(
    monkeypatch: Any,
) -> None:
    """A registry entry with platform == "chromecast" proceeds to the blocking
    pychromecast discovery (D3: real-cast path unchanged)."""

    calls = _install_pychromecast_spy(monkeypatch)
    entity_id = "media_player.example_chromecast"

    hass = _hass_with_registry("chromecast", entity_id)

    result = ChromecastPlaybackStrategy.discover_chromecast_model(hass, entity_id)

    # Discovery reached: the fake pychromecast was invoked and returned the
    # advertised model.
    assert len(calls) == 1
    assert calls[0]["friendly_names"] == ["Example Chromecast"]
    assert calls[0]["discovery_timeout"] == 5.0
    assert result == ("Chromecast Ultra", False)


def _run_play_for_session(
    monkeypatch: Any,
    item: dict[str, Any],
    playback_info: dict[str, str],
    monkey_patched_bpd: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Shared helper: run async_play_on_chromecast with a stubbed
    build_play_media_data and return (session, result)."""

    client = FakePlaybackClient(dict(item))
    runtime = runtime_for(client)

    prepared = PreparedPlaybackItem(
        requested_item_id=item.get("Id", "episode-7"),
        item_id=item.get("Id", "episode-7"),
        item=dict(item),
    )

    async def prepare(runtime_arg: Any, item_id: str) -> PreparedPlaybackItem:
        assert runtime_arg is runtime
        return prepared

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback.async_prepare_playback_item",
        prepare,
    )
    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback."
        "ChromecastPlaybackStrategy.discover_chromecast_model",
        lambda hass, target: ("Home Assistant Voice", False),
    )
    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback.build_play_media_data",
        monkey_patched_bpd or (
            lambda runtime_arg, target, prepared_arg, model, **_kwargs: (
                {
                    "entity_id": target,
                    "media_content_id": playback_info["media_url"],
                    "media_content_type": playback_info["content_type"],
                },
                dict(playback_info),
            )
        ),
    )

    hass = FakePlaybackHass(
        SimpleNamespace(
            entity_id="media_player.example",
            state="playing",
            attributes={},
        )
    )

    result = run(
        async_play_on_chromecast(
            hass,
            runtime,
            target_entity_id="media_player.example",
            item_id=prepared.item_id,
        )
    )
    session = runtime.playback_sessions["media_player.example"]
    return session, result


def test_transcode_video_does_not_seed_accumulated_with_resume_offset(
    monkeypatch: Any,
) -> None:
    """T3: transcode video (m3u8) — the Cast receiver does NOT honour
    extra.current_time on a LIVE stream, so the accumulated offset must
    be 0.0 even though a resume tick exists. No false progress."""

    ticks = 3_600_000_000  # 360s == 6:00
    item = {
        "Id": "episode-7",
        "Name": "Episode Seven",
        "Type": "Episode",
        "RunTimeTicks": 1_850_000_000,
        "UserData": {"PlaybackPositionTicks": ticks},
        "Container": "mkv",
        "MediaStreams": [
            {"Type": "Video", "Codec": "hevc", "Height": 4320, "BitDepth": 10},
            {"Type": "Audio", "Index": 1, "Codec": "ac3", "Channels": 6},
        ],
    }

    transcode_info = {
        "media_url": (
            "http://jellyfin.local:8096/Videos/episode-7/master.m3u8"
            "?api_key=secret-tokenStartPositionTicks=3600000000"
            "&MediaSourceId=episode-7"
        ),
        "content_type": "application/x-mpegURL",
    }

    session, result = _run_play_for_session(
        monkeypatch, item, transcode_info, None
    )

    # start_position_ticks is stored (the offset the URL carries)
    assert session["start_position_ticks"] == ticks
    # T3: accumulated must be 0.0 — the receiver will not seek
    assert session["accumulated_playing_seconds"] == 0.0
    assert result["success"] is True


def test_direct_play_video_seeds_accumulated_with_resume_offset(
    monkeypatch: Any,
) -> None:
    """T3: direct-play video — extra.current_time + stream_type=BUFFERED
    ARE sent, so the receiver will honour the seek. The accumulated
    offset is seeded correctly from start_position_ticks / 1e7."""

    ticks = 6_260_000_000  # 626s == 10:26
    item = {
        "Id": "episode-7",
        "Name": "Episode Seven",
        "Type": "Episode",
        "RunTimeTicks": 1_850_000_000,
        "UserData": {"PlaybackPositionTicks": ticks},
        "Container": "mkv",
        "MediaStreams": [
            {"Type": "Video", "Codec": "h264", "Height": 1080, "BitDepth": 8},
            {"Type": "Audio", "Index": 1, "Codec": "aac", "Channels": 2},
        ],
    }

    direct_play_info = {
        "media_url": (
            "http://jellyfin.local:8096/Videos/episode-7/stream"
            "?Static=true&api_key=secret-token&VideoCodec=h264&AudioCodec=aac"
        ),
        "content_type": "video/mp4",
    }

    session, result = _run_play_for_session(
        monkeypatch, item, direct_play_info, None
    )

    assert session["start_position_ticks"] == ticks
    assert session["accumulated_playing_seconds"] == 626.0
    assert result["success"] is True


def test_audio_play_seeds_accumulated_with_resume_offset(
    monkeypatch: Any,
) -> None:
    """T3: audio — the URL StartPositionTicks param IS honoured by the
    Cast receiver (T1 evidence), so the accumulated offset IS seeded."""

    ticks = 1_200_000_000  # 120s == 2:00
    item = {
        "Id": "episode-7",
        "Name": "Episode Seven",
        "Type": "Episode",
        "RunTimeTicks": 1_850_000_000,
        "UserData": {"PlaybackPositionTicks": ticks},
        "Container": "mp3",
    }

    audio_info = {
        "media_url": (
            "http://jellyfin.local:8096/Audio/episode-7/stream"
            "?static=true&api_key=secret-token"
            "&StartPositionTicks=1200000000"
        ),
        "content_type": "audio/mpeg",
    }

    session, result = _run_play_for_session(
        monkeypatch, item, audio_info, None
    )

    assert session["start_position_ticks"] == ticks
    assert session["accumulated_playing_seconds"] == 120.0
    assert result["success"] is True
