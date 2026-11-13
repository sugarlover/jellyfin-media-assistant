"""Playback-position regressions through the registered callbacks and API."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.homeassistant.ha_stubs import FakeHass, FakeState, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist import advancement, media_actions, queue_control, services
from custom_components.jellyfin_assist.api import JellyfinApiClient, JellyfinConnectionError
from custom_components.jellyfin_assist.configuration import JellyfinBehaviorSettings
from custom_components.jellyfin_assist.playback import async_play_on_chromecast
from custom_components.jellyfin_assist.playback_strategy import ChromecastPlaybackStrategy
from tests.homeassistant.test_advancement import (
    RecordingPlayingClient,
    SpyBackgroundEntry,
    _session,
    runtime_with_client,
)
from tests.homeassistant.test_api import FakeResponse
from tests.homeassistant.test_playback import FakePlaybackClient, FakePlaybackHass, runtime_for


PLAYER = "media_player.example"
ITEM = "1e0ed46d08153e62e1cea40c91b6ddb5"


def state(value: str, at: datetime, **attrs: Any) -> Any:
    return SimpleNamespace(entity_id=PLAYER, state=value, last_changed=at, attributes=attrs)


def event(old: Any, new: Any, player: str = PLAYER) -> Any:
    return SimpleNamespace(data={"entity_id": player, "old_state": old, "new_state": new})


async def drain(entry: SpyBackgroundEntry) -> None:
    while entry.background_tasks:
        _name, coro = entry.background_tasks.pop(0)
        await coro


class ProgressServer:
    """Exercise actual API request construction and readback, without a live write."""

    def __init__(self) -> None:
        self.saved_ticks = 0
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/Users/Me"):
            return FakeResponse(200, {"Id": "user-1"})
        assert url == f"http://jellyfin/Users/user-1/Items/{ITEM}"
        return FakeResponse(200, {"UserData": {"PlaybackPositionTicks": self.saved_ticks}})

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        assert url == f"http://jellyfin/Users/user-1/PlayingItems/{ITEM}/Progress"
        self.saved_ticks = int(kwargs["params"]["positionTicks"])
        return FakeResponse(204, None)


def test_six_minutes_through_registered_timer_and_api(tmp_path: Path, monkeypatch: Any) -> None:
    server = ProgressServer()
    client = JellyfinApiClient(server, "http://jellyfin", "server-key", user_id="user-1", user_token="user-token")
    rt = runtime_with_client(client)
    rt.user_id = "user-1"
    # Exercise the actual default-player option normalization.
    rt.playback_targets = JellyfinBehaviorSettings.from_mappings({"default_media_player": PLAYER}).effective_playback_targets
    hass = FakeHass(tmp_path, states=[FakeState(PLAYER, state="playing")])
    entry = SpyBackgroundEntry("entry", {})
    timers = []
    monkeypatch.setattr(advancement, "async_track_time_interval", lambda hass, *, action, interval: timers.append((action, interval)) or (lambda: None))
    advancement.async_setup_queue_advancement(hass, entry, rt)
    rt.playback_sessions[PLAYER] = {
        **_session(duration_seconds=2700, accumulated_playing_seconds=0,
                   playing_started_at=datetime.now(timezone.utc) - timedelta(seconds=360)),
        "item_id": ITEM,
    }
    assert hass.tracked_state_changes[0][0] == (PLAYER,)
    assert timers[0][1] == timedelta(seconds=60)
    timers[0][0](datetime.now(timezone.utc))
    asyncio.run(drain(entry))
    assert server.saved_ticks == 3_600_000_000
    assert [method for method, _url, _kwargs in server.calls] == ["GET", "POST", "GET"]
    assert all(kwargs["headers"]["X-Emby-Token"] == "user-token" for _method, _url, kwargs in server.calls)


@pytest.mark.parametrize("terminal", ["paused", "buffering", "idle", "off", "unavailable"])
def test_transition_saves_final_six_minute_position(tmp_path: Path, terminal: str) -> None:
    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.queue_client = None
    started = datetime(2026, 11, 12, 23, 50, 41, tzinfo=timezone.utc)
    rt.playback_sessions[PLAYER] = _session(duration_seconds=2700, accumulated_playing_seconds=0, playing_started_at=started)
    entry = SpyBackgroundEntry("entry", {})
    hass = FakeHass(tmp_path)
    advancement.async_setup_queue_advancement(hass, entry, rt)
    handler = hass.tracked_state_changes[0][1]
    handler(event(state("playing", started), state(terminal, started + timedelta(seconds=360))))
    asyncio.run(drain(entry))
    assert client.calls[0]["position_ticks"] == 3_600_000_000
    assert client.calls[0]["is_paused"] is True
    assert (PLAYER in rt.playback_sessions) == (terminal in {"paused", "buffering"})


def test_pause_resume_then_idle_excludes_paused_time(tmp_path: Path) -> None:
    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.queue_client = None
    started = datetime(2026, 11, 12, 23, 0, tzinfo=timezone.utc)
    rt.playback_sessions[PLAYER] = _session(duration_seconds=2700, accumulated_playing_seconds=360, playing_started_at=started)
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})
    advancement.async_setup_queue_advancement(hass, entry, rt)
    handler = hass.tracked_state_changes[0][1]
    playing = state("playing", started)
    paused = state("paused", started + timedelta(seconds=60))
    resumed = state("playing", started + timedelta(seconds=660))
    idle = state("idle", started + timedelta(seconds=720))
    handler(event(playing, paused))
    # Intentionally delay the pause task until after resume: it must use its snapshot.
    handler(event(paused, resumed))
    handler(event(resumed, idle))
    asyncio.run(drain(entry))
    assert [call["position_ticks"] for call in client.calls] == [4_200_000_000, 4_800_000_000]
    assert PLAYER not in rt.playback_sessions


def test_attribute_only_update_does_not_backdate_new_session(tmp_path: Path) -> None:
    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    old_started = datetime(2026, 11, 12, 22, 0, tzinfo=timezone.utc)
    new_started = old_started + timedelta(hours=1)
    rt.playback_sessions[PLAYER] = _session(duration_seconds=2700, accumulated_playing_seconds=360, playing_started_at=new_started)
    advancement._update_playback_session(rt, player=PLAYER, old_state=state("playing", old_started), new_state=state("playing", old_started, media_title="new title"))
    assert rt.playback_sessions[PLAYER]["playing_started_at"] == new_started
    advancement._update_playback_session(rt, player=PLAYER, old_state=state("playing", old_started), new_state=state("paused", new_started + timedelta(seconds=60)))
    assert rt.playback_sessions[PLAYER]["accumulated_playing_seconds"] == 420


@pytest.mark.parametrize("override, expected", [(None, 3_600_000_000), (0, 0), (1_200_000_000, 1_200_000_000)])
def test_url_and_session_share_effective_resume_offset(monkeypatch: Any, override: int | None, expected: int) -> None:
    client = FakePlaybackClient({
        "Id": ITEM, "Type": "Episode", "Name": "Episode", "RunTimeTicks": 27_000_000_000,
        "UserData": {"PlaybackPositionTicks": 3_600_000_000},
    })
    rt = runtime_for(client)
    hass = FakePlaybackHass(None)
    monkeypatch.setattr(ChromecastPlaybackStrategy, "discover_chromecast_model", lambda hass, player: ("Unknown", False))
    result = asyncio.run(async_play_on_chromecast(hass, rt, target_entity_id=PLAYER, item_id=ITEM, start_position_ticks=override))
    # D1: the resume offset travels as extra.current_time (seconds) on the
    # play_media payload.
    extra = hass.services.calls[0][2]["extra"]
    assert extra["current_time"] == expected / 10_000_000
    assert result["start_position_ticks"] == expected
    # This test item has no MediaStreams -> unknown codec -> transcode (m3u8).
    # Under T3's seek guard, the Cast receiver does NOT honour the seek on a
    # transcode/LIVE stream, so accumulated_playing_seconds is 0.0 even
    # though a resume offset exists. start_position_ticks and extra.current_time
    # still carry the effective offset (D3 consistency with the media URL).
    assert rt.playback_sessions[PLAYER]["accumulated_playing_seconds"] == 0.0


def test_playing_state_arrives_during_service_call(monkeypatch: Any) -> None:
    client = FakePlaybackClient({"Id": ITEM, "Type": "Episode", "RunTimeTicks": 27_000_000_000})
    rt = runtime_for(client)
    hass = FakePlaybackHass(None)
    monkeypatch.setattr(ChromecastPlaybackStrategy, "discover_chromecast_model", lambda hass, player: ("Unknown", False))
    observed = []
    async def play(*args: Any, **kwargs: Any) -> None:
        at = datetime.now(timezone.utc)
        observed.append(at)
        hass.states.state = state("playing", at)
    hass.services.async_call = play
    asyncio.run(async_play_on_chromecast(hass, rt, target_entity_id=PLAYER, item_id=ITEM))
    assert rt.playback_sessions[PLAYER]["playing_started_at"] == observed[0]


def test_delayed_first_playing_event_initializes_clock(tmp_path: Path) -> None:
    rt = runtime_with_client(RecordingPlayingClient())
    rt.playback_sessions[PLAYER] = _session(duration_seconds=2700, accumulated_playing_seconds=0)
    entry = SpyBackgroundEntry("entry", {})
    handler = advancement._build_queue_advancement_handler(FakeHass(tmp_path), entry, rt)
    at = datetime.now(timezone.utc)
    handler(event(None, state("playing", at)))
    assert rt.playback_sessions[PLAYER]["playing_started_at"] == at
    assert entry.background_tasks == []


@pytest.mark.parametrize("duration", [0, None, "unknown"])
def test_missing_duration_still_writes_tracked_position(tmp_path: Path, duration: Any, caplog: Any) -> None:
    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.playback_sessions[PLAYER] = _session(duration_seconds=duration, accumulated_playing_seconds=360)
    with caplog.at_level(logging.DEBUG, logger=advancement.__name__):
        asyncio.run(advancement._async_write_sync_position(FakeHass(tmp_path), rt, PLAYER, True))
    assert client.calls[0]["position_ticks"] == 3_600_000_000
    assert "duration unknown" in caplog.text
    assert "Progress saved" in caplog.text


@pytest.mark.parametrize("targets", [(), (PLAYER,)])
def test_unlisted_playback_has_no_side_effects(targets: tuple[str, ...]) -> None:
    client = FakePlaybackClient({"Id": ITEM, "Type": "Episode"})
    rt = runtime_for(client)
    rt.playback_targets = targets
    hass = FakePlaybackHass(None)
    with pytest.raises(ValueError, match="not configured"):
        asyncio.run(async_play_on_chromecast(hass, rt, target_entity_id="media_player.unlisted", item_id=ITEM))
    assert client.calls == []
    assert hass.services.calls == []
    assert hass.tracked_state_changes == []
    assert rt.playback_sessions == {}


@pytest.mark.parametrize("call", [media_actions.async_play_item, media_actions.async_prepare_play_session, media_actions.async_queue_add_item])
def test_high_level_actions_reject_before_turn_on_or_queue_write(tmp_path: Path, call: Any) -> None:
    rt = runtime_with_client(RecordingPlayingClient())
    rt.queue_client = SimpleNamespace()  # Every attempted queue call would fail.
    hass = FakeHass(tmp_path)
    kwargs = {"media_player": "media_player.unlisted"}
    if call is not media_actions.async_prepare_play_session:
        kwargs["item"] = {"id": ITEM, "name": "Episode", "type": "Episode"}
    response = asyncio.run(call(hass, rt, **kwargs))
    assert response["status"] == "invalid_playback_target"
    assert "integration options" in response["message"]
    assert hass.services.calls == []


@pytest.mark.parametrize("call", [media_actions._queue_call, queue_control._queue_call, services._async_queue_call])
@pytest.mark.parametrize("operation", ["get", "add", "next", "clear", "settings", "shuffle"])
def test_all_queue_boundaries_reject_unlisted_players(call: Any, operation: str) -> None:
    rt = runtime_with_client(RecordingPlayingClient())
    rt.queue_client = SimpleNamespace()
    result = asyncio.run(call(rt, operation, player="media_player.unlisted"))
    assert result["status"] == 403
    assert result["content"]["status"] == "invalid_playback_target"


def test_empty_options_do_not_discover_arbitrary_players(tmp_path: Path) -> None:
    rt = runtime_with_client(RecordingPlayingClient())
    rt.playback_targets = ()
    hass = FakeHass(tmp_path, states=[FakeState(PLAYER, state="playing")])
    assert services._candidate_entity_ids(hass, rt) == ()
    entry = SpyBackgroundEntry("entry", {})
    advancement.async_setup_queue_advancement(hass, entry, rt)
    assert hass.tracked_state_changes == []
    assert entry.unload_callbacks == []


def test_tracking_rejects_unlisted_events_and_direct_writes(tmp_path: Path) -> None:
    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    rt.playback_sessions["media_player.unlisted"] = _session(duration_seconds=2700, accumulated_playing_seconds=360)
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})
    handler = advancement._build_queue_advancement_handler(hass, entry, rt)
    now = datetime.now(timezone.utc)
    handler(event(state("playing", now), state("paused", now), "media_player.unlisted"))
    asyncio.run(advancement._async_write_sync_position(hass, rt, "media_player.unlisted", True))
    assert entry.background_tasks == []
    assert client.calls == []


@pytest.mark.parametrize("queue_failure", [False, True])
def test_rejected_completion_saves_without_advancing(tmp_path: Path, queue_failure: bool) -> None:
    class Queue:
        next_calls = 0

        async def async_get(self, player: str) -> Any:
            from custom_components.jellyfin_assist.queue_store import QueueStoreError
            if queue_failure:
                raise QueueStoreError("offline")
            return {"status": 200, "content": {"success": True, "current": {"id": "abc123"}}}

        async def async_next(self, player: str) -> Any:
            self.next_calls += 1
            raise AssertionError("An incomplete episode must not advance")

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    queue = Queue()
    rt.queue_client = queue
    rt.playback_sessions[PLAYER] = _session(duration_seconds=2700, accumulated_playing_seconds=360)
    now = datetime.now(timezone.utc)
    asyncio.run(advancement._async_process_completion(FakeHass(tmp_path), rt, player=PLAYER, old_state=state("playing", now), new_state=state("idle", now)))
    assert client.calls[0]["position_ticks"] == 3_600_000_000
    assert queue.next_calls == 0
    assert PLAYER not in rt.playback_sessions


def test_stale_idle_callback_does_not_drop_replacement_session(tmp_path: Path) -> None:
    rt = runtime_with_client(RecordingPlayingClient())
    old_session = _session(duration_seconds=2700, accumulated_playing_seconds=360)
    rt.playback_sessions[PLAYER] = old_session
    hass = FakeHass(tmp_path)
    entry = SpyBackgroundEntry("entry", {})
    advancement.async_setup_queue_advancement(hass, entry, rt)
    now = datetime.now(timezone.utc)
    hass.tracked_state_changes[0][1](event(state("playing", now), state("idle", now)))
    replacement = _session(duration_seconds=2700, accumulated_playing_seconds=0)
    rt.playback_sessions[PLAYER] = replacement
    asyncio.run(drain(entry))
    assert rt.playback_sessions[PLAYER] is replacement
    assert rt.client.calls == []


def test_failure_is_logged_and_next_period_can_retry(tmp_path: Path, caplog: Any) -> None:
    class FailingClient(RecordingPlayingClient):
        async def async_post_playing_items(self, **kwargs: Any) -> None:
            raise JellyfinConnectionError("offline")

    rt = runtime_with_client(FailingClient())
    rt.playback_sessions[PLAYER] = _session(duration_seconds=2700, accumulated_playing_seconds=360)
    hass = FakeHass(tmp_path, states=[FakeState(PLAYER, state="playing")])
    with caplog.at_level(logging.DEBUG, logger=advancement.__name__):
        asyncio.run(advancement._async_periodic_write_sync_tasks(hass, rt))
    assert "Progress failed" in caplog.text
    assert PLAYER in rt.playback_sessions
    rt.client = RecordingPlayingClient()
    asyncio.run(advancement._async_periodic_write_sync_tasks(hass, rt))
    assert rt.client.calls[0]["position_ticks"] == 3_600_000_000


def test_inflight_periodic_write_finishes_before_final_stop(tmp_path: Path) -> None:
    async def exercise() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        class SlowClient(RecordingPlayingClient):
            async def async_post_playing_items(self, **kwargs: Any) -> None:
                if not entered.is_set():
                    entered.set()
                    await release.wait()
                await super().async_post_playing_items(**kwargs)

        client = SlowClient()
        rt = runtime_with_client(client)
        hass = FakeHass(tmp_path)
        rt.playback_sessions[PLAYER] = _session(duration_seconds=2700, accumulated_playing_seconds=300)
        timer = asyncio.create_task(advancement._async_write_sync_position(hass, rt, PLAYER, False))
        await entered.wait()
        final = _session(duration_seconds=2700, accumulated_playing_seconds=360)
        stopped = asyncio.create_task(advancement._async_write_sync_position(hass, rt, PLAYER, True, session=final))
        release.set()
        await asyncio.gather(timer, stopped)
        assert [c["position_ticks"] for c in client.calls] == [3_000_000_000, 3_600_000_000]

    asyncio.run(exercise())
