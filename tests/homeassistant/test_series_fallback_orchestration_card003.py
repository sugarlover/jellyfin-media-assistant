"""JMA-SERIES-003: orchestration-level tests for generic-series selection.

Exercise the real async resolver and orchestrator with mocked Jellyfin/player
boundaries; the pure selection policy is already tested separately.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.homeassistant.ha_stubs import FakeHass, FakeState, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist import orchestration
from custom_components.jellyfin_assist.orchestration import (
    async_media_orchestrator,
    async_resolve_media_intent,
)
from custom_components.jellyfin_assist.runtime import JellyfinAssistRuntime
from custom_components.jellyfin_assist.search import CatalogManager


SERIES_ID = "series-1"
SERIES_NAME = "Example Show"
PLAYER = "media_player.living_room_tv"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _runtime() -> JellyfinAssistRuntime:
    async def unused_loader() -> Any:
        raise AssertionError("catalog loader must not run")

    return JellyfinAssistRuntime(
        client=object(),  # type: ignore[arg-type]
        catalog_manager=CatalogManager(
            snapshot_loader=unused_loader,
            requested_types=["Movie"],
            cache_identity="server:user",
            cache_store=None,
        ),
        connection_info=None,
        entry_id="entry-1",
        user_id="user-1",
    )


def _season(season: int, count: int) -> list[dict[str, Any]]:
    return [
        {
            "Id": f"s{season}e{number}",
            "Name": f"Season {season} Episode {number}",
            "Type": "Episode",
            "ParentIndexNumber": season,
            "IndexNumber": number,
        }
        for number in range(1, count + 1)
    ]


def _keys(items: list[dict[str, Any]]) -> list[tuple[int, int]]:
    return [(int(item["season"]), int(item["episode"])) for item in items]


def _install_search(monkeypatch: Any, rows: list[dict[str, Any]], *,
                    fail_lookup: bool = False) -> list[str]:
    """Mock only Jellyfin search/action boundaries; record the service used."""
    services: list[str] = []

    async def search(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["media_type"] == "Series"
        return {"items": [{"id": SERIES_ID, "name": SERIES_NAME, "type": "Series"}]}

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        service = args[2]
        services.append(service)
        if service == "search_series":
            assert args[3]["series_id"] == SERIES_ID
            if fail_lookup:
                return {"status": 503, "content": {}}
            return {"status": 200, "content": {"Items": rows}}
        if service == "search_season":
            return {"status": 200, "content": {"Items": rows}}
        raise AssertionError(f"unexpected Jellyfin action: {service}")

    monkeypatch.setattr(orchestration, "_search", search)
    monkeypatch.setattr(orchestration, "_action", action)
    return services


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({1: 16, 2: 3}, [(1, n) for n in range(1, 17)]),
        ({1: 15, 2: 2}, [(1, n) for n in range(1, 16)]),
        ({1: 4, 2: 7, 3: 7},
         [(1, n) for n in range(1, 5)]
         + [(2, n) for n in range(1, 8)]
         + [(3, n) for n in range(1, 5)]),
        ({1: 2, 2: 3}, [(1, 1), (1, 2), (2, 1), (2, 2), (2, 3)]),
        ({2: 10, 3: 10},
         [(2, n) for n in range(1, 11)]
         + [(3, n) for n in range(1, 6)]),
        ({0: 10, 1: 2, 2: 20},
         [(1, 1), (1, 2)] + [(2, n) for n in range(1, 14)]),
    ],
    ids=[
        "season-one-over-15-keeps-all-season-one",
        "season-one-exactly-15",
        "short-season-one-tops-up-chronologically",
        "fewer-than-15-total-uses-all",
        "missing-season-one-starts-earliest-regular-season",
        "specials-excluded-from-generic-request",
    ],
)
def test_generic_series_resolver_uses_whole_series_and_selected_episode_plan(
    tmp_path: Path, monkeypatch: Any, counts: dict[int, int],
    expected: list[tuple[int, int]],
) -> None:
    rows = [row for season, count in counts.items() for row in _season(season, count)]
    # Unsorted input proves the whole-series boundary and selector establish order.
    services = _install_search(monkeypatch, list(reversed(rows)))
    result = _run(async_resolve_media_intent(
        FakeHass(tmp_path), _runtime(), query=SERIES_NAME, media_type="Series",
    ))

    assert services == ["search_series"]
    assert result["success"] is True
    assert result["status"] == "resolved"
    assert result["intent"] == "Series"
    assert _keys(result["playback_plan"]) == expected
    assert [item["id"] for item in result["playback_plan"]] == [
        f"s{s}e{e}" for s, e in expected
    ]
    assert all(item["series_id"] == SERIES_ID for item in result["playback_plan"])


@pytest.mark.parametrize("rows", [[], _season(0, 5)], ids=["empty-series", "specials-only"])
def test_generic_series_without_regular_episodes_fails_cleanly(
    tmp_path: Path, monkeypatch: Any, rows: list[dict[str, Any]],
) -> None:
    services = _install_search(monkeypatch, rows)
    result = _run(async_resolve_media_intent(
        FakeHass(tmp_path), _runtime(), query=SERIES_NAME, media_type="Series",
    ))
    assert services == ["search_series"]
    assert result["success"] is False
    assert result["status"] == "series_empty"
    assert not result.get("playback_plan")
    assert "no playable episodes" in result["message"].lower()


def test_generic_series_lookup_error_is_not_reported_as_empty(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    services = _install_search(monkeypatch, [], fail_lookup=True)
    result = _run(async_resolve_media_intent(
        FakeHass(tmp_path), _runtime(), query=SERIES_NAME, media_type="Series",
    ))
    assert services == ["search_series"]
    assert result["success"] is False
    assert result["status"] == "series_lookup_failed"
    assert not result.get("playback_plan")


@pytest.mark.parametrize("count", [1, 3], ids=["one-episode", "several-episodes"])
def test_explicit_season_stays_bounded_without_generic_lookup(
    tmp_path: Path, monkeypatch: Any, count: int,
) -> None:
    rows = _season(2, count)
    services = _install_search(monkeypatch, rows)
    result = _run(async_resolve_media_intent(
        FakeHass(tmp_path), _runtime(), query=SERIES_NAME,
        media_type="Series", season=2,
    ))
    assert services == ["search_season"]
    assert result["success"] is True
    assert _keys(result["playback_plan"]) == [(2, n) for n in range(1, count + 1)]


@pytest.mark.parametrize("operation", ["play", "add"])
def test_play_and_add_consume_actual_generic_series_plan(
    tmp_path: Path, monkeypatch: Any, operation: str,
) -> None:
    rows = _season(1, 3) + _season(2, 16)
    expected = [f"s1e{n}" for n in range(1, 4)] + [f"s2e{n}" for n in range(1, 13)]
    recorded: list[tuple[str, str | None]] = []
    hass = FakeHass(tmp_path, states=[FakeState(PLAYER, friendly_name="Living Room TV")])

    async def search(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["media_type"] == "Series"
        return {"items": [{"id": SERIES_ID, "name": SERIES_NAME, "type": "Series"}]}

    async def action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        service = args[2]
        if service == "resolve_media_player":
            return {
                "success": True, "media_player": PLAYER,
                "media_player_name": "Living Room TV", "query": SERIES_NAME,
                "media_type": "Series",
            }
        if service == "search_series":
            assert args[3]["series_id"] == SERIES_ID
            return {"status": 200, "content": {"Items": list(reversed(rows))}}
        if service == "queue_clear":
            recorded.append(("clear", None))
            return {"status": 200, "content": {"success": True}}
        if service == "queue_add":
            # The production play path passes selected item data to this boundary.
            payload = args[3]
            item_id = payload["id"]
            recorded.append(("queue", str(item_id) if item_id is not None else None))
            return {"status": 200, "content": {"success": True, "status": "added"}}
        raise AssertionError(f"unexpected action: {service}")

    async def identity_plan(runtime: Any, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return plan

    async def prepare(*args: Any, **kwargs: Any) -> dict[str, Any]:
        recorded.append(("prepare", None))
        return {"success": True, "status": "ready"}

    async def play(*args: Any, **kwargs: Any) -> dict[str, Any]:
        recorded.append(("play", kwargs["item"]["id"]))
        return {"success": True, "status": "playing"}

    async def add(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["media_player"] == PLAYER
        recorded.append(("add", kwargs["item"]["id"]))
        return {"success": True, "status": "added"}

    monkeypatch.setattr(orchestration, "_search", search)
    monkeypatch.setattr(orchestration, "_action", action)
    monkeypatch.setattr(orchestration, "_normalize_playback_plan", identity_plan)
    monkeypatch.setattr(orchestration, "async_prepare_play_session", prepare)
    monkeypatch.setattr(orchestration, "async_play_item", play)
    monkeypatch.setattr(orchestration, "async_queue_add_item", add)

    result = _run(async_media_orchestrator(
        hass, _runtime(), query=SERIES_NAME, media_type="Series",
        media_player=PLAYER, operation=operation,
    ))
    assert result["success"] is True
    assert result["status"] == ("playing" if operation == "play" else "added")
    assert [item["id"] for item in result["playback_plan"]] == expected
    if operation == "add":
        assert recorded == [("add", item_id) for item_id in expected]
    else:
        assert recorded[0:2] == [("prepare", None), ("clear", None)]
        assert [item_id for event, item_id in recorded if event == "queue"] == expected
        assert recorded[-1] == ("play", expected[0])
