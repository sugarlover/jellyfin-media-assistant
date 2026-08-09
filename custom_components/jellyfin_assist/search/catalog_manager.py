"""Long-lived catalog lifecycle, cache, refresh, and search management.

This Home-Assistant-independent manager is designed to become the integration's
runtime boundary. It restores a metadata-only disk cache, keeps one immutable
in-memory index available for fast searches, refreshes through an injected
read-only snapshot loader, and swaps state only after a complete refresh and
atomic cache write succeed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
import time
from typing import Any

from ..matching.context import MediaSearchContext
from .catalog_cache import (
    CatalogCacheDocument,
    CatalogCacheError,
    CatalogCacheStore,
    sanitize_catalog_snapshot,
)
from .catalog_index import CatalogIndex, LocalCatalogSearchOutcome
from .catalog_loader import CatalogSnapshot, normalize_catalog_media_types


CatalogSnapshotLoader = Callable[[], Awaitable[CatalogSnapshot]]
Clock = Callable[[], float]


class CatalogDataSource(StrEnum):
    """Source of the currently active in-memory catalog."""

    NONE = "none"
    CACHE = "cache"
    REFRESH = "refresh"


class CatalogManagerError(RuntimeError):
    """Base class for catalog-manager failures."""


class CatalogUnavailableError(CatalogManagerError):
    """Raised when search is attempted before any index is available."""


class CatalogRefreshError(CatalogManagerError):
    """Raised when a refresh cannot safely replace the active catalog."""


@dataclass(frozen=True, slots=True)
class CatalogManagerDiagnostics:
    """Snapshot of catalog availability, provenance, counts, and timing."""

    available: bool
    source: CatalogDataSource
    refresh_in_progress: bool
    requested_types: tuple[str, ...]
    cache_path: str | None
    catalog_created_at: float | None
    cache_age_seconds: float | None
    page_count: int
    snapshot_item_count: int
    raw_item_count: int
    indexed_record_count: int
    logical_group_count: int
    grouped_physical_item_count: int
    index_issue_count: int
    duplicate_item_count: int
    last_cache_load_duration_ms: float | None
    last_refresh_duration_ms: float | None
    last_index_build_duration_ms: float | None
    last_cache_write_duration_ms: float | None
    last_search_duration_ms: float | None
    search_count: int
    last_error: str | None


@dataclass(frozen=True, slots=True)
class ManagedCatalogSearchOutcome:
    """One local search result with manager timing and state diagnostics."""

    outcome: LocalCatalogSearchOutcome
    search_duration_ms: float
    diagnostics: CatalogManagerDiagnostics


class CatalogManager:
    """Own one reusable immutable catalog index and its persistent cache."""

    def __init__(
        self,
        *,
        snapshot_loader: CatalogSnapshotLoader,
        requested_types: Sequence[str] | None,
        cache_identity: str,
        cache_store: CatalogCacheStore | None,
        clock: Clock = time.time,
        monotonic: Clock = time.perf_counter,
        allow_truncated_snapshots: bool = False,
    ) -> None:
        if not callable(snapshot_loader):
            raise TypeError("snapshot_loader must be callable")
        identity = cache_identity.strip()
        if not identity:
            raise ValueError("cache_identity must not be empty")
        if not callable(clock) or not callable(monotonic):
            raise TypeError("clock and monotonic must be callable")

        self._snapshot_loader = snapshot_loader
        self._requested_types = normalize_catalog_media_types(requested_types)
        self._cache_identity = identity
        self._cache_store = cache_store
        self._clock = clock
        self._monotonic = monotonic
        self._allow_truncated_snapshots = allow_truncated_snapshots

        self._snapshot: CatalogSnapshot | None = None
        self._index: CatalogIndex | None = None
        self._source = CatalogDataSource.NONE
        self._catalog_created_at: float | None = None
        self._refresh_in_progress = False
        self._last_error: str | None = None

        self._last_cache_load_duration_ms: float | None = None
        self._last_refresh_duration_ms: float | None = None
        self._last_index_build_duration_ms: float | None = None
        self._last_cache_write_duration_ms: float | None = None
        self._last_search_duration_ms: float | None = None
        self._search_count = 0

        self._refresh_task: asyncio.Task[CatalogManagerDiagnostics] | None = None
        self._refresh_task_lock = asyncio.Lock()

    @property
    def index(self) -> CatalogIndex | None:
        """Return the active immutable index, if available."""

        return self._index

    @property
    def snapshot(self) -> CatalogSnapshot | None:
        """Return the active metadata snapshot, if available."""

        return self._snapshot

    def diagnostics(self) -> CatalogManagerDiagnostics:
        """Return current non-secret manager diagnostics."""

        snapshot = self._snapshot
        index = self._index
        created_at = self._catalog_created_at
        age = None
        if created_at is not None:
            age = max(0.0, self._clock() - created_at)
        return CatalogManagerDiagnostics(
            available=index is not None,
            source=self._source,
            refresh_in_progress=self._refresh_in_progress,
            requested_types=self._requested_types,
            cache_path=str(self._cache_store.path) if self._cache_store else None,
            catalog_created_at=created_at,
            cache_age_seconds=age,
            page_count=len(snapshot.pages) if snapshot else 0,
            snapshot_item_count=len(snapshot.items) if snapshot else 0,
            raw_item_count=snapshot.raw_item_count if snapshot else 0,
            indexed_record_count=len(index.records) if index else 0,
            logical_group_count=index.logical_group_count if index else 0,
            grouped_physical_item_count=(
                index.grouped_physical_item_count if index else 0
            ),
            index_issue_count=len(index.issues) if index else 0,
            duplicate_item_count=snapshot.duplicate_item_count if snapshot else 0,
            last_cache_load_duration_ms=self._last_cache_load_duration_ms,
            last_refresh_duration_ms=self._last_refresh_duration_ms,
            last_index_build_duration_ms=self._last_index_build_duration_ms,
            last_cache_write_duration_ms=self._last_cache_write_duration_ms,
            last_search_duration_ms=self._last_search_duration_ms,
            search_count=self._search_count,
            last_error=self._last_error,
        )

    def _validate_snapshot(self, snapshot: Any) -> CatalogSnapshot:
        if not isinstance(snapshot, CatalogSnapshot):
            raise CatalogRefreshError("snapshot loader must return CatalogSnapshot")
        if snapshot.requested_types != self._requested_types:
            raise CatalogRefreshError("refreshed catalog media types do not match")
        if snapshot.truncated and not self._allow_truncated_snapshots:
            raise CatalogRefreshError("truncated catalog snapshots are not cacheable")
        return sanitize_catalog_snapshot(snapshot)

    def _build_index(self, snapshot: CatalogSnapshot) -> CatalogIndex:
        started = self._monotonic()
        index = CatalogIndex.build(snapshot.items)
        self._last_index_build_duration_ms = (
            self._monotonic() - started
        ) * 1000.0
        if snapshot.items and not index.records:
            raise CatalogRefreshError("catalog snapshot produced no searchable records")
        return index

    async def async_load_cache(self) -> bool:
        """Restore the active index from disk without contacting Jellyfin."""

        if self._cache_store is None:
            return False
        started = self._monotonic()
        try:
            document = await asyncio.to_thread(
                self._cache_store.load,
                expected_identity=self._cache_identity,
                expected_types=self._requested_types,
            )
            if document is None:
                self._last_error = None
                return False
            snapshot = self._validate_snapshot(document.snapshot)
            index = self._build_index(snapshot)
        except (CatalogCacheError, CatalogRefreshError, OSError, ValueError) as err:
            self._last_error = f"{type(err).__name__}: {err}"
            return False
        finally:
            self._last_cache_load_duration_ms = (
                self._monotonic() - started
            ) * 1000.0

        self._snapshot = snapshot
        self._index = index
        self._source = CatalogDataSource.CACHE
        self._catalog_created_at = document.created_at
        self._last_error = None
        return True

    async def async_initialize(
        self,
        *,
        refresh_if_missing: bool = True,
    ) -> CatalogManagerDiagnostics:
        """Load cache first and optionally refresh only when no cache exists."""

        loaded = await self.async_load_cache()
        if not loaded and refresh_if_missing:
            return await self.async_refresh()
        return self.diagnostics()

    async def async_refresh(self) -> CatalogManagerDiagnostics:
        """Coalesce concurrent requests into one safe catalog refresh."""

        async with self._refresh_task_lock:
            task = self._refresh_task
            if task is None or task.done():
                task = asyncio.create_task(self._async_refresh_once())
                self._refresh_task = task

        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._refresh_task_lock:
                    if self._refresh_task is task:
                        self._refresh_task = None

    async def _async_refresh_once(self) -> CatalogManagerDiagnostics:
        started = self._monotonic()
        self._refresh_in_progress = True
        self._last_cache_write_duration_ms = None
        try:
            raw_snapshot = await self._snapshot_loader()
            snapshot = self._validate_snapshot(raw_snapshot)
            index = self._build_index(snapshot)
            created_at = self._clock()

            if self._cache_store is not None:
                document = CatalogCacheDocument(
                    identity=self._cache_identity,
                    created_at=created_at,
                    snapshot=snapshot,
                )
                write_started = self._monotonic()
                await asyncio.to_thread(self._cache_store.write, document)
                self._last_cache_write_duration_ms = (
                    self._monotonic() - write_started
                ) * 1000.0

            # Swap only after retrieval, validation, index construction, and the
            # atomic cache write all succeed. Existing searches can continue to
            # use the old immutable index throughout the refresh.
            self._snapshot = snapshot
            self._index = index
            self._source = CatalogDataSource.REFRESH
            self._catalog_created_at = created_at
            self._last_error = None
        except Exception as err:
            self._last_error = f"{type(err).__name__}: {err}"
            if isinstance(err, CatalogRefreshError):
                raise
            raise CatalogRefreshError("catalog refresh failed") from err
        finally:
            self._refresh_in_progress = False
            self._last_refresh_duration_ms = (
                self._monotonic() - started
            ) * 1000.0
        return self.diagnostics()

    def search(
        self,
        query: str,
        *,
        context: MediaSearchContext | None = None,
        max_shortlist: int = 200,
        small_type_scan_limit: int = 250,
    ) -> ManagedCatalogSearchOutcome:
        """Search the reusable in-memory index and record execution timing."""

        index = self._index
        if index is None:
            raise CatalogUnavailableError("catalog index is not available")
        started = self._monotonic()
        outcome = index.search(
            query,
            context=context,
            max_shortlist=max_shortlist,
            small_type_scan_limit=small_type_scan_limit,
        )
        duration = (self._monotonic() - started) * 1000.0
        self._last_search_duration_ms = duration
        self._search_count += 1
        return ManagedCatalogSearchOutcome(
            outcome=outcome,
            search_duration_ms=duration,
            diagnostics=self.diagnostics(),
        )
