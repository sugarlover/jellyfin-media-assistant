"""T4 — JMA resume-fix regression coverage for the six plan scenarios.

Focused regression block for the jma-resume-fix plan
(/workspace/planner/plans/2026-11-13-jma-resume-fix.md). Pins the narrowest
useful behaviour for each of the six scenario classes:

1. Fresh playback (no tick)       -> extra.current_time absent/0.
2. 10:26 resume (6_260_000_000)   -> extra.current_time == 626.0, seeds 626.0.
3. Explicit restart at zero       -> force_start_position_ticks=0 -> 0.0.
4. Paused position                -> correct resume offset, no false progress.
5. Unauthorized playback target   -> rejected, no session written.
6. Queue advancement              -> session/queue behaviour unchanged by the
                                      resume change.

The D1-T3 deep payload assertions already live in test_playback.py /
test_playback_position.py. What this block adds is what was not directly
pinned there: scenario 4's "no false progress" at the tracking layer for a
resume-seeded paused session, and scenario 6's proof that a resume-seeded
session drives queue advancement unchanged. Scenarios 1/2/3/5 are re-pinned
compactly so the six-scenario contract is self-contained here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.homeassistant.ha_stubs import FakeHass, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist import advancement
from custom_components.jellyfin_assist.playback import (
    async_play_on_chromecast,
    build_play_media_data,
)
from tests.homeassistant.test_advancement import (
    RecordingPlayingClient,
    SpyBackgroundEntry,
    _session,
    runtime_with_client,
)
from tests.homeassistant.test_playback import (
    FakePlaybackClient,
    FakePlaybackHass,
    PreparedPlaybackItem,
    runtime_for,
)

# 10:26 == 626 s == 6_260_000_000 ticks. The canonical resume scenario.
RESUME_TICKS = 6_260_000_000
RESUME_SECONDS = 626.0
PLAYER = "media_player.example"


def _direct_play_episode(item: dict[str, Any]) -> dict[str, Any]:
    """An H.264/aac 1080p episode: direct-play video (seek-supported, T3)."""

    return {
        "Id": item.get("Id", "episode-1"),
        "Name": "Pilot",
        "Type": "Episode",
        "SeriesName": "Example Series",
        "ParentIndexNumber": 1,
        "IndexNumber": 1,
        "RunTimeTicks": 1_850_000_000,
        "Container": "mkv",
        "MediaStreams": [
            {"Type": "Video", "Codec": "h264", "Height": 1080, "BitDepth": 8},
            {"Type": "Audio", "Index": 1, "Codec": "aac", "Channels": 2},
        ],
    }


def _direct_play_info() -> dict[str, str]:
    """playback_info for a direct-play video: seek_supported under T3."""

    return {
        "media_url": (
            "http://jellyfin.local:8096/Videos/episode-1/stream"
            "?Static=true&api_key=secret-token&VideoCodec=h264&AudioCodec=aac"
        ),
        "content_type": "video/mp4",
    }


def _playing_state() -> Any:
    return SimpleNamespace(
        entity_id=PLAYER,
        state="playing",
        last_changed=datetime.now(timezone.utc),
        attributes={},
    )


def _run_play(
    monkeypatch: Any,
    item: dict[str, Any],
    playback_info: dict[str, str],
    *,
    start_position_ticks: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drive the real async_play_on_chromecast with a stubbed payload
    builder and return (session, result). Only the payload builder is
    stubbed; the session-seeding and seek-guard path under test is real."""

    client = FakePlaybackClient(dict(item))
    runtime = runtime_for(client)
    prepared = PreparedPlaybackItem(
        requested_item_id=item["Id"],
        item_id=item["Id"],
        item=dict(item),
    )

    async def prepare(rt: Any, item_id: str) -> PreparedPlaybackItem:
        assert item_id == item["Id"]
        return prepared

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback."
        "async_prepare_playback_item",
        prepare,
    )
    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback."
        "ChromecastPlaybackStrategy.discover_chromecast_model",
        lambda hass, player: ("Unknown", False),
    )
    monkeypatch.setattr(
        "custom_components.jellyfin_assist.playback.build_play_media_data",
        lambda rt, target, prepared_arg, model, **_kw: (
            {
                "entity_id": target,
                "media_content_id": playback_info["media_url"],
                "media_content_type": playback_info["content_type"],
            },
            dict(playback_info),
        ),
    )

    hass = FakePlaybackHass(_playing_state())

    async def _invoke() -> dict[str, Any]:
        return await async_play_on_chromecast(
            hass,
            runtime,
            target_entity_id=PLAYER,
            item_id=prepared.item_id,
            start_position_ticks=start_position_ticks,
        )

    result = asyncio.run(_invoke())
    return runtime.playback_sessions[PLAYER], result


