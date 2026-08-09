"""Protect intent and query context in native resolver/pending responses."""

from __future__ import annotations

import inspect

from custom_components.jellyfin_assist import orchestration


def test_native_resolver_preserves_explicit_requested_type_before_fallbacks() -> None:
    source = inspect.getsource(orchestration.async_resolve_media_intent)
    assert "requested_type = _text(media_type) or None" in source
    assert "fallback_media_type: str | None = requested_type" in source


def test_native_resolver_preserves_query_and_intent_on_not_found_and_multiple_matches() -> None:
    source = inspect.getsource(orchestration.async_resolve_media_intent)
    assert 'status="not_found"' in source
    assert 'status="multiple_matches"' in source
    assert "intent=fallback_media_type" in source
    assert "query=query" in source


def test_orchestrator_persists_pending_context_in_integration_runtime() -> None:
    source = inspect.getsource(orchestration.async_media_orchestrator)
    assert "runtime.pending_selection =" in source
    for field in ('"items"', '"media_player"', '"operation"', '"query"', '"intent"'):
        assert field in source


def test_pending_selection_reads_runtime_state_and_never_uses_helpers() -> None:
    source = inspect.getsource(orchestration.async_play_pending_media)
    assert "runtime.pending_selection" in source
    assert "pending_query" in source
    assert "pending_intent" in source
    assert "input_text." not in source
    assert "input_boolean." not in source


def test_successful_pending_selection_clears_runtime_state() -> None:
    source = inspect.getsource(orchestration.async_play_pending_media)
    assert source.count("runtime.pending_selection = None") >= 3


def test_pending_container_selection_restores_original_request_context() -> None:
    source = inspect.getsource(orchestration.async_play_pending_media)
    assert "if pending_query:" in source
    assert 'result["query"] = pending_query' in source
    assert "if pending_intent:" in source
    assert 'result["intent"] = pending_intent' in source
