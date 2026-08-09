#!/usr/bin/env python3
"""Audit the remaining upstream JellyHA runtime dependency surface."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "provenance" / "jellyha.json"
CANONICAL_SCRIPTS = (
    ROOT / "reference" / "current-working" / "home-assistant" / "scripts.yaml"
)
PUBLIC_MANIFEST = ROOT / "custom_components" / "jellyfin_assist" / "manifest.json"
JELLYFIN_ASSIST_RUNTIME = ROOT / "custom_components" / "jellyfin_assist"
JELLYFIN_ASSIST_CONST = JELLYFIN_ASSIST_RUNTIME / "const.py"
JELLYFIN_ASSIST_SERVICES = JELLYFIN_ASSIST_RUNTIME / "services.py"
VENDORED_LICENSE = ROOT / "reference" / "current-working" / "jellyha" / "LICENSE"
THIRD_PARTY_NOTICE = ROOT / "THIRD_PARTY_NOTICES.md"

ACTION_PATTERN = re.compile(
    r"^\s*(?:-\s*)?(?:action|service):\s*jellyha\.([a-z0-9_]+)\s*$",
    re.MULTILINE,
)
NATIVE_PLAYBACK_PATTERN = re.compile(
    r"^\s*(?:-\s*)?(?:action|service):\s*jellyfin_assist\.play_on_chromecast\s*$",
    re.MULTILINE,
)
EXPECTED_ACTION_COUNTS = Counter()
EXPECTED_NATIVE_PLAYBACK_ACTION_COUNT = 0
EXPECTED_TRACKED_SERVICES = {
    "jellyha.get_item",
    "jellyha.search",
    "jellyha.play_on_chromecast",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit() -> list[str]:
    """Return human-readable errors; empty means the dependency inventory is current."""

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
            "Provenance inventory services differ from the approved dependency set: "
            f"{sorted(inventory_services)}"
        )

    if CANONICAL_SCRIPTS.exists():
        errors.append(
            "Project-owned Home Assistant scripts unexpectedly reappeared after native orchestration migration"
        )
    action_counts = Counter()
    media_actions_text = (JELLYFIN_ASSIST_RUNTIME / "media_actions.py").read_text(encoding="utf-8")
    if "async_play_on_chromecast(" not in media_actions_text:
        errors.append("Native high-level playback no longer routes through async_play_on_chromecast")

    unexpected = {f"jellyha.{name}" for name in action_counts} - EXPECTED_TRACKED_SERVICES
    if unexpected:
        errors.append(f"Unexpected upstream JellyHA actions: {sorted(unexpected)}")

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

    if not VENDORED_LICENSE.exists():
        errors.append("Vendored JellyHA reference is missing its MIT license")
    else:
        license_text = VENDORED_LICENSE.read_text(encoding="utf-8")
        if "MIT License" not in license_text or "Copyright (c) 2026 zupancicmarko" not in license_text:
            errors.append("Vendored JellyHA license does not contain the recorded upstream notice")

    if not THIRD_PARTY_NOTICE.exists():
        errors.append("Missing THIRD_PARTY_NOTICES.md")
    else:
        notice = THIRD_PARTY_NOTICE.read_text(encoding="utf-8")
        if "zupancicmarko/JellyHA" not in notice or "License: MIT" not in notice:
            errors.append("THIRD_PARTY_NOTICES.md does not record JellyHA provenance")


    adaptation_commit = inventory.get("adaptation_source_commit")
    if adaptation_commit != "6b8b2f679f922ea3a0d9c3c4b9827ee7053308f9":
        errors.append("Step 42B get_item adaptation source is not pinned to the verified JellyHA commit")
    adaptation_scope = set(inventory.get("adaptation_source_scope") or [])
    if adaptation_scope != {
        "custom_components/jellyha/services.py",
        "custom_components/jellyha/api.py",
    }:
        errors.append("Step 42B get_item adaptation scope is incomplete")

    if inventory.get("vendored_upstream_commit") is not None:
        # Once a real SHA is recorded, provenance_status must also be updated.
        if inventory.get("provenance_status") == "commit_sha_missing":
            errors.append("Vendored commit is populated but provenance_status still says commit_sha_missing")
    elif inventory.get("provenance_status") != "commit_sha_missing":
        errors.append("Missing vendored commit SHA must remain explicitly marked as a provenance gap")

    return errors


def main() -> int:
    errors = audit()
    if errors:
        print("JellyHA dependency/provenance audit: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("JellyHA dependency/provenance audit: PASS")
    print("Tracked upstream services: jellyha.get_item, jellyha.search, jellyha.play_on_chromecast (all retired runtime/provenance only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
