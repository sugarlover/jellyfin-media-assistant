"""Protect native-only resolver search routing after YAML retirement."""

from __future__ import annotations

import inspect

from custom_components.jellyfin_assist import orchestration

RETIRED_ROBUST_HELPER = "input_boolean.jellyfin_assist_robust_search"


def test_native_resolver_uses_native_search_only_and_no_rollback_helper() -> None:
    source = inspect.getsource(orchestration)
    assert RETIRED_ROBUST_HELPER not in source
    assert "jellyha.search" not in source
    assert "SERVICE_SEARCH" in source


def test_primary_search_passes_disambiguation_context() -> None:
    source = inspect.getsource(orchestration.async_resolve_media_intent)
    assert "artist=requested_artist" in source
    assert "series=requested_series" in source
    assert "year=requested_year" in source


def test_orchestrator_calls_native_resolver_directly() -> None:
    source = inspect.getsource(orchestration.async_media_orchestrator)
    assert "await async_resolve_media_intent(" in source
    assert "script." not in source


def test_logical_artist_playback_queries_all_grouped_jellyfin_ids() -> None:
    source = inspect.getsource(orchestration.async_resolve_media_intent)
    assert "physical_ids" in source
    assert "SERVICE_GET_ARTIST_TRACKS" in inspect.getsource(orchestration)


def test_native_results_are_not_rejected_by_legacy_substring_filters() -> None:
    source = inspect.getsource(orchestration.async_resolve_media_intent)
    assert "requested_artist_key in candidate_artist_key" not in source
    assert "requested_series_key in candidate_series_key" not in source


def test_episode_title_resolution_is_native_python() -> None:
    source = inspect.getsource(orchestration.async_resolve_episode_title)
    assert '"search_episode_title"' in source
    assert "script." not in source
