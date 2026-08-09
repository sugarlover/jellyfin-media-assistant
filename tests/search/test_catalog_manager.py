"""Tests for reusable catalog lifecycle, refresh, cache, and timing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from custom_components.jellyfin_assist.matching import (
    MatchDecisionStatus,
    MediaSearchContext,
)
from custom_components.jellyfin_assist.search import (
    CatalogCacheDocument,
    CatalogCacheStore,
    CatalogDataSource,
    CatalogLoadStopReason,
    CatalogManager,
    CatalogRefreshError,
    CatalogSnapshot,
    CatalogUnavailableError,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def movie_snapshot(title: str = "Bubba Ho-tep") -> CatalogSnapshot:
    return CatalogSnapshot(
        requested_types=("Movie",),
        items=(
            {
                "Id": "movie-1",
                "Name": title,
                "Type": "Movie",
                "ProductionYear": 2002,
            },
        ),
        pages=(),
        raw_item_count=1,
        duplicate_item_count=0,
        missing_id_count=0,
        server_overflow_item_count=0,
        stop_reason=CatalogLoadStopReason.COMPLETE,
    )


class StepClock:
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


def manager(
    tmp_path: Path,
    loader: Any,
    *,
    clock: Any = lambda: 2000.0,
    monotonic: Any = None,
) -> CatalogManager:
    return CatalogManager(
        snapshot_loader=loader,
        requested_types=["Movie"],
        cache_identity="server:user",
        cache_store=CatalogCacheStore(tmp_path / "catalog.json"),
        clock=clock,
        monotonic=monotonic or __import__("time").perf_counter,
    )


def test_search_before_catalog_is_available_fails_clearly(tmp_path: Path) -> None:
    async def loader() -> CatalogSnapshot:
        return movie_snapshot()

    catalog = manager(tmp_path, loader)

    with pytest.raises(CatalogUnavailableError, match="not available"):
        catalog.search("Bubba ho tep")


def test_initialize_refreshes_on_cache_miss_and_searches_reused_index(
    tmp_path: Path,
) -> None:
    calls = 0

    async def loader() -> CatalogSnapshot:
        nonlocal calls
        calls += 1
        return movie_snapshot()

    catalog = manager(tmp_path, loader)
    diagnostics = run(catalog.async_initialize())
    first = catalog.search(
        "Bubba ho tep",
        context=MediaSearchContext(media_type="Movie"),
    )
    second = catalog.search(
        "Bubba ho tep",
        context=MediaSearchContext(media_type="Movie"),
    )

    assert calls == 1
    assert diagnostics.source is CatalogDataSource.REFRESH
    assert first.outcome.decision.status is MatchDecisionStatus.MATCHED
    assert second.outcome.selected_record.item_id == "movie-1"
    assert second.diagnostics.search_count == 2
    assert second.diagnostics.last_search_duration_ms is not None


def test_cache_restore_does_not_call_loader(tmp_path: Path) -> None:
    store = CatalogCacheStore(tmp_path / "catalog.json")
    store.write(
        CatalogCacheDocument(
            identity="server:user",
            created_at=1500.0,
            snapshot=movie_snapshot(),
        )
    )
    calls = 0

    async def loader() -> CatalogSnapshot:
        nonlocal calls
        calls += 1
        return movie_snapshot("Wrong")

    catalog = CatalogManager(
        snapshot_loader=loader,
        requested_types=["Movie"],
        cache_identity="server:user",
        cache_store=store,
        clock=lambda: 2000.0,
    )

    loaded = run(catalog.async_load_cache())
    result = catalog.search("Bubba ho tep")

    assert loaded is True
    assert calls == 0
    assert result.diagnostics.source is CatalogDataSource.CACHE
    assert result.diagnostics.cache_age_seconds == 500.0
    assert result.outcome.selected_record.item["Name"] == "Bubba Ho-tep"


def test_successful_refresh_atomically_replaces_old_index(tmp_path: Path) -> None:
    store = CatalogCacheStore(tmp_path / "catalog.json")
    store.write(
        CatalogCacheDocument(
            identity="server:user",
            created_at=1000.0,
            snapshot=movie_snapshot("Old Title"),
        )
    )

    async def loader() -> CatalogSnapshot:
        return movie_snapshot("New Title")

    catalog = CatalogManager(
        snapshot_loader=loader,
        requested_types=["Movie"],
        cache_identity="server:user",
        cache_store=store,
        clock=lambda: 2000.0,
    )
    assert run(catalog.async_load_cache()) is True

    run(catalog.async_refresh())

    assert catalog.search("New Title").outcome.decision.status is MatchDecisionStatus.MATCHED
    assert catalog.search("Old Title").outcome.decision.status is MatchDecisionStatus.NOT_FOUND
    reloaded = store.load(
        expected_identity="server:user",
        expected_types=["Movie"],
    )
    assert reloaded is not None
    assert reloaded.snapshot.items[0]["Name"] == "New Title"


def test_failed_refresh_keeps_previous_working_index(tmp_path: Path) -> None:
    store = CatalogCacheStore(tmp_path / "catalog.json")
    store.write(
        CatalogCacheDocument(
            identity="server:user",
            created_at=1000.0,
            snapshot=movie_snapshot("Stable Title"),
        )
    )

    async def loader() -> CatalogSnapshot:
        raise ConnectionError("Jellyfin offline")

    catalog = CatalogManager(
        snapshot_loader=loader,
        requested_types=["Movie"],
        cache_identity="server:user",
        cache_store=store,
    )
    assert run(catalog.async_load_cache()) is True

    with pytest.raises(CatalogRefreshError, match="refresh failed"):
        run(catalog.async_refresh())

    result = catalog.search("Stable Title")
    assert result.outcome.decision.status is MatchDecisionStatus.MATCHED
    assert result.diagnostics.source is CatalogDataSource.CACHE
    assert "Jellyfin offline" in (result.diagnostics.last_error or "")


def test_cache_write_failure_keeps_previous_index(tmp_path: Path) -> None:
    store = CatalogCacheStore(tmp_path / "catalog.json")
    store.write(
        CatalogCacheDocument(
            identity="server:user",
            created_at=1000.0,
            snapshot=movie_snapshot("Stable Title"),
        )
    )

    async def loader() -> CatalogSnapshot:
        return movie_snapshot("Uncommitted Title")

    catalog = CatalogManager(
        snapshot_loader=loader,
        requested_types=["Movie"],
        cache_identity="server:user",
        cache_store=store,
    )
    assert run(catalog.async_load_cache()) is True

    class FailingStore:
        path = store.path

        def load(self, **kwargs: Any) -> CatalogCacheDocument | None:
            return store.load(**kwargs)

        def write(self, document: CatalogCacheDocument) -> None:
            raise OSError("disk full")

    catalog._cache_store = FailingStore()  # test-only injected storage failure

    with pytest.raises(CatalogRefreshError, match="refresh failed"):
        run(catalog.async_refresh())

    assert catalog.search("Stable Title").outcome.decision.status is MatchDecisionStatus.MATCHED
    assert catalog.search("Uncommitted Title").outcome.decision.status is MatchDecisionStatus.NOT_FOUND


def test_truncated_refresh_is_rejected_and_not_cached(tmp_path: Path) -> None:
    truncated = movie_snapshot()
    truncated = CatalogSnapshot(
        requested_types=truncated.requested_types,
        items=truncated.items,
        pages=truncated.pages,
        raw_item_count=truncated.raw_item_count,
        duplicate_item_count=0,
        missing_id_count=0,
        server_overflow_item_count=0,
        stop_reason=CatalogLoadStopReason.MAX_ITEMS_REACHED,
    )

    async def loader() -> CatalogSnapshot:
        return truncated

    catalog = manager(tmp_path, loader)

    with pytest.raises(CatalogRefreshError, match="truncated"):
        run(catalog.async_refresh())
    assert not (tmp_path / "catalog.json").exists()
    assert catalog.diagnostics().available is False


def test_concurrent_refresh_calls_share_one_loader_execution(tmp_path: Path) -> None:
    calls = 0
    gate = asyncio.Event()

    async def loader() -> CatalogSnapshot:
        nonlocal calls
        calls += 1
        await gate.wait()
        return movie_snapshot()

    async def scenario() -> tuple[Any, Any]:
        catalog = manager(tmp_path, loader)
        first = asyncio.create_task(catalog.async_refresh())
        second = asyncio.create_task(catalog.async_refresh())
        await asyncio.sleep(0)
        gate.set()
        return await asyncio.gather(first, second)

    first, second = run(scenario())

    assert calls == 1
    assert first.indexed_record_count == 1
    assert second.indexed_record_count == 1


def test_timing_diagnostics_are_recorded(tmp_path: Path) -> None:
    async def loader() -> CatalogSnapshot:
        return movie_snapshot()

    # Each operation consumes pairs of monotonic readings. Exact durations are
    # less important than proving they are exposed and non-negative.
    monotonic = StepClock([0.0, 0.01, 0.02, 0.04, 0.05, 0.09, 0.10, 0.11])
    catalog = manager(tmp_path, loader, monotonic=monotonic)

    refreshed = run(catalog.async_refresh())
    searched = catalog.search("Bubba ho tep")

    assert refreshed.last_index_build_duration_ms == pytest.approx(10.0)
    assert refreshed.last_cache_write_duration_ms == pytest.approx(10.0)
    assert refreshed.last_refresh_duration_ms == pytest.approx(90.0)
    assert searched.search_duration_ms == pytest.approx(10.0)


def test_searches_keep_using_old_index_while_refresh_is_in_progress(
    tmp_path: Path,
) -> None:
    store = CatalogCacheStore(tmp_path / "catalog.json")
    store.write(
        CatalogCacheDocument(
            identity="server:user",
            created_at=1000.0,
            snapshot=movie_snapshot("Stable Title"),
        )
    )

    async def scenario() -> tuple[Any, Any]:
        gate = asyncio.Event()

        async def loader() -> CatalogSnapshot:
            await gate.wait()
            return movie_snapshot("New Title")

        catalog = CatalogManager(
            snapshot_loader=loader,
            requested_types=["Movie"],
            cache_identity="server:user",
            cache_store=store,
        )
        assert await catalog.async_load_cache() is True
        refresh = asyncio.create_task(catalog.async_refresh())
        for _ in range(5):
            await asyncio.sleep(0)
            if catalog.diagnostics().refresh_in_progress:
                break
        old_result = catalog.search("Stable Title")
        assert old_result.diagnostics.refresh_in_progress is True
        gate.set()
        await refresh
        new_result = catalog.search("New Title")
        return old_result, new_result

    old_result, new_result = run(scenario())

    assert old_result.outcome.decision.status is MatchDecisionStatus.MATCHED
    assert new_result.outcome.decision.status is MatchDecisionStatus.MATCHED