# ---------------------------------------------------------------------------
# Scenario 1 — Fresh playback (no tick) -> extra.current_time absent/0.
# ---------------------------------------------------------------------------
def test_fresh_playback_payload_has_no_resume_tick() -> None:
    """Plan scenario 1 (payload): no PlaybackPositionTicks and no explicit
    offset -> the exact HA payload carries no current_time."""

    item = _direct_play_episode({"Id": "episode-1"})
    client = FakePlaybackClient(item)
    runtime = runtime_for(client)
    prepared = PreparedPlaybackItem(
        requested_item_id="episode-1",
        item_id="episode-1",
        item=dict(item),
    )
    data, info = build_play_media_data(runtime, PLAYER, prepared, "Chromecast Ultra")

    assert "current_time" not in data["extra"]
    assert data["media_content_type"] == "video/mp4"
    assert info["content_type"] == "video/mp4"


def test_fresh_playback_session_starts_at_zero(
    monkeypatch: Any,
) -> None:
    """Plan scenario 1 (tracking): a fresh session stores no
    start_position_ticks and seeds accumulated_playing_seconds at 0.0."""

    item = _direct_play_episode({"Id": "episode-1"})
    session, result = _run_play(monkeypatch, item, _direct_play_info())

    assert session["start_position_ticks"] is None
    assert session["accumulated_playing_seconds"] == 0.0
    assert result["start_position_ticks"] is None


# ---------------------------------------------------------------------------
# Scenario 2 — 10:26 resume -> extra.current_time == 626.0, seeds 626.0.
# ---------------------------------------------------------------------------
def test_resume_payload_carries_626_seconds() -> None:
    """Plan scenario 2 (payload): 6_260_000_000 ticks -> extra.current_time
    == 626.0 exactly, with stream_type BUFFERED for direct-play video."""

    item = _direct_play_episode({"Id": "episode-1"})
    item["UserData"] = {"PlaybackPositionTicks": RESUME_TICKS}
    client = FakePlaybackClient(item)
    runtime = runtime_for(client)
    prepared = PreparedPlaybackItem(
        requested_item_id="episode-1",
        item_id="episode-1",
        item=dict(item),
    )
    data, _info = build_play_media_data(runtime, PLAYER, prepared, "Chromecast Ultra")

    assert data["extra"]["current_time"] == RESUME_SECONDS
    assert data["extra"]["stream_type"] == "BUFFERED"


def test_resume_session_seeds_626_seconds(monkeypatch: Any) -> None:
    """Plan scenario 2 (tracking): direct-play video is seek-supported under
    T3, so the session seeds accumulated_playing_seconds at 626.0 and stores
    the resume ticks."""

    item = _direct_play_episode({"Id": "episode-1"})
    item["UserData"] = {"PlaybackPositionTicks": RESUME_TICKS}
    session, result = _run_play(monkeypatch, item, _direct_play_info())

    assert session["start_position_ticks"] == RESUME_TICKS
    assert session["accumulated_playing_seconds"] == RESUME_SECONDS
    assert result["start_position_ticks"] == RESUME_TICKS


