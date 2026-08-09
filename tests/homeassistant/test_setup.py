"""Tests for config-entry setup, cache fallback, and action registration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.homeassistant.ha_stubs import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    FakeEntry,
    FakeHass,
    install_homeassistant_stubs,
)

install_homeassistant_stubs()

from custom_components.jellyfin_assist import (
    _normalize_playback_targets,
    async_migrate_entry,
    async_remove_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.jellyfin_assist.api import (
    JellyfinAuthenticationError,
    JellyfinConnectionError,
    JellyfinConnectionInfo,
    JellyfinInvalidResponseError,
)
from custom_components.jellyfin_assist.search import (
    DEFAULT_CATALOG_MEDIA_TYPES,
    CatalogCacheDocument,
    CatalogCacheStore,
    CatalogLoadStopReason,
    CatalogSnapshot,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def entry_data() -> dict[str, Any]:
    return {
        "server_url": "http://jellyfin.local:8096",
        "api_key": "secret",
        "user_id": "USER-1",
        "verify_ssl": True,
    }


def write_cache(tmp_path: Path, entry_id: str = "entry-1") -> Path:
    path = tmp_path / ".storage" / "jellyfin_assist" / f"catalog-{entry_id}.json"
    snapshot = CatalogSnapshot(
        requested_types=DEFAULT_CATALOG_MEDIA_TYPES,
        items=({"Id": "movie", "Name": "Cached Movie", "Type": "Movie"},),
        pages=(),
        raw_item_count=1,
        duplicate_item_count=0,
        missing_id_count=0,
        server_overflow_item_count=0,
        stop_reason=CatalogLoadStopReason.COMPLETE,
    )
    CatalogCacheStore(path).write(
        CatalogCacheDocument(
            identity="http://jellyfin.local:8096:user-1",
            created_at=1000.0,
            snapshot=snapshot,
        )
    )
    return path


def connection_info() -> JellyfinConnectionInfo:
    return JellyfinConnectionInfo(
        server_id="server",
        server_name="Jellyfin",
        server_version="10.11.11",
        user_id="USER-1",
        user_name="Example User",
    )


def test_async_setup_registers_search_action(tmp_path: Path) -> None:
    hass = FakeHass(tmp_path)

    assert run(async_setup(hass, {})) is True
    assert ("jellyfin_assist", "search") in hass.services.registered


def test_setup_entry_loads_configured_default_media_player(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    write_cache(tmp_path)
    entry = FakeEntry(
        "entry-1",
        entry_data(),
        options={
            "default_media_player": "media_player.example_chromecast",
            "playback_targets": [
                "media_player.example_chromecast",
                "media_player.example_secondary_chromecast",
            ],
        },
    )
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        return connection_info()

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    assert run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data.user_id == "USER-1"
    assert entry.runtime_data.default_media_player == "media_player.example_chromecast"
    assert entry.runtime_data.playback_targets == (
        "media_player.example_chromecast",
        "media_player.example_secondary_chromecast",
    )
    assert entry.runtime_data.queue_client is not None
    assert entry.runtime_data.queue_storage_key == "jellyfin_assist.queue.entry-1"
    assert hass.storage["jellyfin_assist.voice_sentences"]["filename"] == "jellyfin_assist_media.yaml"
    assert entry.runtime_data.voice_sentence_provisioning.status == "installed"
    assert entry.runtime_data.voice_sentence_provisioning.current is True
    assert entry.runtime_data.queue_advancement_targets == (
        "media_player.example_chromecast",
        "media_player.example_secondary_chromecast",
    )
    assert hass.tracked_state_changes[0][0] == (
        "media_player.example_chromecast",
        "media_player.example_secondary_chromecast",
    )
    assert len(entry.unload_callbacks) == 1
    assert entry.state_cache_clear_count == 1



def test_setup_entry_automatically_includes_default_in_effective_targets(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    write_cache(tmp_path)
    entry = FakeEntry(
        "entry-1",
        entry_data(),
        options={
            "default_media_player": "media_player.example_chromecast",
            "playback_targets": ["media_player.example_secondary_chromecast"],
        },
    )
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        return connection_info()

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    assert run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data.playback_targets == (
        "media_player.example_chromecast",
        "media_player.example_secondary_chromecast",
    )

def test_setup_entry_loads_cache_and_schedules_safe_refresh(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    write_cache(tmp_path)
    entry = FakeEntry("entry-1", entry_data())
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        return connection_info()

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    assert run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data.catalog_manager.diagnostics().available is True
    assert entry.runtime_data.startup_used_offline_cache is False
    assert entry.background_tasks[0][0] == "jellyfin_assist refresh catalog"
    assert entry.runtime_data.catalog_manager.search("Cached Movie").outcome.selected_record.item_id == "movie"


def test_setup_entry_allows_offline_start_only_with_valid_cache(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    write_cache(tmp_path)
    entry = FakeEntry("entry-1", entry_data())
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        raise JellyfinConnectionError("offline")

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    assert run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data.startup_used_offline_cache is True
    assert entry.background_tasks == []


def test_setup_entry_retries_when_offline_without_cache(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    entry = FakeEntry("entry-1", entry_data())
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        raise JellyfinConnectionError("offline")

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    with pytest.raises(ConfigEntryNotReady, match="no cached catalog"):
        run(async_setup_entry(hass, entry))


def test_authentication_failure_never_silently_uses_cache(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    write_cache(tmp_path)
    entry = FakeEntry("entry-1", entry_data())
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        raise JellyfinAuthenticationError("bad key")

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    with pytest.raises(ConfigEntryAuthFailed):
        run(async_setup_entry(hass, entry))


def test_invalid_server_response_never_silently_uses_cache(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    write_cache(tmp_path)
    entry = FakeEntry("entry-1", entry_data())
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        raise JellyfinInvalidResponseError("wrong user")

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    with pytest.raises(ConfigEntryNotReady, match="invalid response"):
        run(async_setup_entry(hass, entry))


def test_unload_is_supported(tmp_path: Path) -> None:
    entry = FakeEntry("entry-1", entry_data())
    hass = FakeHass(tmp_path)

    assert run(async_unload_entry(hass, entry)) is True


def test_playback_target_normalization_tolerates_scalar_and_duplicates() -> None:
    assert _normalize_playback_targets("media_player.example_chromecast") == (
        "media_player.example_chromecast",
    )
    assert _normalize_playback_targets(
        ["media_player.example_chromecast", "media_player.example_chromecast", ""]
    ) == ("media_player.example_chromecast",)

def test_setup_entry_tolerates_legacy_behavior_keys_in_data(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    write_cache(tmp_path)
    data = entry_data()
    data.update(
        {
            "default_media_player": "media_player.example_chromecast",
            "playback_targets": "media_player.example_secondary_chromecast",
        }
    )
    entry = FakeEntry("entry-1", data, options={})
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        return connection_info()

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    assert run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data.default_media_player == "media_player.example_chromecast"
    assert entry.runtime_data.playback_targets == (
        "media_player.example_chromecast",
        "media_player.example_secondary_chromecast",
    )


def test_migrate_entry_updates_legacy_minor_schema(tmp_path: Path) -> None:
    data = entry_data()
    data["default_media_player"] = "media_player.example_chromecast"
    data["playback_targets"] = "media_player.example_secondary_chromecast"
    entry = FakeEntry(
        "entry-1",
        data,
        options={},
        version=1,
        minor_version=1,
    )
    hass = FakeHass(tmp_path, entries=[entry])

    assert run(async_migrate_entry(hass, entry)) is True
    assert entry.version == 1
    assert entry.minor_version == 3
    assert entry.update_count == 1
    assert "default_media_player" not in entry.data
    assert "playback_targets" not in entry.data
    assert entry.options == {
        "default_media_player": "media_player.example_chromecast",
        "playback_targets": ["media_player.example_secondary_chromecast"],
    }



def test_migrate_entry_retires_queue_service_option_from_schema_1_2(tmp_path: Path) -> None:
    entry = FakeEntry(
        "entry-1",
        entry_data(),
        options={
            "default_media_player": "media_player.example_chromecast",
            "queue_service_url": "http://queue.example:8787",
        },
        version=1,
        minor_version=2,
    )
    hass = FakeHass(tmp_path, entries=[entry])

    assert run(async_migrate_entry(hass, entry)) is True
    assert entry.minor_version == 3
    assert entry.options == {
        "default_media_player": "media_player.example_chromecast"
    }
    assert entry.update_count == 1

def test_migrate_entry_is_noop_for_current_schema(tmp_path: Path) -> None:
    entry = FakeEntry(
        "entry-1",
        entry_data(),
        options={"default_media_player": "media_player.example_chromecast"},
        version=1,
        minor_version=3,
    )
    hass = FakeHass(tmp_path, entries=[entry])

    assert run(async_migrate_entry(hass, entry)) is True
    assert entry.update_count == 0


def test_migrate_entry_rejects_unknown_major_schema(tmp_path: Path) -> None:
    entry = FakeEntry(
        "entry-1",
        entry_data(),
        version=2,
        minor_version=1,
    )
    hass = FakeHass(tmp_path, entries=[entry])

    assert run(async_migrate_entry(hass, entry)) is False
    assert entry.update_count == 0


def test_remove_final_entry_cleans_unchanged_managed_voice_sentences(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    write_cache(tmp_path)
    entry = FakeEntry("entry-1", entry_data())
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        return connection_info()

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    assert run(async_setup_entry(hass, entry)) is True
    sentence_file = tmp_path / "custom_sentences" / "en" / "jellyfin_assist_media.yaml"
    assert sentence_file.is_file()

    run(async_remove_entry(hass, entry))

    assert not sentence_file.exists()
    assert "jellyfin_assist.voice_sentences" not in hass.storage


def test_remove_final_entry_preserves_user_modified_voice_sentences(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    write_cache(tmp_path)
    entry = FakeEntry("entry-1", entry_data())
    hass = FakeHass(tmp_path, session=object(), entries=[entry])

    async def validate(self: Any, user_id: str) -> JellyfinConnectionInfo:
        return connection_info()

    monkeypatch.setattr(
        "custom_components.jellyfin_assist.api.JellyfinApiClient.async_validate_connection",
        validate,
    )

    assert run(async_setup_entry(hass, entry)) is True
    sentence_file = tmp_path / "custom_sentences" / "en" / "jellyfin_assist_media.yaml"
    sentence_file.write_text("language: en\n# keep me\n", encoding="utf-8")

    run(async_remove_entry(hass, entry))

    assert sentence_file.read_text(encoding="utf-8") == "language: en\n# keep me\n"
    assert "jellyfin_assist.voice_sentences" not in hass.storage
