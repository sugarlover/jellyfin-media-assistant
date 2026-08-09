"""Release-safety tests for the sanitized public configuration surface."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

import yaml

from tools.configuration_surface_audit import audit_repository


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_HA_REFERENCE = REPOSITORY_ROOT / "reference" / "current-working" / "home-assistant"
PRIVATE_REFERENCE = REPOSITORY_ROOT / "reference" / "private-current-working"


def test_configuration_surface_stays_within_approved_areas() -> None:
    result = audit_repository(REPOSITORY_ROOT)

    assert result.unapproved_findings == ()
    assert result.baseline_overages == ()


def test_sensitive_local_files_are_not_tracked() -> None:
    result = audit_repository(REPOSITORY_ROOT)

    assert result.sensitive_tracked_files == ()


def test_runtime_integration_contains_no_instance_specific_findings() -> None:
    result = audit_repository(REPOSITORY_ROOT)
    runtime_findings = tuple(
        finding
        for finding in result.findings
        if finding.path.startswith("custom_components/jellyfin_assist/")
        and finding.category in {"instance_specific", "credential_adjacent"}
    )

    assert runtime_findings == ()


def test_public_home_assistant_reference_uses_placeholders() -> None:
    configuration = (PUBLIC_HA_REFERENCE / "configuration.yaml").read_text(
        encoding="utf-8"
    )

    assert "MEDIA_SERVER_HOST" not in configuration
    assert "rest_command:" not in configuration
    assert "JELLYFIN_USER_ID" not in configuration
    assert "jellyfin_api_key" not in configuration
    assert re.search(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.", configuration) is None
    assert re.search(r"\b[0-9a-f]{32}\b", configuration, re.IGNORECASE) is None


def test_public_sentence_player_list_contains_examples_only() -> None:
    sentence_file = (
        REPOSITORY_ROOT
        / "custom_components"
        / "jellyfin_assist"
        / "custom_sentences"
        / "en"
        / "jellyfin_assist_media.yaml"
    )
    sentence_data = yaml.safe_load(sentence_file.read_text(encoding="utf-8"))
    values = sentence_data["lists"]["media_player"]["values"]

    assert values
    assert all(value["in"].startswith("Example ") for value in values)
    assert all(value["out"].startswith("media_player.example_") for value in values)


def test_private_household_reference_path_is_ignored() -> None:
    completed = subprocess.run(
        ["git", "check-ignore", "-q", "reference/private-current-working/probe.txt"],
        cwd=REPOSITORY_ROOT,
        check=False,
    )

    assert completed.returncode == 0


def test_public_reference_requires_no_queue_advancement_automation() -> None:
    assert not (PUBLIC_HA_REFERENCE / "automations.yaml").exists()
    assert not (
        PUBLIC_HA_REFERENCE / "jellyfin_assist_automations.example.yaml"
    ).exists()
