"""Protect media-aware pending-selection normalization and queue boundaries."""

from __future__ import annotations

import inspect

from custom_components.jellyfin_assist import orchestration
from custom_components.jellyfin_assist import media_actions


def test_pending_audio_normalization_uses_track_fields_not_episode_fields() -> None:
    item = orchestration.normalize_jellyfin_item(
        {
            "Id": "song-1",
            "Name": "Song",
            "Type": "Audio",
            "Artists": ["Artist"],
            "ParentIndexNumber": 2,
            "IndexNumber": 7,
        }
    )
    assert item["season_number"] is None
    assert item["episode_number"] is None
    assert item["disc_number"] == 2
    assert item["track_number"] == 7
    assert item["index_number"] == 7


def test_ambiguous_audio_prompts_include_artist_names() -> None:
    source = inspect.getsource(orchestration._pending_choice_text)
    assert 'item_type == "audio"' in source
    assert "artist_name" in source
    assert "album_artist" in source
    assert 'f" by {artist}"' in source


def test_common_queue_boundary_never_maps_audio_track_to_episode() -> None:
    source = inspect.getsource(media_actions.async_queue_add_item)
    assert 'media_type == "Audio"' in source
    assert "season = episode = \"\"" in source


def test_native_orchestrator_uses_common_queue_add_boundary() -> None:
    source = inspect.getsource(orchestration.async_media_orchestrator)
    assert "async_queue_add_item(" in source
    assert "index_number" not in source[source.index("if requested_operation == \"add\""):source.index("session = await async_prepare_play_session")]
