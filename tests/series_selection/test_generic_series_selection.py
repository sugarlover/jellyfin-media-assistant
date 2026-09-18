"""Focused unit tests for the pure generic-series episode selection policy.

These tests mechanically prove the nine JMA-SERIES-002 acceptance cases from
``docs/development/series-playback-fallback-requirements.md`` and
``docs/development/series-playback-fallback-kanban.md``:

1. S1 >15 -> all S1 only.
2. S1 =15 -> all 15.
3. S1 1..14 -> top up chronologically to 15.
4. Entire series <15 -> all available regular episodes.
5. No S1 -> first 15 regular episodes.
6. Specials (season 0) excluded.
7. Missing episode numbers skipped without reordering.
8. Duplicate episode identities do not duplicate the plan.
9. No regular episodes -> empty selection.

They exercise only
``custom_components.jellyfin_assist.series_selection``: a deterministic,
side-effect-free policy over already retrieved episode metadata. No Home
Assistant, Jellyfin, orchestration, playback, or queue behavior is touched.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

import pytest

from custom_components.jellyfin_assist.series_selection import (
    EPISODES_PER_GENERIC_SERIES_SESSION,
    deduplicate_episode_rows,
    ordered_unique_episodes,
    select_explicit_season_episodes,
    select_generic_series_episodes,
)


def _episode(
    season: int,
    episode: int,
    *,
    item_id: str | None = "id-0",
    name: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build one episode row shaped like the ordered whole-series lookup output."""

    row: dict[str, Any] = {
        "Id": item_id,
        "ParentIndexNumber": season,
        "IndexNumber": episode,
        "Name": name or f"Season {season} Episode {episode}",
        "Type": "Episode",
    }
    row.update(extra)
    return row


def _season(
    season: int,
    episodes: Iterable[int],
    item_prefix: str | None = None,
    drop: Iterable[int] = (),
) -> list[dict[str, Any]]:
    """Build a season's available episodes with deterministic ids."""

    prefix = item_prefix or f"s{season}"
    return [
        _episode(season, number, item_id=f"{prefix}e{number}")
        for number in episodes
        if number not in drop
    ]


