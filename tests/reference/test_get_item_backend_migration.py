"""Protect the native get_item production migration after YAML retirement."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATION = ROOT / "custom_components" / "jellyfin_assist" / "orchestration.py"
MEDIA_ACTIONS = ROOT / "custom_components" / "jellyfin_assist" / "media_actions.py"
SERVICES = ROOT / "custom_components" / "jellyfin_assist" / "services.py"
DUPLICATE = ROOT / "tools" / "reference" / "current-working" / "home-assistant" / "scripts.yaml"
PUBLIC_SCRIPTS = ROOT / "reference" / "current-working" / "home-assistant" / "scripts.yaml"


def test_production_get_item_paths_are_native() -> None:
    orchestration = ORCHESTRATION.read_text(encoding="utf-8")
    media_actions = MEDIA_ACTIONS.read_text(encoding="utf-8")
    services = SERVICES.read_text(encoding="utf-8")
    assert "async_get_native_item" in orchestration
    assert "async_get_native_item" in media_actions
    assert "async_handle_get_item" in services
    for text in (orchestration, media_actions, services):
        assert "jellyha.get_item" not in text


def test_stale_duplicate_reference_is_retired() -> None:
    assert not DUPLICATE.exists()


def test_project_owned_public_scripts_are_retired() -> None:
    assert not PUBLIC_SCRIPTS.exists()
    text = ORCHESTRATION.read_text(encoding="utf-8")
    assert "robust_config_entry_id" not in text
