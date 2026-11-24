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


def test_pending_selection_play_starts_fresh_queue_add_appends_only() -> None:
    # D5 operation/playback preservation (review item 6): the numbered
    # selection round-trip preserves the spoken operation. A *play*
    # confirmation starts a FRESH queue (clear, then add, then play); an
    # *add* confirmation only APPENDS to the existing queue (no clear).  No
    # playback or queue mutation happens until the user selects.
    source = inspect.getsource(orchestration.async_play_pending_media)

    # The spoken operation is carried from the pending store and only
    # play/add are honored (anything else falls back to play).
    assert 'pending.get("operation")' in source
    assert 'pending_operation not in {"play", "add"}' in source

    # A *play* confirmation clears the queue (fresh start) before adding and
    # playing the selected item.
    assert source.index("SERVICE_QUEUE_CLEAR") < source.index("async_play_item(")

    # An *add* confirmation is the queue-append-only path: it is entered
    # before the clear/prepare/play tail and returns from it, so it never
    # starts a fresh queue.
    add_branch = source.index('if pending_operation == "add":')
    assert add_branch < source.index("SERVICE_QUEUE_CLEAR")
    assert add_branch < source.index("async_play_item(")

    # The pending selection is released only after the selection is resolved
    # (i.e. no mutation before selection).
    assert source.count("runtime.pending_selection = None") >= 2