def _plan_keys(rows: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Reduce a plan to its chronological (season, episode) identity list."""

    return [
        (int(row["ParentIndexNumber"]), int(row["IndexNumber"]))
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Acceptance case 1: Season 1 has more than 15 episodes -> all Season 1 only
# ---------------------------------------------------------------------------


def test_case1_s1_over_target_keeps_all_season_one_and_no_later_episodes() -> None:
    season_one = _season(1, range(1, 17))  # 16 available Season 1 episodes
    rest = _season(2, range(1, 8), item_prefix="s2")

    plan = select_generic_series_episodes(season_one + rest)

    assert _plan_keys(plan) == [(1, episode) for episode in range(1, 17)]
    assert len(plan) == 16
    assert not any(season != 1 for season, _ in _plan_keys(plan))


# ---------------------------------------------------------------------------
# Acceptance case 2: Season 1 has exactly 15 -> all 15 Season 1 episodes
# ---------------------------------------------------------------------------


def test_case2_s1_exactly_target_returns_all_fifteen() -> None:
    season_one = _season(1, range(1, 16))  # exactly 15
    season_two = _season(2, range(1, 6), item_prefix="s2")

    plan = select_generic_series_episodes(season_one + season_two)

    assert _plan_keys(plan) == [(1, episode) for episode in range(1, 16)]
    assert len(plan) == 15
    assert "s2e1" not in {row["Id"] for row in plan}


# ---------------------------------------------------------------------------
# Acceptance case 3: Season 1 has 1..14 -> top up chronologically to 15
# ---------------------------------------------------------------------------


def test_case3_short_s1_tops_up_chronologically_until_fifteen() -> None:
    season_one = _season(1, (2, 7, 9))
    later = _season(2, (1, 3, 4, 6, 8, 10, 12, 14), item_prefix="s2") + _season(
        3, range(1, 7), item_prefix="s3"
    )

    plan = select_generic_series_episodes(season_one + later)

    # All three Season 1 episodes keep their chronological relative order,
    # followed by the earliest later regular episodes in chronological order
    # until the plan reaches exactly 15.  Gaps inside the later seasons do
    # not shift the ordering.
    assert _plan_keys(plan) == [
        (1, 2),
        (1, 7),
        (1, 9),
        (2, 1),
        (2, 3),
        (2, 4),
        (2, 6),
        (2, 8),
        (2, 10),
        (2, 12),
        (2, 14),
        (3, 1),
        (3, 2),
        (3, 3),
        (3, 4),
    ]
    assert len(plan) == 15  # 3 + 12, never beyond the target
    assert (3, 5) not in _plan_keys(plan)
    assert (3, 6) not in _plan_keys(plan)


def test_case3_boundary_s1_fourteen_plus_one_top_up() -> None:
    season_one = _season(1, range(1, 15))  # 14
    later = _season(2, range(1, 26), item_prefix="s2") + _season(
        3, range(1, 4), item_prefix="s3"
    )

    plan = select_generic_series_episodes(season_one + later)

    assert len(plan) == 15
    assert _plan_keys(plan) == (
        [(1, episode) for episode in range(1, 15)] + [(2, 1)]
    )
    assert (2, 13) not in _plan_keys(plan)
    assert (2, 25) not in _plan_keys(plan)
    assert (3, 1) not in _plan_keys(plan)


def test_case3_boundary_s1_one_plus_fourteen_top_ups() -> None:
    season_one = _season(1, (1,))
    later = _season(2, range(1, 15), item_prefix="s2") + _season(3, (1, 2), item_prefix="s3")

    plan = select_generic_series_episodes(season_one + later)

    assert _plan_keys(plan) == [(1, 1)] + [(2, episode) for episode in range(1, 15)]
    assert len(plan) == 15
    assert (3, 1) not in _plan_keys(plan)


# ---------------------------------------------------------------------------
# Acceptance case 4: entire series <15 total -> all available regular episodes
# ---------------------------------------------------------------------------


def test_case4_entire_series_under_target_returns_all_regular_episodes() -> None:
    series = _season(2, (1, 2, 3), item_prefix="s2") + _season(
        4, (1, 2, 3, 4, 5), item_prefix="s4"
    )

    plan = select_generic_series_episodes(series)

    assert _plan_keys(plan) == (
        [(2, episode) for episode in (1, 2, 3)]
        + [(4, episode) for episode in range(1, 6)]
    )
    assert len(plan) == 8


# ---------------------------------------------------------------------------
# Acceptance case 5: no Season 1 -> first 15 regular episodes chronologically
# ---------------------------------------------------------------------------


def test_case5_no_s1_starts_at_earliest_regular_season() -> None:
    series = _season(0, (1, 2), item_prefix="s0") + _season(
        2, (1, 2, 3, 4), item_prefix="s2"
    ) + _season(3, (1, 2, 3, 4, 5, 6, 7, 8, 9, 10), item_prefix="s3")
    # 14 regular episodes only: all of them, in order.

    plan = select_generic_series_episodes(series)

    assert _plan_keys(plan) == (
        [(2, episode) for episode in range(1, 5)]
        + [(3, episode) for episode in range(1, 11)]
    )
    assert len(plan) == 14


def test_case5_no_s1_truncates_at_fifteen_regular_episodes() -> None:
    series = _season(0, (1, 2), item_prefix="s0") + _season(
        2, (1, 2, 3, 4), item_prefix="s2"
    ) + _season(3, range(1, 21), item_prefix="s3")
    # 24 regular episodes: only the first 15 are returned.

    plan = select_generic_series_episodes(series)

    assert _plan_keys(plan) == (
        [(2, episode) for episode in range(1, 5)]
        + [(3, episode) for episode in range(1, 12)]
    )
    assert len(plan) == 15
    assert (3, 12) not in _plan_keys(plan)
    assert (3, 20) not in _plan_keys(plan)


# ---------------------------------------------------------------------------
# Acceptance case 6: Season 0 / Specials excluded from generic selection
# ---------------------------------------------------------------------------


def test_case6_specials_never_appear_in_a_generic_plan() -> None:
    series = _season(0, (1, 2, 3), item_prefix="special")

    plan = select_generic_series_episodes(series)

    assert plan == []


def test_case6_specials_do_not_fill_the_fifteen_target() -> None:
    series = _season(0, range(1, 11), item_prefix="special") + _season(
        2, range(1, 6), item_prefix="s2"
    )

    plan = select_generic_series_episodes(series)

    assert _plan_keys(plan) == [(2, episode) for episode in range(1, 6)]
    assert "special" not in {row["Id"] for row in plan}
    assert len(plan) == 5  # 10 specials cannot substitute for 15 regular episodes


def test_case6_specials_are_dropped_from_ordering_too() -> None:
    specials = _season(0, (1, 2), item_prefix="special")
    regular = _season(2, (1, 2), item_prefix="s2")

    assert ordered_unique_episodes(specials + regular) == regular
    assert deduplicate_episode_rows(specials + regular) == regular


# ---------------------------------------------------------------------------
# Acceptance case 7: missing episode numbers skipped without reordering
# ---------------------------------------------------------------------------


def test_case7_missing_numbers_do_not_reorder_available_episodes() -> None:
    # Season 2 is missing episodes 3-7 and 8; 9, 10, 13 and 25 exist.
    # Season 3 is incomplete (1, 2, 5). Season 1 has only episode 4.
    series = _season(1, (4,)) + _season(
        2, (1, 2, 9, 10, 13, 25), item_prefix="s2"
    ) + _season(3, (1, 2, 5), item_prefix="s3")

    plan = select_generic_series_episodes(series)

    assert _plan_keys(plan) == [
        (1, 4),
        (2, 1),
        (2, 2),
        (2, 9),
        (2, 10),
        (2, 13),
        (2, 25),
        (3, 1),
        (3, 2),
        (3, 5),
    ]
    assert len(plan) == 10
    assert sorted(_plan_keys(plan)) == _plan_keys(plan)


def test_case7_missing_numbers_are_skipped_inside_the_top_up() -> None:
    season_one = _season(1, (1, 2))
    later = _season(2, (1, 2, 9, 10), item_prefix="s2")
    # 4 regular episodes available: all are used, no placeholders invented.

    plan = select_generic_series_episodes(season_one + later)

    assert _plan_keys(plan) == [(1, 1), (1, 2), (2, 1), (2, 2), (2, 9), (2, 10)]
    assert len(plan) == 6
    assert (2, 3) not in _plan_keys(plan)


# ---------------------------------------------------------------------------
# Acceptance case 8: duplicate episode identities do not duplicate the plan
# ---------------------------------------------------------------------------


def test_case8_duplicate_rows_appear_exactly_once() -> None:
    original = _season(1, (1, 2, 3)) + _season(2, (1, 2, 3), item_prefix="s2")
    duplicates = [
        _episode(1, 2, item_id="1-2-duplicate"),
        _episode(1, 1, item_id="1-1-duplicate"),
        _episode(2, 3, item_id="2-3-duplicate"),
    ]

    plan = select_generic_series_episodes(original + duplicates)

    assert _plan_keys(plan) == [
        (1, 1),
        (1, 2),
        (1, 3),
        (2, 1),
        (2, 2),
        (2, 3),
    ]
    keys = _plan_keys(plan)
    assert len(keys) == len(set(keys))


def test_case8_duplicate_protection_respects_the_fifteen_target() -> None:
    original = _season(2, range(1, 16), item_prefix="s2")  # 15 regular, no S1
    duplicates = [
        _episode(2, number, item_id=f"s2e{number}-dup") for number in range(1, 16)
    ]

    plan = select_generic_series_episodes(original + duplicates)

    assert len(plan) == 15
    assert _plan_keys(plan) == [(2, number) for number in range(1, 16)]
    assert len({(row["ParentIndexNumber"], row["IndexNumber"]) for row in plan}) == 15


def test_duplicate_rows_keep_the_richest_representation() -> None:
    first = _episode(1, 1, item_id="1-1-poor")
    duplicate = _episode(1, 1, item_id="1-1-full", name="Pilot", **{"SeriesId": "series-x"})
    poor_then_rich = [deepcopy(first), deepcopy(duplicate)]
    rich_then_poor = [deepcopy(duplicate), deepcopy(first)]

    assert deduplicate_episode_rows(poor_then_rich) == [dict(duplicate)]
    assert deduplicate_episode_rows(rich_then_poor) == [dict(duplicate)]


# ---------------------------------------------------------------------------
# Deterministic ordering by season then episode ascending
# ---------------------------------------------------------------------------


def test_selection_is_chronological_when_input_arrives_unordered() -> None:
    rows = [
        _episode(3, 2, item_id="s3e2"),
        _episode(1, 9, item_id="s1e9"),
        _episode(2, 1, item_id="s2e1"),
        _episode(1, 3, item_id="s1e3"),
        _episode(2, 5, item_id="s2e5"),
        _episode(3, 1, item_id="s3e1"),
    ]

    assert ordered_unique_episodes(rows) == [
        _episode(1, 3, item_id="s1e3"),
        _episode(1, 9, item_id="s1e9"),
        _episode(2, 1, item_id="s2e1"),
        _episode(2, 5, item_id="s2e5"),
        _episode(3, 1, item_id="s3e1"),
        _episode(3, 2, item_id="s3e2"),
    ]


def test_same_input_produces_identical_plans() -> None:
    rows = [
        _episode(4, 2, item_id="s4e2"),
        _episode(2, 9, item_id="s2e9"),
        _episode(3, 1, item_id="s3e1"),
        _episode(2, 1, item_id="s2e1"),
    ]

    first = select_generic_series_episodes(rows)
    second = select_generic_series_episodes(list(reversed(rows)))

    assert _plan_keys(first) == _plan_keys(second) == [
        (2, 1),
        (2, 9),
        (3, 1),
        (4, 2),
    ]
    assert [row["Id"] for row in first] == [row["Id"] for row in second]


# ---------------------------------------------------------------------------
# Invalid metadata handling (missing season/episode numbers are skipped)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("season", "episode"),
    [
        (None, 1),
        ("1", 1),
        (1.5, 1),
        (True, 2),
        (1, None),
        (1, "2"),
        (1, -1),
        (0, 1),
        (-2, 1),
    ],
)
def test_rows_with_invalid_or_missing_numbers_are_skipped(season: Any, episode: Any) -> None:
    items = [
        _episode(2, 1, item_id="valid-s2e1"),
        _episode(season, episode, item_id="invalid-row"),  # type: ignore[arg-type]
    ]

    assert ordered_unique_episodes(items) == [_episode(2, 1, item_id="valid-s2e1")]


def test_only_invalid_rows_produce_an_empty_selection() -> None:
    items = [
        _episode(None, 1, item_id="missing-season"),
        _episode(2, None, item_id="missing-episode"),
        _episode("2", "1", item_id="text-numbers"),
    ]

    assert ordered_unique_episodes(items) == []
    assert select_generic_series_episodes(items) == []


# ---------------------------------------------------------------------------
# Acceptance case 9 (support): empty-result edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows",
    [
        [],
        _season(0, (1, 2, 3), item_prefix="special"),
        [
            _episode(None, 1, item_id="missing-season"),
            _episode(2, None, item_id="missing-episode"),
        ],
    ],
)
def test_no_regular_episodes_yields_an_empty_selection(
    rows: list[dict[str, Any]],
) -> None:
    assert select_generic_series_episodes(rows) == []
    assert select_explicit_season_episodes(rows, 1) == []
    assert ordered_unique_episodes(rows) == []


def test_empty_input_yields_an_empty_deduplicated_list() -> None:
    assert ordered_unique_episodes([]) == []
    assert deduplicate_episode_rows([]) == []


# ---------------------------------------------------------------------------
# Target constant
# ---------------------------------------------------------------------------


def test_generic_series_session_target_is_fifteen() -> None:
    assert EPISODES_PER_GENERIC_SERIES_SESSION == 15


# ---------------------------------------------------------------------------
# Explicit-season boundary (no top-up behavior for explicit requests)
# ---------------------------------------------------------------------------


def test_explicit_season_request_is_bounded_to_the_requested_season() -> None:
    series = _season(1, (1, 2), item_prefix="s1") + _season(2, (1, 2, 3), item_prefix="s2")

    plan = select_explicit_season_episodes(series, 2)

    assert _plan_keys(plan) == [(2, 1), (2, 2), (2, 3)]


def test_explicit_season_with_one_episode_yields_a_one_item_plan() -> None:
    series = _season(3, (7,), item_prefix="s3") + _season(1, (1, 2), item_prefix="s1")

    plan = select_explicit_season_episodes(series, 3)

    assert _plan_keys(plan) == [(3, 7)]
    assert len(plan) == 1


def test_explicit_season_zero_and_invalid_requests_are_empty() -> None:
    series = _season(0, (1,), item_prefix="special") + _season(1, (1,), item_prefix="s1")

    assert select_explicit_season_episodes(series, 0) == []
    assert select_explicit_season_episodes(series, -1) == []


# ---------------------------------------------------------------------------
# The policy is side-effect-free
# ---------------------------------------------------------------------------


def test_selection_does_not_mutate_caller_input_or_alias_returned_rows() -> None:
    rows = _season(1, (1, 2))
    before = deepcopy(rows)

    plan = select_generic_series_episodes(rows)

    assert rows == before
    assert plan[0] is not rows[0]
    assert plan[1] is not rows[1]
    plan[0]["Name"] = "mutated"
    assert rows[0]["Name"] == "Season 1 Episode 1"
