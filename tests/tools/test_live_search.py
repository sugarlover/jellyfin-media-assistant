from __future__ import annotations

from pathlib import Path

import pytest

from tools.live_search import load_env_file, parse_bool, required_setting
from tools.jellyfin_readonly import JellyfinLiveConfigurationError


def test_env_loader_supports_comments_quotes_and_export(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
# local settings
export JELLYFIN_URL='http://server:8096'
JELLYFIN_API_KEY=\"abc123\"
JELLYFIN_USER_ID=user-1
""".strip(),
        encoding="utf-8",
    )

    values = load_env_file(env_file)

    assert values == {
        "JELLYFIN_URL": "http://server:8096",
        "JELLYFIN_API_KEY": "abc123",
        "JELLYFIN_USER_ID": "user-1",
    }


def test_env_loader_rejects_invalid_line(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NOT_AN_ASSIGNMENT", encoding="utf-8")

    with pytest.raises(JellyfinLiveConfigurationError, match="expected KEY=VALUE"):
        load_env_file(env_file)


@pytest.mark.parametrize("value", ["true", "1", "YES", "on"])
def test_parse_bool_true(value: str) -> None:
    assert parse_bool(value, default=False) is True


@pytest.mark.parametrize("value", ["false", "0", "NO", "off"])
def test_parse_bool_false(value: str) -> None:
    assert parse_bool(value, default=True) is False


def test_required_setting_rejects_missing_value() -> None:
    with pytest.raises(JellyfinLiveConfigurationError, match="JELLYFIN_URL"):
        required_setting({}, "JELLYFIN_URL")


def test_parser_accepts_local_catalog_mode() -> None:
    from tools.live_search import build_parser

    args = build_parser().parse_args(
        [
            "Bubba ho tep",
            "--media-type",
            "Movie",
            "--catalog",
            "--catalog-page-size",
            "250",
        ]
    )

    assert args.catalog is True
    assert args.catalog_page_size == 250
    assert args.catalog_max_items == 0
    assert args.refresh_catalog is False
    assert args.no_catalog_cache is False


def test_local_catalog_report_contains_snapshot_and_shortlist_diagnostics() -> None:
    from custom_components.jellyfin_assist.matching import MediaSearchContext
    from custom_components.jellyfin_assist.search import (
        CatalogIndex,
        CatalogLoadStopReason,
        CatalogSnapshot,
    )
    from tools.live_search import local_outcome_dict

    snapshot = CatalogSnapshot(
        requested_types=("Movie",),
        items=(
            {
                "Id": "bubba",
                "Name": "Bubba Ho-tep",
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
    index = CatalogIndex.build(snapshot.items)
    outcome = index.search(
        "Bubba ho tep",
        context=MediaSearchContext(media_type="Movie"),
    )

    report = local_outcome_dict(
        outcome,
        snapshot=snapshot,
        index=index,
        server={"ServerName": "Test", "Version": "10.11"},
    )

    assert report["mode"] == "local_catalog"
    assert report["catalog"]["indexed_records"] == 1
    assert report["decision"]["selected"]["title"] == "Bubba Ho-tep"
    assert report["decision"]["selected"]["shortlisted_by"] == [
        "deterministic_variant"
    ]



def test_local_catalog_report_exposes_logical_provider_group_ids() -> None:
    from custom_components.jellyfin_assist.matching import MediaSearchContext
    from custom_components.jellyfin_assist.search import (
        CatalogIndex,
        CatalogLoadStopReason,
        CatalogSnapshot,
    )
    from tools.live_search import local_outcome_dict

    provider_id = "0743b15a-3c32-48c8-ad58-cb325350befa"
    items = (
        {
            "Id": "blink-lower",
            "Name": "blink-182",
            "Type": "MusicArtist",
            "ProviderIds": {"MusicBrainzArtist": provider_id},
        },
        {
            "Id": "blink-upper",
            "Name": "Blink-182",
            "Type": "MusicArtist",
            "ProviderIds": {"MusicBrainzArtist": provider_id},
        },
    )
    snapshot = CatalogSnapshot(
        requested_types=("MusicArtist",),
        items=items,
        pages=(),
        raw_item_count=2,
        duplicate_item_count=0,
        missing_id_count=0,
        server_overflow_item_count=0,
        stop_reason=CatalogLoadStopReason.COMPLETE,
    )
    index = CatalogIndex.build(snapshot.items)
    outcome = index.search(
        "blink one eighty two",
        context=MediaSearchContext(media_type="MusicArtist"),
    )

    report = local_outcome_dict(
        outcome,
        snapshot=snapshot,
        index=index,
        server={"ServerName": "Test", "Version": "10.11"},
    )

    assert report["catalog"]["indexed_records"] == 1
    assert report["catalog"]["logical_groups"] == 1
    assert report["catalog"]["grouped_physical_items"] == 1
    selected = report["decision"]["selected"]
    assert selected["physical_ids"] == ["blink-lower", "blink-upper"]
    assert selected["provider_ids"] == {
        "musicbrainzartist": provider_id,
    }


def test_parser_accepts_catalog_cache_controls(tmp_path: Path) -> None:
    from tools.live_search import build_parser

    args = build_parser().parse_args(
        [
            "Runaround",
            "--media-type",
            "Audio",
            "--catalog",
            "--refresh-catalog",
            "--catalog-cache-dir",
            str(tmp_path),
        ]
    )

    assert args.refresh_catalog is True
    assert args.catalog_cache_dir == tmp_path


def test_local_catalog_report_exposes_manager_cache_and_timing(tmp_path: Path) -> None:
    from custom_components.jellyfin_assist.matching import MediaSearchContext
    from custom_components.jellyfin_assist.search import (
        CatalogDataSource,
        CatalogIndex,
        CatalogLoadStopReason,
        CatalogManagerDiagnostics,
        CatalogSnapshot,
    )
    from tools.live_search import local_outcome_dict

    snapshot = CatalogSnapshot(
        requested_types=("Movie",),
        items=({"Id": "bubba", "Name": "Bubba Ho-tep", "Type": "Movie"},),
        pages=(),
        raw_item_count=1,
        duplicate_item_count=0,
        missing_id_count=0,
        server_overflow_item_count=0,
        stop_reason=CatalogLoadStopReason.COMPLETE,
    )
    index = CatalogIndex.build(snapshot.items)
    outcome = index.search(
        "Bubba ho tep",
        context=MediaSearchContext(media_type="Movie"),
    )
    diagnostics = CatalogManagerDiagnostics(
        available=True,
        source=CatalogDataSource.CACHE,
        refresh_in_progress=False,
        requested_types=("Movie",),
        cache_path=str(tmp_path / "catalog.json"),
        catalog_created_at=1000.0,
        cache_age_seconds=50.0,
        page_count=1,
        snapshot_item_count=1,
        raw_item_count=1,
        indexed_record_count=1,
        logical_group_count=0,
        grouped_physical_item_count=0,
        index_issue_count=0,
        duplicate_item_count=0,
        last_cache_load_duration_ms=12.0,
        last_refresh_duration_ms=None,
        last_index_build_duration_ms=5.0,
        last_cache_write_duration_ms=None,
        last_search_duration_ms=0.4,
        search_count=1,
        last_error=None,
    )

    report = local_outcome_dict(
        outcome,
        snapshot=snapshot,
        index=index,
        server={"ServerName": "Test", "Version": "10.11"},
        manager_diagnostics=diagnostics,
    )

    assert report["manager"]["source"] == "cache"
    assert report["manager"]["cache_age_seconds"] == 50.0
    assert report["manager"]["last_search_duration_ms"] == 0.4
