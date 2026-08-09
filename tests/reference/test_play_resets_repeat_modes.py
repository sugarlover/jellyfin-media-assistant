"""Protect repeat-mode reset semantics for native media orchestration."""

from __future__ import annotations

import inspect

from custom_components.jellyfin_assist import orchestration
from custom_components.jellyfin_assist import media_actions
from custom_components.jellyfin_assist import advancement
from custom_components.jellyfin_assist import queue_control


def test_native_play_session_helper_disables_both_repeat_modes_idempotently() -> None:
    source = inspect.getsource(media_actions.async_prepare_play_session)

    assert "repeat_item=False" in source
    assert "repeat_queue=False" in source
    assert 'status": "repeat_reset_failed"' in source
    assert 'not bool(body.get("repeat_item", False))' in source
    assert 'not bool(body.get("repeat_queue", False))' in source


def test_native_orchestrator_prepares_session_before_clearing_queue() -> None:
    source = inspect.getsource(orchestration.async_media_orchestrator)

    assert source.index("async_prepare_play_session(") < source.index("SERVICE_QUEUE_CLEAR")
    assert 'status="repeat_reset_failed"' in source


def test_pending_play_prepares_session_before_clearing_queue() -> None:
    source = inspect.getsource(orchestration.async_play_pending_media)

    assert source.index("async_prepare_play_session(") < source.index("SERVICE_QUEUE_CLEAR")


def test_add_and_low_level_play_do_not_reset_repeat_modes() -> None:
    queue_add = inspect.getsource(media_actions.async_queue_add_item)
    play_item = inspect.getsource(media_actions.async_play_item)

    assert "async_prepare_play_session(" not in queue_add
    assert "async_prepare_play_session(" not in play_item
    assert "repeat_item=False" not in play_item


def test_queue_advancement_does_not_reset_repeat_modes() -> None:
    assert "async_prepare_play_session" not in inspect.getsource(advancement)
    assert "async_prepare_play_session" not in inspect.getsource(queue_control)
