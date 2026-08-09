"""Protect native queue-advancement safety and failure-only notifications."""

from __future__ import annotations

from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
ADVANCEMENT: Final = ROOT / "custom_components" / "jellyfin_assist" / "advancement.py"
HA_REFERENCE: Final = ROOT / "reference" / "current-working" / "home-assistant"


def test_manual_queue_advancement_automation_is_retired() -> None:
    assert not (HA_REFERENCE / "jellyfin_assist_automations.example.yaml").exists()


def test_native_queue_advancement_preserves_completion_guardrails() -> None:
    text = ADVANCEMENT.read_text(encoding="utf-8")

    assert "COMPLETION_THRESHOLD_PERCENT: Final = 95.0" in text
    assert 'getattr(old_state, "state", None) != "playing"' in text
    assert 'getattr(new_state, "state", None) != "idle"' in text
    assert "jellyfin_id == current_id" in text
    assert "async_play_item(" in text
    assert "jellyfin_assist_play_media" not in text


def test_persistent_notifications_remain_failure_only() -> None:
    text = ADVANCEMENT.read_text(encoding="utf-8")

    for title in (
        "Jellyfin Assist Queue Read - FAILED",
        "Jellyfin Assist Queue Advance - FAILED",
        "Jellyfin Assist Next Item Playback - FAILED",
    ):
        assert title in text

    assert "Queue Complete" not in text
    assert "NEXT ITEM PLAYING" not in text
    assert "Completion Detection - REJECTED" not in text
