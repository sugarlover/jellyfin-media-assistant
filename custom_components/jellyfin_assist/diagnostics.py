"""Diagnostics support for Jellyfin Media Assistant."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .configuration import CONFIG_ENTRY_MINOR_VERSION, CONFIG_ENTRY_VERSION
from .const import CONF_API_KEY
from .voice import (
    CUSTOM_SENTENCE_FILENAME,
    CUSTOM_SENTENCE_LANGUAGE,
    NATIVE_INTENT_TYPES,
)
from .voice_sentences import async_inspect_voice_sentences



async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: Any,
) -> dict[str, Any]:
    """Return non-secret configuration and catalog health diagnostics."""

    runtime = entry.runtime_data
    connection_info = runtime.connection_info

    registered_intents = {
        handler.intent_type
        for handler in intent.async_get(hass)
        if getattr(handler, "intent_type", None)
    }
    expected_intents = set(NATIVE_INTENT_TYPES)
    sentence_state = await async_inspect_voice_sentences(hass)
    provisioning = runtime.voice_sentence_provisioning

    return {
        "configuration_schema": {
            "stored_version": int(getattr(entry, "version", 1)),
            "stored_minor_version": int(getattr(entry, "minor_version", 1)),
            "current_version": CONFIG_ENTRY_VERSION,
            "current_minor_version": CONFIG_ENTRY_MINOR_VERSION,
        },
        "entry": async_redact_data(dict(entry.data), {CONF_API_KEY}),
        "connection": (
            {
                "server_id": connection_info.server_id,
                "server_name": connection_info.server_name,
                "server_version": connection_info.server_version,
                "user_id": connection_info.user_id,
                "user_name": connection_info.user_name,
            }
            if connection_info is not None
            else None
        ),
        "startup_used_offline_cache": runtime.startup_used_offline_cache,
        "player_configuration": {
            "default_media_player": runtime.default_media_player,
            "playback_targets": list(runtime.playback_targets),
        },
        "queue": {
            "storage": "home_assistant_store",
            "configured": runtime.queue_client is not None,
            "storage_key": runtime.queue_storage_key,
        },
        "queue_advancement": {
            "mode": "native",
            "registered_targets": list(runtime.queue_advancement_targets),
            "completion_threshold_percent": 95,
            "last_result": runtime.last_queue_advancement,
        },
        "pending_selection": {
            "storage": "integration_runtime",
            "active": isinstance(runtime.pending_selection, dict),
            "choice_count": (
                len(runtime.pending_selection.get("items", []))
                if isinstance(runtime.pending_selection, dict)
                and isinstance(runtime.pending_selection.get("items"), list)
                else 0
            ),
            "media_player": (
                runtime.pending_selection.get("media_player")
                if isinstance(runtime.pending_selection, dict)
                else None
            ),
            "operation": (
                runtime.pending_selection.get("operation")
                if isinstance(runtime.pending_selection, dict)
                else None
            ),
            "intent": (
                runtime.pending_selection.get("intent")
                if isinstance(runtime.pending_selection, dict)
                else None
            ),
        },
        "last_player_resolution": runtime.last_player_resolution,
        "voice": {
            "native_intent_handlers_expected": len(expected_intents),
            "native_intent_handlers_registered": len(
                registered_intents & expected_intents
            ),
            "all_native_intent_handlers_registered": expected_intents.issubset(
                registered_intents
            ),
            "custom_sentences_packaged": sentence_state.packaged,
            "custom_sentences_installed": sentence_state.installed,
            "custom_sentences_current": sentence_state.current,
            "custom_sentences_managed": sentence_state.managed,
            "custom_sentences_user_modified": sentence_state.user_modified,
            "custom_sentences_status": sentence_state.status,
            "custom_sentence_language": CUSTOM_SENTENCE_LANGUAGE,
            "custom_sentence_filename": CUSTOM_SENTENCE_FILENAME,
            "last_provisioning_status": (
                provisioning.status if provisioning is not None else None
            ),
            "last_reload_attempted": (
                provisioning.reload_attempted if provisioning is not None else False
            ),
            "last_reload_succeeded": (
                provisioning.reload_succeeded if provisioning is not None else False
            ),
            "last_provisioning_error": (
                provisioning.error if provisioning is not None else None
            ),
        },
        "catalog": asdict(runtime.catalog_manager.diagnostics()),
    }
