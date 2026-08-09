"""Constants for the Jellyfin Media Assistant integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "jellyfin_assist"
NAME: Final = "Jellyfin Media Assistant"
VERSION: Final = "0.1.0-beta.1"

CONF_SERVER_URL: Final = "server_url"
CONF_API_KEY: Final = "api_key"
CONF_USER_ID: Final = "user_id"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_DEFAULT_MEDIA_PLAYER: Final = "default_media_player"
CONF_PLAYBACK_TARGETS: Final = "playback_targets"
# Retired in schema 1.3; retained only so old config entries can be migrated.
CONF_QUEUE_SERVICE_URL: Final = "queue_service_url"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_QUERY: Final = "query"
ATTR_MEDIA_TYPE: Final = "media_type"
ATTR_ARTIST: Final = "artist"
ATTR_ALBUM: Final = "album"
ATTR_SERIES: Final = "series"
ATTR_YEAR: Final = "year"
ATTR_OVERWRITE_USER_MODIFIED: Final = "overwrite_user_modified"
ATTR_MEDIA_PLAYER: Final = "media_player"
ATTR_MEDIA_PLAYER_NAME: Final = "media_player_name"
ATTR_OPERATION: Final = "operation"
ATTR_SEASON: Final = "season"
ATTR_EPISODE: Final = "episode"
ATTR_ITEM_ID: Final = "item_id"
ATTR_ENTITY_ID: Final = "entity_id"
ATTR_SERIES_ID: Final = "series_id"
ATTR_ALBUM_ID: Final = "album_id"
ATTR_ARTIST_ID: Final = "artist_id"
ATTR_EPISODE_TITLE: Final = "episode_title"
ATTR_REPEAT_ITEM: Final = "repeat_item"
ATTR_REPEAT_QUEUE: Final = "repeat_queue"
ATTR_ID: Final = "id"
ATTR_NAME: Final = "name"
ATTR_TYPE: Final = "type"
ATTR_SELECTION: Final = "selection"

PLAYER_RESOLUTION_OPERATIONS: Final = (
    "play",
    "add",
    "queue_next",
    "whats_playing",
    "what_just_played",
    "queue_status",
    "queue_clear",
    "queue_shuffle",
    "repeat_item_enable",
    "repeat_queue_enable",
    "repeat_off",
    "repeat_item_toggle",
    "repeat_queue_toggle",
)
QUEUE_PLAYER_OPERATIONS: Final = frozenset(PLAYER_RESOLUTION_OPERATIONS[2:])

SERVICE_SEARCH: Final = "search"
SERVICE_REFRESH_CATALOG: Final = "refresh_catalog"
SERVICE_PLAY_ON_CHROMECAST: Final = "play_on_chromecast"
SERVICE_GET_ITEM: Final = "get_item"
SERVICE_RESOLVE_MEDIA_PLAYER: Final = "resolve_media_player"
SERVICE_RESUME_MEDIA_REQUEST: Final = "resume_media_request"
SERVICE_SEARCH_SEASON: Final = "search_season"
SERVICE_SEARCH_EPISODE: Final = "search_episode"
SERVICE_SEARCH_EPISODE_TITLE: Final = "search_episode_title"
SERVICE_GET_ALBUM_TRACKS: Final = "get_album_tracks"
SERVICE_GET_ARTIST_TRACKS: Final = "get_artist_tracks"
SERVICE_QUEUE_GET: Final = "queue_get"
SERVICE_QUEUE_ADD: Final = "queue_add"
SERVICE_QUEUE_NEXT: Final = "queue_next"
SERVICE_QUEUE_CLEAR: Final = "queue_clear"
SERVICE_QUEUE_SET_REPEAT: Final = "queue_set_repeat"
SERVICE_QUEUE_SHUFFLE: Final = "queue_shuffle"
SERVICE_QUEUE_COMMAND: Final = "queue_command"
SERVICE_MEDIA_ORCHESTRATOR: Final = "media_orchestrator"
SERVICE_PLAY_PENDING_MEDIA: Final = "play_pending_media"
SERVICE_RESUME_PENDING_MEDIA_REQUEST: Final = "resume_pending_media_request"
SERVICE_REPAIR_VOICE_SENTENCES: Final = "repair_voice_sentences"

DEFAULT_VERIFY_SSL: Final = True
DEFAULT_REQUEST_TIMEOUT_SECONDS: Final = 20.0
DEFAULT_CATALOG_PAGE_SIZE: Final = 500
MAX_QUERY_LENGTH: Final = 300
MAX_CONTEXT_LENGTH: Final = 200
MIN_YEAR: Final = 1800
MAX_YEAR: Final = 3000

CACHE_DIRECTORY: Final = ".storage/jellyfin_assist"
CACHE_FILENAME_PREFIX: Final = "catalog"
