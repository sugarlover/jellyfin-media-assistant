"""Release guardrails for native Assist onboarding."""

from __future__ import annotations

from pathlib import Path

import yaml

from custom_components.jellyfin_assist.voice import (
    CUSTOM_SENTENCE_FILENAME,
    CUSTOM_SENTENCE_LANGUAGE,
    NATIVE_INTENT_TYPES,
)

ROOT = Path(__file__).resolve().parents[2]
SENTENCES = (
    ROOT
    / "custom_components"
    / "jellyfin_assist"
    / "custom_sentences"
    / CUSTOM_SENTENCE_LANGUAGE
    / CUSTOM_SENTENCE_FILENAME
)


def test_packaged_custom_sentences_match_native_intent_inventory() -> None:
    data = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))

    assert data["language"] == "en"
    assert set(data["intents"]) == set(NATIVE_INTENT_TYPES)


def test_packaged_voice_surface_uses_canonical_namespace_only() -> None:
    text = SENTENCES.read_text(encoding="utf-8")

    assert "JellyHA" not in text
    assert "jellyha_" not in text
    assert "JellyfinAssist" in text


def test_current_working_reference_requires_no_manual_voice_sentence_copy() -> None:
    active_sentences = (
        ROOT
        / "reference"
        / "current-working"
        / "home-assistant"
        / "custom_sentences"
        / CUSTOM_SENTENCE_LANGUAGE
        / CUSTOM_SENTENCE_FILENAME
    )
    legacy_sentences = active_sentences.with_name("jellyha_media.yaml")
    configuration = (
        ROOT
        / "reference"
        / "current-working"
        / "home-assistant"
        / "configuration.yaml"
    )

    assert not active_sentences.exists()
    assert not legacy_sentences.exists()
    configuration_text = configuration.read_text(encoding="utf-8")
    assert "intent_script:" not in configuration_text
    assert "JellyHA" not in configuration_text


def test_voice_sentence_provisioning_is_part_of_integration_setup() -> None:
    setup_text = (ROOT / "custom_components" / "jellyfin_assist" / "__init__.py").read_text(
        encoding="utf-8"
    )
    manifest = yaml.safe_load(
        (ROOT / "custom_components" / "jellyfin_assist" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert "async_provision_voice_sentences" in setup_text
    assert "conversation" in manifest.get("after_dependencies", [])