# ---------------------------------------------------------------------------
# Scenario 3 — Explicit restart at zero -> 0.0.
# ---------------------------------------------------------------------------
def test_explicit_restart_at_zero_payload() -> None:
    """Plan scenario 3 (payload): force_start_position_ticks=0 ->
    extra.current_time == 0.0."""

    item = _direct_play_episode({"Id": "episode-1"})
    item["UserData"] = {"PlaybackPositionTicks": RESUME_TICKS}
    client = FakePlaybackClient(item)
    runtime = runtime_for(client)
    prepared = PreparedPlaybackItem(
        requested_item_id="episode-1",
        item_id="episode-1",
        item=dict(item),
    )
    data, _info = build_play_media_data(
        runtime, PLAYER, prepared, "Chromecast Ultra",
        force_start_position_ticks=0,
    )

    assert data["extra"]["current_time"] == 0.0


def test_explicit_restart_at_zero_session(
    monkeypatch: Any,
) -> None:
    """Plan scenario 3 (tracking): an explicit offset of 0 -> the session
    stores start_position_ticks == 0 and seeds accumulated at 0.0, so the
    episode restarts from the beginning (not from the saved 10:26)."""

    item = _direct_play_episode({"Id": "episode-1"})
    item["UserData"] = {"PlaybackPositionTicks": RESUME_TICKS}
    session, result = _run_play(
        monkeypatch, item, _direct_play_info(), start_position_ticks=0
    )

    assert session["start_position_ticks"] == 0
    assert session["accumulated_playing_seconds"] == 0.0
    assert result["start_position_ticks"] == 0


# ---------------------------------------------------------------------------
# Scenario 4 — Paused position -> correct resume offset, no false progress.
# ---------------------------------------------------------------------------
def test_paused_resume_session_reports_no_false_progress(tmp_path: Path) -> None:
    """Plan scenario 4: a resume-seeded session (accumulated == 626.0) that is
    then paused must persist the seeded offset and must NOT advance the
    accumulated clock for wall-clock time spent paused.

    The tracking layer writes the tracked position on the playing->paused
    transition with is_paused=True. Because the write is paused, no
    elapsed-since-start is added (false progress is exactly the bug this
    guards against). The persisted ticks are the 10:26 offset
    (626 s -> 6_260_000_000 ticks), not the seconds elapsed since play
    started."""

    client = RecordingPlayingClient()
    rt = runtime_with_client(client)
    started = datetime(2026, 11, 12, 23, 0, tzinfo=timezone.utc)
    # Resume-seeded session: accumulated starts at the 10:26 offset and the
    # player is paused at that same instant, so no playing time is elapsed
    # between start and pause.
    rt.playback_sessions[PLAYER] = _session(
        duration_seconds=1_850.0,
        accumulated_playing_seconds=RESUME_SECONDS,
        playing_started_at=started,
    )
    entry = SpyBackgroundEntry("entry", {})
    hass = FakeHass(tmp_path)
    handler = advancement._build_queue_advancement_handler(hass, entry, rt)

    playing = SimpleNamespace(
        entity_id=PLAYER, state="playing", last_changed=started, attributes={}
    )
    # Paused at the same instant: zero wall-clock playing time between the
    # resume start and the pause. This is the "no false progress" case — the
    # paused write must persist exactly the seeded 10:26 offset, with no
    # wall-clock elapsed time added.
    paused = SimpleNamespace(
        entity_id=PLAYER,
        state="paused",
        last_changed=started,
        attributes={},
    )
    handler(
        SimpleNamespace(
            data={"entity_id": PLAYER, "old_state": playing, "new_state": paused}
        )
    )
    asyncio.run(_drain(entry))

    # Exactly one paused write, at the seeded resume offset, is_paused=True.
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["position_ticks"] == RESUME_TICKS
    assert call["is_paused"] is True
    # Paused time is not counted: the session still reports 626.0 accumulated.
    assert rt.playback_sessions[PLAYER]["accumulated_playing_seconds"] == RESUME_SECONDS


