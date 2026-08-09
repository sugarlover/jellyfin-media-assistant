"""Release tests for the first public-beta repository packaging surface."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.jellyfin_assist.const import VERSION
from tools import repository_packaging_audit

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "custom_components" / "jellyfin_assist"


def test_public_beta_version_is_consistent() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))

    assert VERSION == "0.1.0-beta.1"
    assert manifest["version"] == VERSION
    assert "0.1.0-beta.1" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_manifest_has_hacs_required_repository_metadata() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["documentation"] == "https://github.com/sugarlover/jellyfin-media-assistant#readme"
    assert manifest["issue_tracker"] == "https://github.com/sugarlover/jellyfin-media-assistant/issues"
    assert manifest["codeowners"] == ["@sugarlover"]


def test_hacs_manifest_declares_beta_minimum_home_assistant() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))

    assert hacs == {
        "name": "Jellyfin Media Assistant",
        "homeassistant": "2026.7.0",
    }


def test_release_repository_has_single_custom_integration() -> None:
    integration_dirs = sorted(
        path.name for path in (ROOT / "custom_components").iterdir() if path.is_dir()
    )
    assert integration_dirs == ["jellyfin_assist"]


def test_root_release_docs_and_license_exist() -> None:
    expected = {
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "hacs.json",
    }
    assert all((ROOT / name).is_file() for name in expected)


def test_repository_packaging_audit_passes() -> None:
    assert repository_packaging_audit.main() == 0
