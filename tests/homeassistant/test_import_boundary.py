"""The pure search package must remain usable without Home Assistant imports."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_search_tool_package_import_does_not_import_homeassistant_or_aiohttp() -> None:
    root = Path(__file__).resolve().parents[2]
    script = """
import sys
sys.modules['homeassistant'] = None
sys.modules['aiohttp'] = None
import custom_components.jellyfin_assist.search
assert 'custom_components.jellyfin_assist.api' not in sys.modules
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
