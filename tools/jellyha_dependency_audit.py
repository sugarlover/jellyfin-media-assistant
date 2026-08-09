#!/usr/bin/env python3
"""Audit that JellyHA remains provenance-only and absent from runtime dependencies."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "provenance" / "jellyha.json"
PUBLIC_MANIFEST = ROOT / "custom_components" / "jellyfin_assist" / "manifest.json"
JELLYFIN_ASSIST_RUNTIME = ROOT / "custom_components" / "jellyfin_assist"
JELLYFIN_ASSIST_CONST = JELLYFIN_ASSIST_RUNTIME / "const.py"
JELLYFIN_ASSIST_SERVICES = JELLYFIN_ASSIST_RUNTIME / "services.py"
RETAINED_LICENSE = ROOT / "docs" / "provenance" / "JELLYHA_LICENSE.txt"
THIRD_PARTY_NOTICE = ROOT / "THIRD_PARTY_NOTICES.md"
HISTORICAL_SOURCE_SNAPSHOT = ROOT / "reference" / "current-working" / "jellyha"
EXPECTED_TRACKED_SERVICES = {
    "jellyha.get_item",
    "jellyha.search",
    "jellyha.play_on_chromecast",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit() -> list[str]:
    """Return human-readable errors; empty means provenance/runtime boundaries hold."""

    errors: list[str] = []

    if not INVENTORY.exists():
        return [f"Missing provenance inventory: {INVENTORY.relative_to(ROOT)}"]

    inventory = _load_json(INVENTORY)
    capabilities = inventory.get("tracked_upstream_capabilities", [])
    inventory_services = {
        str(item.get("service"))
        for item in capabilities
        if isinstance(item, dict) and item.get("service")
    }
    if inventory_services != EXPECTED_TRACKED_SERVICES:
        errors.append(
            "Provenance inventory services differ from the approved retired set: "
            f"{sorted(inventory_services)}"
        )

    manifest = _load_json(PUBLIC_MANIFEST)
    dependencies = set(manifest.get("dependencies") or [])
    requirements = " ".join(str(x) for x in manifest.get("requirements") or [])
    if "jellyha" in dependencies or "jellyha" in requirements.casefold():
        errors.append(
            "Public jellyfin_assist manifest unexpectedly declares JellyHA as a package/integration dependency"
        )

    const_text = JELLYFIN_ASSIST_CONST.read_text(encoding="utf-8")
    services_text = JELLYFIN_ASSIST_SERVICES.read_text(encoding="utf-8")
    if 'SERVICE_GET_ITEM: Final = "get_item"' not in const_text:
        errors.append("Native get_item action marker was not found")
    if "async_handle_get_item" not in services_text:
        errors.append("Native get_item action was not found")

    media_actions_text = (JELLYFIN_ASSIST_RUNTIME / "media_actions.py").read_text(
        encoding="utf-8"
    )
    if "async_play_on_chromecast(" not in media_actions_text:
        errors.append("Native high-level playback no longer routes through async_play_on_chromecast")

    runtime_files = [
        path
        for path in JELLYFIN_ASSIST_RUNTIME.rglob("*")
        if path.is_file() and path.suffix in {".py", ".yaml", ".json"}
    ]
    runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    forbidden_runtime_markers = (
        "jellyha.get_item",
        "jellyha.search",
        "jellyha.play_on_chromecast",
        "LEGACY_JELLYHA_",
        "SERVICE_COMPARE_SEARCH",
        "compare_search",
        "compare_get_item",
    )
    for marker in forbidden_runtime_markers:
        if marker in runtime_text:
            errors.append(f"Retired JellyHA runtime surface reappeared: {marker}")

    for item in capabilities:
        if not isinstance(item, dict):
            continue
        if item.get("classification") != "retired_runtime_provenance_reference":
            errors.append(
                f"Tracked capability is not fully runtime-retired: {item.get('service')}"
            )
        if item.get("canonical_caller") is not None or item.get("additional_caller") is not None:
            errors.append(
                f"Tracked capability still records a runtime caller: {item.get('service')}"
            )
        if item.get("migration_status") != "runtime_retired":
            errors.append(
                f"Tracked capability has an unexpected migration status: {item.get('service')}"
            )

    if HISTORICAL_SOURCE_SNAPSHOT.exists():
        errors.append(
            "Historical JellyHA source snapshot should not be distributed in the public repository"
        )

    if not RETAINED_LICENSE.exists():
        errors.append("Retained JellyHA MIT license is missing")
    else:
        license_text = RETAINED_LICENSE.read_text(encoding="utf-8")
        if "MIT License" not in license_text or "Copyright (c) 2026 zupancicmarko" not in license_text:
            errors.append("Retained JellyHA license does not contain the recorded upstream notice")

    if not THIRD_PARTY_NOTICE.exists():
        errors.append("Missing THIRD_PARTY_NOTICES.md")
    else:
        notice = THIRD_PARTY_NOTICE.read_text(encoding="utf-8")
        if "zupancicmarko/JellyHA" not in notice or "License: MIT" not in notice:
            errors.append("THIRD_PARTY_NOTICES.md does not record JellyHA provenance")

    if inventory.get("retained_license_path") != "docs/provenance/JELLYHA_LICENSE.txt":
        errors.append("JellyHA provenance does not point to the retained public license")
    if inventory.get("public_source_snapshot_retained") is not False:
        errors.append("JellyHA provenance must record that no public source snapshot is retained")
    if inventory.get("historical_snapshot_commit") is not None:
        errors.append("Unknown historical JellyHA snapshot commit must remain explicitly null")

    adaptation_commit = inventory.get("adaptation_source_commit")
    if adaptation_commit != "6b8b2f679f922ea3a0d9c3c4b9827ee7053308f9":
        errors.append("JellyHA adaptation source is not pinned to the verified commit")
    adaptation_scope = set(inventory.get("adaptation_source_scope") or [])
    if adaptation_scope != {
        "custom_components/jellyha/services.py",
        "custom_components/jellyha/api.py",
    }:
        errors.append("JellyHA adaptation source scope is incomplete")

    return errors


def main() -> int:
    errors = audit()
    if errors:
        print("JellyHA dependency/provenance audit: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("JellyHA dependency/provenance audit: PASS")
    print(
        "Tracked upstream services: jellyha.get_item, jellyha.search, "
        "jellyha.play_on_chromecast (all retired runtime/provenance only)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
