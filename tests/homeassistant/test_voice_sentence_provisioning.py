"""Tests for managed custom-sentence provisioning and repair behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from tests.homeassistant.ha_stubs import FakeHass, install_homeassistant_stubs

install_homeassistant_stubs()

from custom_components.jellyfin_assist.const import DOMAIN
from custom_components.jellyfin_assist.voice import (
    CUSTOM_SENTENCE_FILENAME,
    CUSTOM_SENTENCE_LANGUAGE,
)
from custom_components.jellyfin_assist.voice_sentences import (
    VOICE_SENTENCE_STORE_KEY,
    VOICE_SENTENCE_USER_MODIFIED_ISSUE,
    async_inspect_voice_sentences,
    async_provision_voice_sentences,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def installed_path(root: Path) -> Path:
    return root / "custom_sentences" / CUSTOM_SENTENCE_LANGUAGE / CUSTOM_SENTENCE_FILENAME


def packaged_file(tmp_path: Path, monkeypatch: Any, content: bytes = b"language: en\n") -> Path:
    packaged = tmp_path / "package" / CUSTOM_SENTENCE_FILENAME
    packaged.parent.mkdir(parents=True)
    packaged.write_bytes(content)
    monkeypatch.setattr(
        "custom_components.jellyfin_assist.voice_sentences.PACKAGED_SENTENCE_PATH",
        packaged,
    )
    return packaged


def register_conversation_reload(hass: FakeHass) -> None:
    async def reload_handler(call: Any) -> None:
        return None

    hass.services.async_register("conversation", "reload", reload_handler)


def test_first_setup_installs_and_reloads_managed_sentences(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    packaged = packaged_file(tmp_path, monkeypatch, b"language: en\nintents: {}\n")
    hass = FakeHass(tmp_path)
    register_conversation_reload(hass)

    result = run(async_provision_voice_sentences(hass))

    assert result.status == "installed"
    assert result.managed is True
    assert result.current is True
    assert result.reload_attempted is True
    assert result.reload_succeeded is True
    assert installed_path(tmp_path).read_bytes() == packaged.read_bytes()
    assert hass.storage[VOICE_SENTENCE_STORE_KEY]["managed_sha256"]
    assert hass.services.calls[-1]["domain"] == "conversation"
    assert hass.services.calls[-1]["service"] == "reload"


def test_identical_existing_file_is_adopted_without_reload(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    packaged = packaged_file(tmp_path, monkeypatch, b"language: en\nintents: {}\n")
    target = installed_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(packaged.read_bytes())
    hass = FakeHass(tmp_path)
    register_conversation_reload(hass)

    result = run(async_provision_voice_sentences(hass))

    assert result.status == "current"
    assert result.managed is True
    assert result.reload_attempted is False
    assert hass.services.calls == []
    assert run(async_inspect_voice_sentences(hass)).managed is True


def test_untouched_managed_file_updates_when_packaged_sentences_change(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    packaged = packaged_file(tmp_path, monkeypatch, b"language: en\nversion: 1\n")
    hass = FakeHass(tmp_path)
    register_conversation_reload(hass)
    assert run(async_provision_voice_sentences(hass)).status == "installed"
    hass.services.calls.clear()

    packaged.write_bytes(b"language: en\nversion: 2\n")
    result = run(async_provision_voice_sentences(hass))

    assert result.status == "updated"
    assert result.current is True
    assert installed_path(tmp_path).read_bytes() == packaged.read_bytes()
    assert hass.services.calls[-1]["service"] == "reload"


def test_user_modified_managed_file_is_preserved_and_repair_issue_created(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    packaged_file(tmp_path, monkeypatch, b"language: en\nversion: 1\n")
    hass = FakeHass(tmp_path)
    assert run(async_provision_voice_sentences(hass)).status == "installed"
    target = installed_path(tmp_path)
    target.write_bytes(b"language: en\n# local customization\n")

    result = run(async_provision_voice_sentences(hass))

    assert result.status == "user_modified"
    assert result.user_modified is True
    assert target.read_bytes() == b"language: en\n# local customization\n"
    assert (DOMAIN, VOICE_SENTENCE_USER_MODIFIED_ISSUE) in hass.issues




def test_unmanaged_existing_file_is_preserved_until_explicit_repair(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    packaged_file(tmp_path, monkeypatch, b"language: en\nversion: packaged\n")
    target = installed_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"language: en\n# pre-existing local file\n")
    hass = FakeHass(tmp_path)

    result = run(async_provision_voice_sentences(hass))

    assert result.status == "unmanaged_existing"
    assert result.managed is False
    assert result.user_modified is True
    assert target.read_bytes() == b"language: en\n# pre-existing local file\n"

def test_explicit_repair_can_restore_user_modified_file(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    packaged = packaged_file(tmp_path, monkeypatch, b"language: en\nversion: 1\n")
    hass = FakeHass(tmp_path)
    register_conversation_reload(hass)
    assert run(async_provision_voice_sentences(hass)).status == "installed"
    target = installed_path(tmp_path)
    target.write_bytes(b"language: en\n# local customization\n")

    result = run(
        async_provision_voice_sentences(hass, overwrite_user_modified=True)
    )

    assert result.status == "repaired"
    assert result.current is True
    assert target.read_bytes() == packaged.read_bytes()
    assert (DOMAIN, VOICE_SENTENCE_USER_MODIFIED_ISSUE) not in hass.issues


def test_install_succeeds_when_conversation_reload_service_is_not_loaded(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    packaged_file(tmp_path, monkeypatch, b"language: en\nintents: {}\n")
    hass = FakeHass(tmp_path)

    result = run(async_provision_voice_sentences(hass))

    assert result.status == "installed"
    assert result.current is True
    assert result.reload_attempted is False
    assert result.reload_succeeded is False
