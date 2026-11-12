"""Runtime data owned by one Jellyfin Media Assistant config entry."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .api import JellyfinApiClient, JellyfinConnectionInfo
from .queue_store import NativeQueueStore
from .search import CatalogManager

if TYPE_CHECKING:
    from .voice_sentences import VoiceSentenceState

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class JellyfinAssistRuntime:
    """Objects kept alive for the lifetime of one loaded config entry."""

    client: JellyfinApiClient
    catalog_manager: CatalogManager
    connection_info: JellyfinConnectionInfo | None
    entry_id: str = ""
    user_id: str = ""
    startup_used_offline_cache: bool = False
    default_media_player: str | None = None
    playback_targets: tuple[str, ...] = ()
    queue_client: NativeQueueStore | None = None
    queue_storage_key: str | None = None
    pending_media_request: dict[str, Any] | None = None
    pending_selection: dict[str, Any] | None = None
    last_player_resolution: dict[str, Any] | None = None
    queue_advancement_targets: tuple[str, ...] = ()
    last_queue_advancement: dict[str, Any] | None = None
    playback_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    playback_session_listeners: dict[str, Any] = field(default_factory=dict)
    voice_sentence_provisioning: "VoiceSentenceState | None" = None
    _config_entry: "Any | None" = field(default=None, repr=False)
    _hass: "Any | None" = field(default=None, repr=False)

    def async_bind_entry(self, config_entry: Any, hass: Any) -> None:
        """Bind the owning config entry and HomeAssistant core.

        Stored on the runtime so the re-auth trigger below can reference
        ``ConfigEntry.async_start_reauth`` without the advancement module
        reaching for the HA core directly.
        """

        self._config_entry = config_entry
        self._hass = hass

    async def async_trigger_reauth(self) -> None:
        """Start the config-entry re-authentication flow.

        Called when a playback-position write is rejected (401) so the
        stored user access token can be re-minted. ``ConfigEntry.async_start_reauth``
        is a synchronous method that spawns a background reauth flow task;
        this coroutine wrapper lets ``api.py`` do ``await _async_auth_refresh()``
        per the c90cec8 contract. Best-effort: a failure here (already
        reauthing, no flow manager, etc.) is logged and swallowed so it
        cannot break the advancement sync loop.
        """

        entry = self._config_entry
        if entry is None:
            _LOGGER.warning(
                "No config entry bound; cannot trigger reauth for entry %s",
                self.entry_id,
            )
            return
        try:
            entry.async_start_reauth(self._hass)
        except Exception:  # noqa: BLE001 - best-effort trigger, never raise into the sync loop
            _LOGGER.warning(
                "Could not start re-authentication for %s; skipping",
                getattr(entry, "entry_id", "<unknown>"),
                exc_info=True,
            )


__all__ = ["JellyfinAssistRuntime"]
