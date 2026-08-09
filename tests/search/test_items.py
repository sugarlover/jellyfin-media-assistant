"""Tests for shared Jellyfin catalog-item conversion helpers."""

from __future__ import annotations

from custom_components.jellyfin_assist.search.items import (
    catalog_item_to_media_candidate,
    catalog_provider_ids,
    trusted_logical_group_key,
)


def test_provider_ids_normalize_raw_and_transformed_shapes() -> None:
    raw = {
        "ProviderIds": {
            "MusicBrainzArtist": "{0743B15A-3C32-48C8-AD58-CB325350BEFA}",
            "Empty": " ",
            "Ignored": 123,
        }
    }
    transformed = {
        "provider_ids": {
            "musicbrainz-artist": "0743b15a-3c32-48c8-ad58-cb325350befa"
        }
    }

    expected = (
        (
            "musicbrainzartist",
            "0743b15a-3c32-48c8-ad58-cb325350befa",
        ),
    )
    assert catalog_provider_ids(raw) == expected
    assert catalog_provider_ids(transformed) == expected


def test_trusted_group_key_is_musicartist_musicbrainz_only() -> None:
    provider_id = "0743b15a-3c32-48c8-ad58-cb325350befa"
    artist = {
        "Type": "MusicArtist",
        "ProviderIds": {"MusicBrainzArtist": provider_id},
    }
    movie = {
        "Type": "Movie",
        "ProviderIds": {"MusicBrainzArtist": provider_id},
    }

    assert trusted_logical_group_key(artist) == (
        f"musicartist:musicbrainzartist:{provider_id}"
    )
    assert trusted_logical_group_key(movie) is None
    assert trusted_logical_group_key({"Type": "MusicArtist"}) is None


def test_candidate_retains_provider_and_physical_identity() -> None:
    item = {
        "Id": "artist-1",
        "Name": "blink-182",
        "Type": "MusicArtist",
        "ProviderIds": {
            "MusicBrainzArtist": "0743b15a-3c32-48c8-ad58-cb325350befa"
        },
    }

    candidate = catalog_item_to_media_candidate(item)

    assert candidate is not None
    assert candidate.physical_keys == ("artist-1",)
    assert candidate.provider_ids == (
        (
            "musicbrainzartist",
            "0743b15a-3c32-48c8-ad58-cb325350befa",
        ),
    )
