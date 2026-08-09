"""Audit on-disk public-beta packaging requirements that do not require GitHub state."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "jellyfin_assist"
EXPECTED_VERSION = "0.1.0-beta.1"


def _failures() -> list[str]:
    failures: list[str] = []

    required_root = [
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "hacs.json",
    ]
    for name in required_root:
        if not (ROOT / name).is_file():
            failures.append(f"missing root release file: {name}")

    integration_dirs = [p for p in (ROOT / "custom_components").iterdir() if p.is_dir()]
    if [p.name for p in integration_dirs] != ["jellyfin_assist"]:
        failures.append(
            "custom_components must contain exactly the jellyfin_assist integration"
        )

    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    expected_manifest = {
        "domain": "jellyfin_assist",
        "name": "Jellyfin Media Assistant",
        "documentation": "https://github.com/sugarlover/jellyfin-media-assistant#readme",
        "issue_tracker": "https://github.com/sugarlover/jellyfin-media-assistant/issues",
        "version": EXPECTED_VERSION,
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            failures.append(f"manifest {key!r} must be {expected!r}")
    if manifest.get("codeowners") != ["@sugarlover"]:
        failures.append("manifest codeowners must contain @sugarlover")

    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    if hacs.get("name") != "Jellyfin Media Assistant":
        failures.append("hacs.json name is incorrect")
    if hacs.get("homeassistant") != "2026.7.0":
        failures.append("hacs.json minimum Home Assistant version must be 2026.7.0")

    const_text = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    if f'VERSION: Final = "{EXPECTED_VERSION}"' not in const_text:
        failures.append("const.VERSION does not match manifest beta version")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_readme_phrases = [
        "Installation with HACS",
        "Chromecast",
        "No separate Python installation",
        "custom_sentences",
        "MIT License",
    ]
    for phrase in required_readme_phrases:
        if phrase not in readme:
            failures.append(f"README is missing release guidance: {phrase}")

    retired_paths = [
        ROOT / "reference" / "current-working" / "queue-service",
        ROOT / "reference" / "current-working" / "home-assistant" / "scripts.yaml",
        ROOT / "STEP44B_DELETE_FILES.txt",
    ]
    for path in retired_paths:
        if path.exists():
            failures.append(f"retired pre-beta artifact still exists: {path.relative_to(ROOT)}")

    return failures


def main() -> int:
    failures = _failures()
    print("Repository packaging audit")
    if failures:
        for failure in failures:
            print(f"- FAIL: {failure}")
        return 1
    print("- release metadata: PASS")
    print("- HACS on-disk metadata: PASS")
    print("- beta documentation/license surface: PASS")
    print("- retired runtime artifacts: PASS")
    print("PASS (brand asset and public GitHub settings are checked in Step 46C2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
