"""Tests for the versioned metadata-only catalog disk cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.jellyfin_assist.search import (
    CATALOG_CACHE_SCHEMA_VERSION,
    CatalogCacheDocument,
    CatalogCacheStore,
    CatalogCacheValidationError,
    CatalogLoadStopReason,
    CatalogLoadedPage,
    CatalogPageRequest,
    CatalogSnapshot,
    catalog_cache_filename,
)


def snapshot() -> CatalogSnapshot:
    request = CatalogPageRequest(item_types=("Movie",), start_index=0, limit=500)
    return CatalogSnapshot(
        requested_types=("Movie",),
        items=(
            {
                "Id": "movie-1",
                "Name": "Bubba Ho-tep",
                "Type": "Movie",
                "ProductionYear": 2002,
                "ProviderIds": {"Tmdb": "9707"},
                "Path": "/private/media/Bubba Ho-tep.mkv",
                "ApiKey": "must-not-be-cached",
                "Overview": "Not required by search",
            },
        ),
        pages=(
            CatalogLoadedPage(
                request=request,
                returned_count=1,
                accepted_count=1,
                total_record_count=1,
            ),
        ),
        raw_item_count=1,
        duplicate_item_count=0,
        missing_id_count=0,
        server_overflow_item_count=0,
        stop_reason=CatalogLoadStopReason.COMPLETE,
    )


def test_cache_filename_is_stable_and_type_specific() -> None:
    assert catalog_cache_filename(["Movie"]) == "catalog-movie.json"
    assert catalog_cache_filename(["Audio", "MusicArtist"]) == (
        "catalog-audio-musicartist.json"
    )


def test_cache_round_trip_preserves_search_metadata_and_page_diagnostics(
    tmp_path: Path,
) -> None:
    store = CatalogCacheStore(tmp_path / "catalog.json")
    document = CatalogCacheDocument(
        identity="server:user",
        created_at=1234.5,
        snapshot=snapshot(),
    )

    store.write(document)
    loaded = store.load(
        expected_identity="server:user",
        expected_types=["Movie"],
    )

    assert loaded is not None
    assert loaded.created_at == 1234.5
    assert loaded.snapshot.requested_types == ("Movie",)
    assert loaded.snapshot.items == (
        {
            "Id": "movie-1",
            "Name": "Bubba Ho-tep",
            "Type": "Movie",
            "ProductionYear": 2002,
            "ProviderIds": {"Tmdb": "9707"},
        },
    )
    assert loaded.snapshot.pages[0].returned_count == 1
    assert loaded.snapshot.pages[0].request.limit == 500


def test_cache_never_persists_paths_or_credentials(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    CatalogCacheStore(path).write(
        CatalogCacheDocument(
            identity="server:user",
            created_at=1234.5,
            snapshot=snapshot(),
        )
    )

    text = path.read_text(encoding="utf-8")

    assert "must-not-be-cached" not in text
    assert "/private/media" not in text
    assert "Overview" not in text
    assert "Bubba Ho-tep" in text


def test_cache_write_is_complete_and_leaves_no_temporary_files(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "catalog.json"
    CatalogCacheStore(path).write(
        CatalogCacheDocument(
            identity="server:user",
            created_at=1234.5,
            snapshot=snapshot(),
        )
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == CATALOG_CACHE_SCHEMA_VERSION
    assert list(path.parent.glob("*.tmp")) == []
    assert list(path.parent.glob(".*.tmp")) == []


def test_absent_cache_returns_none(tmp_path: Path) -> None:
    store = CatalogCacheStore(tmp_path / "missing.json")

    assert store.load(
        expected_identity="server:user",
        expected_types=["Movie"],
    ) is None


def test_cache_rejects_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CatalogCacheValidationError, match="could not be read"):
        CatalogCacheStore(path).load(
            expected_identity="server:user",
            expected_types=["Movie"],
        )


def test_cache_rejects_wrong_identity_or_media_types(tmp_path: Path) -> None:
    store = CatalogCacheStore(tmp_path / "catalog.json")
    store.write(
        CatalogCacheDocument(
            identity="server:user",
            created_at=1234.5,
            snapshot=snapshot(),
        )
    )

    with pytest.raises(CatalogCacheValidationError, match="identity"):
        store.load(expected_identity="other:user", expected_types=["Movie"])
    with pytest.raises(CatalogCacheValidationError, match="media types"):
        store.load(expected_identity="server:user", expected_types=["Audio"])


def test_failed_atomic_replace_preserves_previous_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.jellyfin_assist.search import catalog_cache as cache_module
    from custom_components.jellyfin_assist.search import CatalogCacheWriteError

    path = tmp_path / "catalog.json"
    store = CatalogCacheStore(path)
    store.write(
        CatalogCacheDocument(
            identity="server:user",
            created_at=1000.0,
            snapshot=snapshot(),
        )
    )
    original = path.read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(cache_module.os, "replace", fail_replace)

    with pytest.raises(CatalogCacheWriteError, match="could not be written"):
        store.write(
            CatalogCacheDocument(
                identity="server:user",
                created_at=2000.0,
                snapshot=snapshot(),
            )
        )

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".*.tmp")) == []
