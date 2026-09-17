"""Pure generic-series episode selection policy.

This module is deterministic and side-effect-free: it consumes an already
retrieved list of episode metadata dictionaries (as returned by the ordered
whole-series lookup) and returns the episode rows for one playback plan.

It does not call Home Assistant, Home Assistant services, or Jellyfin.
Orchestration wiring, playback, and queue behavior stay in their existing
modules; this module only decides which available episodes form a plan.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


EPISODES_PER_GENERIC_SERIES_SESSION: int = 15


def _season_number(item: Mapping[str, Any]) -> int | None:
    """Return the episode season as a positive integer, or None."""

    raw = item.get("ParentIndexNumber")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if raw > 0 else None


def _episode_number(item: Mapping[str, Any]) -> int | None:
    """Return the episode number as a non-negative integer, or None."""

    raw = item.get("IndexNumber")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if raw >= 0 else None


def _item_id(item: Mapping[str, Any]) -> str | None:
    raw = item.get("Id")
    return str(raw) if isinstance(raw, str) and raw else None


def _metadata_preference(item: Mapping[str, Any]) -> tuple[int, int]:
    """Rank candidate rows of one episode so the richest row wins.

    A row with a non-empty item ID always beats one without.  Otherwise the
    row carrying the most non-null metadata fields wins, so the plan keeps
    the most useful representation of each episode.
    """

    return (
        1 if _item_id(item) is not None else 0,
        sum(1 for value in item.values() if value is not None),
    )


def deduplicate_episode_rows(
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return ordered unique episode rows with complete season/episode numbers.

    Rows whose season or episode number is missing or invalid are skipped.
    An episode is identified by its (season, episode) pair; when the same
    episode appears more than once, it is reported exactly once, at its
    chronological position, keeping the richest available row.
    """

    seen: dict[tuple[int, int], dict[str, Any]] = {}

    for item in items:
        season = _season_number(item)
        episode = _episode_number(item)
        if season is None or episode is None:
            continue

        key = (season, episode)
        if key not in seen or _metadata_preference(item) > _metadata_preference(
            seen[key]
        ):
            seen[key] = dict(item)

    return sorted(seen.values(), key=lambda row: _order_key(row))


def _order_key(row: Mapping[str, Any]) -> tuple[int, int]:
    """Chronological sort key: season ascending, then episode ascending."""

    return (
        _season_number(row) or 0,
        _episode_number(row) or 0,
    )


def ordered_unique_episodes(
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return unique available episodes in chronological order."""

    return deduplicate_episode_rows(items)


def _season_of(row: Mapping[str, Any]) -> int | None:
    return _season_number(row)


def select_generic_series_episodes(
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Select the playback plan for a generic series request.

    Season 0 / Specials are excluded.  When Season 1 has 15 or more available
    episodes, all Season 1 episodes are returned and no later episodes are.
    When Season 1 has 1 to 14 available episodes, all Season 1 episodes are
    followed by the earliest later regular episodes in chronological order
    until the plan reaches 15 episodes or the series is exhausted.  When no
    Season 1 episodes are available, the first 15 regular episodes in
    chronological order are returned, or all of them when fewer exist.  An
    empty result means no regular episodes are available.
    """

    chronological = ordered_unique_episodes(items)
    target = EPISODES_PER_GENERIC_SERIES_SESSION

    season_one = [row for row in chronological if _season_of(row) == 1]
    later = [row for row in chronological if (_season_of(row) or 0) > 1]

    if len(season_one) >= target:
        # Season 1 alone reaches the session target; queue all of it whole.
        return list(season_one)

    if not season_one:
        # No Season 1 available; take the earliest regular episodes overall.
        return chronological[:target]

    plan = list(season_one)
    for row in later:
        if len(plan) >= target:
            break
        plan.append(row)
    return plan


def select_explicit_season_episodes(
    items: Sequence[Mapping[str, Any]],
    season: int,
) -> list[dict[str, Any]]:
    """Select the playback plan for an explicitly requested season.

    The plan is strictly season-bounded: all available episodes of the
    requested season in chronological order, and no episodes from any other
    season.  There is no 15-episode minimum or top-up behavior, and a
    one-episode season yields a one-item plan.
    """

    if isinstance(season, bool) or not isinstance(season, int) or season < 0:
        return []

    return [row for row in ordered_unique_episodes(items) if _season_of(row) == season]


__all__ = [
    "EPISODES_PER_GENERIC_SERIES_SESSION",
    "deduplicate_episode_rows",
    "ordered_unique_episodes",
    "select_explicit_season_episodes",
    "select_generic_series_episodes",
]
