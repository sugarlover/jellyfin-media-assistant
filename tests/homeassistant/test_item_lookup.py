"""Contract tests for native JellyHA-compatible item lookup."""

from __future__ import annotations

from custom_components.jellyfin_assist.item_lookup import (
    enrich_jellyha_item,
)


def test_enrichment_prefers_first_media_source_streams() -> None:
    result = enrich_jellyha_item(
        {
            "Id": "audio-1",
            "MediaSources": [
                {"MediaStreams": [{"Type": "Audio", "Codec": "flac"}]},
                {"MediaStreams": [{"Type": "Audio", "Codec": "aac"}]},
            ],
            "MediaStreams": [{"Type": "Audio", "Codec": "fallback"}],
            "UserData": {"IsFavorite": True, "Played": True},
        }
    )

    assert result["media_streams"] == [{"Type": "Audio", "Codec": "flac"}]
    assert result["is_favorite"] is True
    assert result["is_played"] is True


def test_enrichment_uses_top_level_streams_when_media_sources_missing() -> None:
    result = enrich_jellyha_item(
        {"Id": "movie-1", "MediaStreams": [{"Type": "Video"}], "UserData": {}}
    )

    assert result["media_streams"] == [{"Type": "Video"}]
    assert result["is_favorite"] is False
    assert result["is_played"] is False


def test_enrichment_matches_jellyha_when_no_stream_fields_exist() -> None:
    result = enrich_jellyha_item({"Id": "artist-1", "UserData": None})

    assert "media_streams" not in result
    assert result["is_favorite"] is False
    assert result["is_played"] is False
