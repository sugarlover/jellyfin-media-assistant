"""Jellyfin Media Assistant Home Assistant integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .const import (
    CACHE_DIRECTORY,
    CACHE_FILENAME_PREFIX,
    DEFAULT_CATALOG_PAGE_SIZE,
    DOMAIN,
)
from .configuration import (
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    JellyfinBehaviorSettings,
    JellyfinConnectionSettings,
    migrate_config_entry_payload,
    normalize_playback_targets,
)
from .search import (
    DEFAULT_CATALOG_MEDIA_TYPES,
    CatalogCacheStore,
    CatalogManager,
    CatalogRefreshError,
    JellyfinCatalogClient,
    load_catalog_snapshot,
)

_LOGGER = logging.getLogger(__name__)


def _cache_path(hass: Any, entry_id: str) -> Path:
    """Return one private metadata-cache path inside Home Assistant storage."""

    filename = f"{CACHE_FILENAME_PREFIX}-{entry_id}.json"
    return Path(hass.config.path(CACHE_DIRECTORY, filename))


def _normalize_playback_targets(value: Any) -> tuple[str, ...]:
    """Compatibility wrapper for the centralized option normalizer."""

    return normalize_playback_targets(value)


async def _async_background_refresh(manager: CatalogManager) -> None:
    """Refresh a cache-backed catalog without disrupting current searches."""

    try:
        await manager.async_refresh()
    except CatalogRefreshError as err:
        _LOGGER.warning("Jellyfin catalog background refresh failed: %s", err)


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Jellyfin Media Assistant from a config entry."""

    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.storage import Store

    from .api import (
        JellyfinApiClient,
        JellyfinAuthenticationError,
        JellyfinConnectionError,
        JellyfinInvalidResponseError,
    )
    from .queue_store import NativeQueueStore, QueueStoreError
    from .runtime import JellyfinAssistRuntime

    connection = JellyfinConnectionSettings.from_mapping(entry.data)
    behavior = JellyfinBehaviorSettings.from_mappings(
        entry.options,
        legacy_data=entry.data,
    )

    client = JellyfinApiClient(
        session=async_get_clientsession(hass),
        server_url=connection.server_url,
        api_key=connection.api_key,
        verify_ssl=connection.verify_ssl,
    )
    catalog_client = JellyfinCatalogClient(api=client, user_id=connection.user_id)
    queue_storage_key = f"{DOMAIN}.queue.{entry.entry_id}"
    queue_backend = Store[dict[str, Any]](
        hass,
        1,
        queue_storage_key,
        private=True,
        atomic_writes=True,
    )
    queue_client = NativeQueueStore(
        queue_backend,
        storage_key=queue_storage_key,
    )
    try:
        await queue_client.async_load()
    except QueueStoreError as err:
        raise ConfigEntryNotReady("Jellyfin Media Assistant queue storage could not be loaded") from err

    async def snapshot_loader() -> Any:
        return await load_catalog_snapshot(
            catalog_client.fetch_catalog_page,
            item_types=DEFAULT_CATALOG_MEDIA_TYPES,
            page_size=DEFAULT_CATALOG_PAGE_SIZE,
        )

    manager = CatalogManager(
        snapshot_loader=snapshot_loader,
        requested_types=DEFAULT_CATALOG_MEDIA_TYPES,
        cache_identity=f"{client.server_url.casefold()}:{connection.user_id.casefold()}",
        cache_store=CatalogCacheStore(_cache_path(hass, entry.entry_id)),
    )

    cache_loaded = await manager.async_load_cache()
    connection_info = None
    startup_used_offline_cache = False

    try:
        connection_info = await client.async_validate_connection(connection.user_id)
    except JellyfinAuthenticationError as err:
        raise ConfigEntryAuthFailed("Jellyfin rejected the configured API key") from err
    except JellyfinConnectionError as err:
        if not cache_loaded:
            raise ConfigEntryNotReady(
                "Jellyfin is unavailable and no cached catalog can be loaded"
            ) from err
        startup_used_offline_cache = True
        _LOGGER.warning(
            "Jellyfin is unavailable; starting with the cached search catalog: %s",
            err,
        )
    except JellyfinInvalidResponseError as err:
        raise ConfigEntryNotReady(
            "Jellyfin returned an invalid response while validating the configuration"
        ) from err

    if not cache_loaded:
        try:
            await manager.async_refresh()
        except CatalogRefreshError as err:
            raise ConfigEntryNotReady(
                "The initial Jellyfin search catalog could not be loaded"
            ) from err

    entry.runtime_data = JellyfinAssistRuntime(
        client=client,
        entry_id=entry.entry_id,
        catalog_manager=manager,
        connection_info=connection_info,
        user_id=connection.user_id,
        startup_used_offline_cache=startup_used_offline_cache,
        default_media_player=behavior.default_media_player,
        playback_targets=behavior.effective_playback_targets,
        queue_client=queue_client,
        queue_storage_key=queue_storage_key,
    )

    from .advancement import async_setup_queue_advancement
    from .voice_sentences import async_provision_voice_sentences

    entry.runtime_data.voice_sentence_provisioning = await async_provision_voice_sentences(hass)
    async_setup_queue_advancement(hass, entry, entry.runtime_data)

    if cache_loaded and connection_info is not None:
        entry.async_create_background_task(
            hass,
            _async_background_refresh(manager),
            f"{DOMAIN} refresh catalog",
        )

    # Home Assistant may serialize a custom config entry before its config-flow
    # handler is registered, caching supports_options=False. The handler is loaded
    # before async_setup_entry runs, so clear the public state cache here to force
    # the next frontend/API read to recalculate options support.
    entry.clear_state_cache()

    from .services import async_register_services

    await async_register_services(hass)

    return True


async def async_migrate_entry(hass: Any, entry: Any) -> bool:
    """Migrate persisted configuration to the current compatible schema."""

    version = int(getattr(entry, "version", 1))
    minor_version = int(getattr(entry, "minor_version", 1))
    if version != CONFIG_ENTRY_VERSION:
        _LOGGER.error(
            "Unsupported Jellyfin Media Assistant config-entry version %s.%s",
            version,
            minor_version,
        )
        return False

    if minor_version >= CONFIG_ENTRY_MINOR_VERSION:
        return True

    data, options = migrate_config_entry_payload(entry.data, entry.options)
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=CONFIG_ENTRY_VERSION,
        minor_version=CONFIG_ENTRY_MINOR_VERSION,
    )
    _LOGGER.info(
        "Migrated Jellyfin Media Assistant configuration to %s.%s",
        CONFIG_ENTRY_VERSION,
        CONFIG_ENTRY_MINOR_VERSION,
    )
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload one config entry; entry-owned background tasks are cancelled by HA."""

    return True


async def async_remove_entry(hass: Any, entry: Any) -> None:
    """Clean up integration-managed voice sentences after the final entry is removed."""

    remaining_entries = [
        other
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ]
    if remaining_entries:
        return

    from .voice_sentences import async_remove_managed_voice_sentences

    await async_remove_managed_voice_sentences(hass)


__all__ = [
    "_normalize_playback_targets",
    "async_migrate_entry",
    "async_remove_entry",
    "async_setup_entry",
    "async_unload_entry",
]
