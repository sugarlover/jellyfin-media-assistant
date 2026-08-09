"""Runtime data owned by one Jellyfin Media Assistant config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .api import JellyfinApiClient, JellyfinConnectionInfo
from .queue_store import NativeQueueStore
from .search import CatalogManager

if TYPE_CHECKING:
    from .voice_sentences import VoiceSentenceState


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
    voice_sentence_provisioning: "VoiceSentenceState | None" = None


__all__ = ["JellyfinAssistRuntime"]
