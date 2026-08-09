"""Tests for the stable JSON-safe Home Assistant search action response."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.jellyfin_assist.matching import MediaSearchContext
from custom_components.jellyfin_assist.search import (
    CatalogCacheStore,
    CatalogLoadStopReason,
    CatalogManager,
    CatalogSnapshot,
    SearchResponseOptions,
    serialize_catalog_record,
    serialize_search_action_response,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def snapshot(items: list[dict[str, Any]], media_type: str = "Movie") -> CatalogSnapshot:
    return CatalogSnapshot(
        requested_types=(media_type,),
        items=tuple(items),
        pages=(),
        raw_item_count=len(items),
        duplicate_item_count=0,
        missing_id_count=0,
        server_overflow_item_count=0,
        stop_reason=CatalogLoadStopReason.COMPLETE,
    )


def build_manager(
    tmp_path: Path,
    items: list[dict[str, Any]],
    *,
    media_type: str = "Movie",
) -> CatalogManager:
    async def loader() -> CatalogSnapshot:
        return snapshot(items, media_type)

    manager = CatalogManager(
        snapshot_loader=loader,
        requested_types=[media_type],
        cache_identity="server:user",
        cache_store=CatalogCacheStore(tmp_path / "catalog.json"),
        clock=lambda: 2000.0,
    )
    run(manager.async_refresh())
    return manager


def movie(item_id: str, name: str, year: int = 2002) -> dict[str, Any]:
    return {
        "Id": item_id,
        "Name": name,
        "Type": "Movie",
        "ProductionYear": year,
        "RunTimeTicks": 5_400 * 10_000_000,
        "ProviderIds": {"Imdb": f"tt-{item_id}"},
    }


def song(item_id: str, name: str, artist: str) -> dict[str, Any]:
    return {
        "Id": item_id,
        "Name": name,
        "Type": "Audio",
        "Artists": [artist],
        "AlbumArtist": artist,
        "Album": "Album",
        "ProductionYear": 1999,
    }


def test_confident_match_returns_exactly_one_legacy_item(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, [movie("bubba", "Bubba Ho-tep")])
    managed = manager.search(
        "Bubba ho tep",
        context=MediaSearchContext(media_type="Movie"),
    )

    response = serialize_search_action_response(managed)

    assert response["schema_version"] == 1
    assert response["decision"]["status"] == "matched"
    assert response["decision"]["automatic_selection_allowed"] is True
    assert len(response["items"]) == 1
    assert response["items"][0]["id"] == "bubba"
    assert response["item"] == response["selected"] == response["items"][0]
    assert response["jellyfin_id"] == "bubba"
    assert response["match"]["method"] == "punctuation_spacing"
    assert response["alternatives"] == []


def test_ambiguous_result_returns_ranked_legacy_items(tmp_path: Path) -> None:
    manager = build_manager(
        tmp_path,
        [song("metallica", "One", "Metallica"), song("u2", "One", "U2")],
        media_type="Audio",
    )
    managed = manager.search(
        "One",
        context=MediaSearchContext(media_type="Audio"),
    )

    response = serialize_search_action_response(managed)

    assert response["decision"]["status"] == "ambiguous"
    assert response["decision"]["selection_required"] is True
    assert response["item"] is None
    assert response["jellyfin_id"] is None
    assert [item["id"] for item in response["items"]] == ["metallica", "u2"]
    assert [entry["rank"] for entry in response["alternatives"]] == [1, 2]


def test_not_found_preserves_empty_items_contract(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, [movie("bubba", "Bubba Ho-tep")])
    managed = manager.search(
        "Completely Different",
        context=MediaSearchContext(media_type="Movie"),
    )

    response = serialize_search_action_response(managed)

    assert response["decision"]["status"] == "not_found"
    assert response["items"] == []
    assert response["item"] is None
    assert response["selected"] is None
    assert response["match"] is None


def test_context_disambiguation_keeps_single_item_contract(tmp_path: Path) -> None:
    manager = build_manager(
        tmp_path,
        [song("metallica", "One", "Metallica"), song("u2", "One", "U2")],
        media_type="Audio",
    )
    managed = manager.search(
        "One",
        context=MediaSearchContext(media_type="Audio", artist="Metallica"),
    )

    response = serialize_search_action_response(managed)

    assert response["decision"]["status"] == "matched"
    assert [item["id"] for item in response["items"]] == ["metallica"]
    assert response["match"]["context_score"] > 0
    fields = {entry["field"]: entry for entry in response["diagnostics"]["ranked_candidates"][0]["context_evidence"]}
    assert fields["artist"]["relation"] == "match"


def test_logical_artist_group_retains_every_physical_id(tmp_path: Path) -> None:
    musicbrainz = "0743b15a-3c32-48c8-ad58-cb325350befa"
    items = [
        {
            "Id": "artist-a",
            "Name": "Blink-182",
            "Type": "MusicArtist",
            "ProviderIds": {"MusicBrainzArtist": musicbrainz},
        },
        {
            "Id": "artist-b",
            "Name": "blink-182",
            "Type": "MusicArtist",
            "ProviderIds": {"MusicBrainzArtist": musicbrainz},
        },
    ]
    manager = build_manager(tmp_path, items, media_type="MusicArtist")
    managed = manager.search(
        "blink one eighty two",
        context=MediaSearchContext(media_type="MusicArtist"),
    )

    response = serialize_search_action_response(managed)
    item = response["items"][0]

    assert response["decision"]["status"] == "matched"
    assert item["physical_ids"] == ["artist-a", "artist-b"]
    assert item["is_logical_group"] is True
    assert item["provider_ids"]["musicbrainzartist"] == musicbrainz
    assert response["match"]["matched_alias"] == "blink one eighty two"
    attempted_values = {
        variant["value"] for variant in response["diagnostics"]["attempted_variants"]
    }
    assert "blink 83" not in attempted_values
    assert "blink83" not in attempted_values


def test_catalog_record_serialization_covers_resolver_fields(tmp_path: Path) -> None:
    manager = build_manager(
        tmp_path,
        [
            {
                "Id": "episode",
                "Name": "Pilot",
                "Type": "Episode",
                "SeriesName": "Example Show",
                "SeriesId": "series",
                "ParentIndexNumber": 1,
                "IndexNumber": 2,
                "ProductionYear": 2020,
                "RunTimeTicks": 2_700 * 10_000_000,
            }
        ],
        media_type="Episode",
    )
    record = manager.index.records[0]  # type: ignore[union-attr]

    item = serialize_catalog_record(record)

    assert item["id"] == "episode"
    assert item["series_name"] == "Example Show"
    assert item["series_id"] == "series"
    assert item["season_name"] == "Season 1"
    assert item["season_number"] == 1
    assert item["episode_number"] == 2
    assert item["runtime_minutes"] == 45


def test_attempted_variants_are_labeled_and_include_original(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, [movie("warrior", "The 13th Warrior", 1999)])
    response = serialize_search_action_response(
        manager.search(
            "the thirteenth warrior",
            context=MediaSearchContext(media_type="Movie"),
        )
    )

    variants = response["diagnostics"]["attempted_variants"]
    assert variants[0]["value"] == "the thirteenth warrior"
    assert "original" in variants[0]["methods"]
    assert any(entry["value"] == "the 13th warrior" for entry in variants)


def test_catalog_and_timing_diagnostics_are_additive(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, [movie("bubba", "Bubba Ho-tep")])
    response = serialize_search_action_response(manager.search("Bubba ho tep"))

    assert response["catalog"]["available"] is True
    assert response["catalog"]["source"] == "refresh"
    assert response["catalog"]["indexed_record_count"] == 1
    assert response["catalog"]["timing_ms"]["search"] is not None
    assert response["diagnostics"]["search_duration_ms"] is not None


def test_output_is_plain_json_safe_data(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, [movie("bubba", "Bubba Ho-tep")])
    response = serialize_search_action_response(manager.search("Bubba ho tep"))

    encoded = json.dumps(response, sort_keys=True)

    assert "Bubba Ho-tep" in encoded
    assert "CatalogDataSource" not in encoded


def test_item_limit_bounds_ambiguous_resolver_items(tmp_path: Path) -> None:
    items = [song(f"song-{index}", "One", f"Artist {index}") for index in range(6)]
    manager = build_manager(tmp_path, items, media_type="Audio")
    managed = manager.search("One", context=MediaSearchContext(media_type="Audio"))

    response = serialize_search_action_response(
        managed,
        options=SearchResponseOptions(item_limit=3, diagnostic_limit=4),
    )

    assert len(response["items"]) == 3
    assert len(response["alternatives"]) == 3
    assert len(response["diagnostics"]["ranked_candidates"]) == 4


@pytest.mark.parametrize("field", ["item_limit", "diagnostic_limit"])
def test_response_options_require_positive_limits(field: str) -> None:
    kwargs = {"item_limit": 5, "diagnostic_limit": 10}
    kwargs[field] = 0

    with pytest.raises(ValueError, match="positive"):
        SearchResponseOptions(**kwargs)


def test_serializer_rejects_wrong_input_type() -> None:
    with pytest.raises(TypeError, match="ManagedCatalogSearchOutcome"):
        serialize_search_action_response(object())  # type: ignore[arg-type]


def test_partial_movie_title_returns_five_ranked_selection_items(tmp_path: Path) -> None:
    titles = [
        "Planet Terror",
        "Forbidden Planet",
        "Red Planet",
        "Treasure Planet",
        "Planet 51",
        "Alien Planet",
    ]
    manager = build_manager(
        tmp_path,
        [movie(f"planet-{index}", title) for index, title in enumerate(titles)],
    )

    response = serialize_search_action_response(
        manager.search(
            "planet",
            context=MediaSearchContext(media_type="Movie"),
        )
    )

    assert response["decision"]["status"] == "ambiguous"
    assert response["decision"]["selection_required"] is True
    assert response["decision"]["active_family"] == "deterministic"
    assert len(response["items"]) == 5
    assert {item["name"] for item in response["items"]}.issubset(set(titles))
    assert all(
        entry["match"]["method"] == "title_fragment"
        for entry in response["alternatives"]
    )
    assert response["diagnostics"]["shortlist_count"] == 6
    assert response["diagnostics"]["ranked_candidate_count"] == 6


def test_audio_spoken_title_collision_returns_both_tracks(tmp_path: Path) -> None:
    manager = build_manager(
        tmp_path,
        [
            {
                **song("matchbox", "3 AM", "Matchbox Twenty"),
                "Album": "Yourself Or Someone Like You",
                "ProductionYear": 1996,
            },
            {
                **song("nf", "3 A.M.", "NF"),
                "Album": "Perception",
                "ProductionYear": 2017,
            },
        ],
        media_type="Audio",
    )

    response = serialize_search_action_response(
        manager.search(
            "three am",
            context=MediaSearchContext(media_type="Audio"),
        )
    )

    assert response["decision"]["status"] == "ambiguous"
    assert response["decision"]["reason"] == "audio_spoken_title_collision"
    assert response["decision"]["selection_required"] is True
    assert [item["id"] for item in response["items"]] == ["matchbox", "nf"]


def test_audio_serialization_separates_disc_track_from_tv_fields(
    tmp_path: Path,
) -> None:
    manager = build_manager(
        tmp_path,
        [
            {
                **song("track", "Example Song", "Example Artist"),
                "ParentIndexNumber": 2,
                "IndexNumber": 7,
            }
        ],
        media_type="Audio",
    )
    record = manager.index.records[0]  # type: ignore[union-attr]

    item = serialize_catalog_record(record)

    assert item["index_number"] == 7
    assert item["track_number"] == 7
    assert item["disc_number"] == 2
    assert item["season_name"] == ""
    assert item["season_number"] is None
    assert item["episode_number"] is None


def test_partial_song_title_and_incomplete_artist_keep_single_item_contract(
    tmp_path: Path,
) -> None:
    manager = build_manager(
        tmp_path,
        [song("crash", "Crash Into Me", "Dave Matthews Band")],
        media_type="Audio",
    )
    managed = manager.search(
        "Crash",
        context=MediaSearchContext(media_type="Audio", artist="Dave Matthews"),
    )

    response = serialize_search_action_response(managed)

    assert response["decision"]["status"] == "matched"
    assert [item["id"] for item in response["items"]] == ["crash"]
    evidence = {
        entry["field"]: entry
        for entry in response["diagnostics"]["ranked_candidates"][0][
            "context_evidence"
        ]
    }
    assert evidence["artist"]["relation"] == "match"
    assert evidence["artist"]["method"] == "title_fragment"


def test_episode_title_and_series_errors_keep_single_item_contract(
    tmp_path: Path,
) -> None:
    manager = build_manager(
        tmp_path,
        [
            {
                "Id": "episode",
                "Name": "Where Is Everybody?",
                "Type": "Episode",
                "SeriesName": "The Twilight Zone",
                "SeriesId": "series",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
            }
        ],
        media_type="Episode",
    )
    managed = manager.search(
        "Where Is Everybdy?",
        context=MediaSearchContext(
            media_type="Episode",
            series="The Twlight Zone",
        ),
    )

    response = serialize_search_action_response(managed)

    assert response["decision"]["status"] == "matched"
    assert [item["id"] for item in response["items"]] == ["episode"]
    evidence = {
        entry["field"]: entry
        for entry in response["diagnostics"]["ranked_candidates"][0][
            "context_evidence"
        ]
    }
    assert evidence["series"]["relation"] == "match"
    assert evidence["series"]["method"] == "single_edit"