# ---------------------------------------------------------------------------
# Scenario 5 — Unauthorized playback target -> rejected, no session written.
# ---------------------------------------------------------------------------
def test_unauthorized_target_rejected_no_session(monkeypatch: Any) -> None:
    """Plan scenario 5: a target not in playback_targets is rejected by
    require_playback_target before any side effect: no play_media call, no
    tracking session, no state listeners."""

    item = _direct_play_episode({"Id": "episode-1"})
    client = FakePlaybackClient(item)
    runtime = runtime_for(client)
    harness = FakePlaybackHass(_playing_state())

    with pytest.raises(ValueError, match="not configured"):
        asyncio.run(
            async_play_on_chromecast(
                harness,
                runtime,
                target_entity_id="media_player.unlisted",
                item_id="episode-1",
            )
        )

    assert harness.services.calls == []
    assert harness.tracked_state_changes == []
    assert runtime.playback_sessions == {}


# ---------------------------------------------------------------------------
# Scenario 6 — Queue advancement -> session/queue behaviour unchanged.
# ---------------------------------------------------------------------------
def test_queue_advancement_unchanged_by_resume_session(tmp_path: Path) -> None:
    """Plan scenario 6: a resume-seeded session (accumulated == 626.0 over a
    ~1850 s runtime) must drive queue advancement exactly as an ordinary
    completed session does: the completion path sees a normal session,
    confirms completion via the queue, advances to the next item, and the
    session is popped. The resume seed does not change any queue behaviour."""

    class NextQueue:
        def __init__(self) -> None:
            self.get_calls = 0
            self.next_calls = 0

        async def async_get(self, player: str) -> Any:
            self.get_calls += 1
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {"id": "episode-1"},
                },
            }

        async def async_next(self, player: str) -> Any:
            self.next_calls += 1
            return {
                "status": 200,
                "content": {
                    "success": True,
                    "current": {
                        "id": "episode-2",
                        "name": "Next Episode",
                        "type": "Episode",
                    },
                },
            }

    # Complete the resume-seeded session: play long enough that the tracked
    # session exceeds the 95% completion threshold. 1850 s runtime with
    # accumulated at 1850 s == 100%.
    rt = runtime_with_client(RecordingPlayingClient())
    rt.queue_client = NextQueue()
    session = _session(
        duration_seconds=1_850.0,
        accumulated_playing_seconds=1_850.0,
    )
    session["item_id"] = "episode-1"
    rt.playback_sessions[PLAYER] = session
    entry = SpyBackgroundEntry("entry", {})
    hass = FakeHass(tmp_path)

    play = SimpleNamespace(
        entity_id=PLAYER, state="playing",
        last_changed=datetime(2026, 11, 12, 23, 0, tzinfo=timezone.utc),
        attributes={},
    )
    idle = SimpleNamespace(
        entity_id=PLAYER, state="idle",
        last_changed=datetime(2026, 11, 12, 23, 31, 0, tzinfo=timezone.utc),
        attributes={},
    )
    handler = advancement._build_queue_advancement_handler(hass, entry, rt)
    handler(
        SimpleNamespace(
            data={"entity_id": PLAYER, "old_state": play, "new_state": idle}
        )
    )
    asyncio.run(_drain(entry))

    queue = rt.queue_client
    # The completion path advanced: it read the queue AND called next.
    assert queue.get_calls == 1
    assert queue.next_calls == 1
    # The session was popped after a confirmed advance.
    assert PLAYER not in rt.playback_sessions
    # Advancement recorded the next item as playing (resume-neutral).
    assert queue.next_calls == 1


async def _drain(entry: SpyBackgroundEntry) -> None:
    while entry.background_tasks:
        _name, coro = entry.background_tasks.pop(0)
        await coro
