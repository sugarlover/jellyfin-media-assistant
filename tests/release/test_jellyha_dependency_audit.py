from __future__ import annotations

from collections import Counter
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "jellyha_dependency_audit.py"

spec = importlib.util.spec_from_file_location("jellyha_dependency_audit", TOOL_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_jellyha_dependency_audit_passes() -> None:
    assert module.audit() == []


def test_direct_jellyha_actions_are_no_longer_production_actions() -> None:
    assert not module.CANONICAL_SCRIPTS.exists()
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in module.JELLYFIN_ASSIST_RUNTIME.rglob("*")
        if path.is_file() and path.suffix in {".py", ".yaml", ".json"}
    )
    assert "jellyha.get_item" not in runtime_text
    assert "jellyha.search" not in runtime_text
    assert "jellyha.play_on_chromecast" not in runtime_text
    assert "async_play_on_chromecast(" in (module.JELLYFIN_ASSIST_RUNTIME / "media_actions.py").read_text(encoding="utf-8")


def test_public_manifest_does_not_declare_jellyha_dependency() -> None:
    manifest = json.loads(module.PUBLIC_MANIFEST.read_text(encoding="utf-8"))
    assert "jellyha" not in set(manifest.get("dependencies") or [])
    assert all("jellyha" not in str(req).casefold() for req in manifest.get("requirements") or [])


def test_all_tracked_jellyha_runtime_dependencies_are_fully_retired() -> None:
    inventory = json.loads(module.INVENTORY.read_text(encoding="utf-8"))
    for item in inventory["tracked_upstream_capabilities"]:
        assert item["classification"] == "retired_runtime_provenance_reference"
        assert item["canonical_caller"] is None
        assert item["additional_caller"] is None

    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in module.JELLYFIN_ASSIST_RUNTIME.rglob("*")
        if path.is_file() and path.suffix in {".py", ".yaml", ".json"}
    )
    assert "jellyha.get_item" not in runtime_text
    assert "jellyha.search" not in runtime_text
    assert "jellyha.play_on_chromecast" not in runtime_text
    assert "compare_search" not in runtime_text
    assert "LEGACY_JELLYHA_" not in runtime_text


def test_get_item_runtime_dependency_is_fully_retired() -> None:
    inventory = json.loads(module.INVENTORY.read_text(encoding="utf-8"))
    get_item = next(
        item
        for item in inventory["tracked_upstream_capabilities"]
        if item["service"] == "jellyha.get_item"
    )
    assert get_item["classification"] == "retired_runtime_provenance_reference"
    assert get_item["canonical_caller"] is None
    assert get_item["additional_caller"] is None
    assert get_item["migration_status"] == "runtime_retired_step_44a"

    runtime_text = (
        module.JELLYFIN_ASSIST_CONST.read_text(encoding="utf-8")
        + module.JELLYFIN_ASSIST_SERVICES.read_text(encoding="utf-8")
    )
    assert "jellyha.get_item" not in runtime_text
    assert "LEGACY_JELLYHA_GET_ITEM_SERVICE" not in runtime_text
    assert "compare_get_item" not in runtime_text


def test_provenance_gap_is_explicit_not_guessed() -> None:
    inventory = json.loads(module.INVENTORY.read_text(encoding="utf-8"))
    assert inventory["vendored_manifest_version"] == "1.2.0"
    assert inventory["vendored_upstream_commit"] is None
    assert inventory["provenance_status"] == "commit_sha_missing"


def test_vendored_reference_carries_upstream_mit_notice() -> None:
    text = module.VENDORED_LICENSE.read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "Copyright (c) 2026 zupancicmarko" in text


def test_step_42b_adaptation_source_is_pinned_separately() -> None:
    inventory = json.loads(module.INVENTORY.read_text(encoding="utf-8"))
    assert inventory["vendored_upstream_commit"] is None
    assert inventory["adaptation_source_commit"] == (
        "6b8b2f679f922ea3a0d9c3c4b9827ee7053308f9"
    )
    assert set(inventory["adaptation_source_scope"]) == {
        "custom_components/jellyha/services.py",
        "custom_components/jellyha/api.py",
    }
