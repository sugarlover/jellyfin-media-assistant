"""Voice-intent request normalization for Jellyfin Media Assistant."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any, Final

from .const import (
    DOMAIN,
    SERVICE_MEDIA_ORCHESTRATOR,
    SERVICE_PLAY_PENDING_MEDIA,
    SERVICE_QUEUE_COMMAND,
    SERVICE_RESUME_PENDING_MEDIA_REQUEST,
)

CUSTOM_SENTENCE_LANGUAGE: Final = "en"
CUSTOM_SENTENCE_FILENAME: Final = "jellyfin_assist_media.yaml"

INTENT_QUEUE_NEXT: Final = "JellyfinAssistQueueNext"
INTENT_QUEUE_WHATS_PLAYING: Final = "JellyfinAssistQueueWhatsPlaying"
INTENT_QUEUE_WHAT_JUST_PLAYED: Final = "JellyfinAssistQueueWhatJustPlayed"
INTENT_QUEUE_STATUS: Final = "JellyfinAssistQueueStatus"
INTENT_QUEUE_CLEAR: Final = "JellyfinAssistQueueClear"
INTENT_QUEUE_SHUFFLE: Final = "JellyfinAssistQueueShuffle"
INTENT_QUEUE_REPEAT_ITEM_ENABLE: Final = "JellyfinAssistQueueRepeatItemEnable"
INTENT_QUEUE_REPEAT_QUEUE_ENABLE: Final = "JellyfinAssistQueueRepeatQueueEnable"
INTENT_QUEUE_REPEAT_OFF: Final = "JellyfinAssistQueueRepeatOff"
INTENT_QUEUE_REPEAT_ITEM_TOGGLE: Final = "JellyfinAssistQueueRepeatItemToggle"
INTENT_QUEUE_REPEAT_QUEUE_TOGGLE: Final = "JellyfinAssistQueueRepeatQueueToggle"
INTENT_MUSIC_ALBUM_PLAY: Final = "JellyfinAssistMusicAlbumPlay"
INTENT_MUSIC_ALBUM_ADD: Final = "JellyfinAssistMusicAlbumAdd"
INTENT_MUSIC_SONG_PLAY: Final = "JellyfinAssistMusicSongPlay"
INTENT_MUSIC_SONG_ADD: Final = "JellyfinAssistMusicSongAdd"
INTENT_MUSIC_ARTIST_PLAY: Final = "JellyfinAssistMusicArtistPlay"
INTENT_MUSIC_ARTIST_ADD: Final = "JellyfinAssistMusicArtistAdd"
INTENT_MOVIE_PLAY: Final = "JellyfinAssistMoviePlay"
INTENT_MOVIE_ADD: Final = "JellyfinAssistMovieAdd"
INTENT_EPISODE_TITLE_PLAY: Final = "JellyfinAssistEpisodeTitlePlay"
INTENT_EPISODE_TITLE_ADD: Final = "JellyfinAssistEpisodeTitleAdd"
INTENT_SHOW_PLAY: Final = "JellyfinAssistShowPlay"
INTENT_SHOW_ADD: Final = "JellyfinAssistShowAdd"
INTENT_MEDIA_PLAY: Final = "JellyfinAssistMediaPlay"
INTENT_MEDIA_SELECT: Final = "JellyfinAssistMediaSelect"
INTENT_MEDIA_PLAYER_SELECT: Final = "JellyfinAssistMediaPlayerSelect"
INTENT_MEDIA_ADD: Final = "JellyfinAssistMediaAdd"

NATIVE_INTENT_TYPES: Final = (
    INTENT_QUEUE_NEXT,
    INTENT_QUEUE_WHATS_PLAYING,
    INTENT_QUEUE_WHAT_JUST_PLAYED,
    INTENT_QUEUE_STATUS,
    INTENT_QUEUE_CLEAR,
    INTENT_QUEUE_SHUFFLE,
    INTENT_QUEUE_REPEAT_ITEM_ENABLE,
    INTENT_QUEUE_REPEAT_QUEUE_ENABLE,
    INTENT_QUEUE_REPEAT_OFF,
    INTENT_QUEUE_REPEAT_ITEM_TOGGLE,
    INTENT_QUEUE_REPEAT_QUEUE_TOGGLE,
    INTENT_MUSIC_ALBUM_PLAY,
    INTENT_MUSIC_ALBUM_ADD,
    INTENT_MUSIC_SONG_PLAY,
    INTENT_MUSIC_SONG_ADD,
    INTENT_MUSIC_ARTIST_PLAY,
    INTENT_MUSIC_ARTIST_ADD,
    INTENT_MOVIE_PLAY,
    INTENT_MOVIE_ADD,
    INTENT_EPISODE_TITLE_PLAY,
    INTENT_EPISODE_TITLE_ADD,
    INTENT_SHOW_PLAY,
    INTENT_SHOW_ADD,
    INTENT_MEDIA_PLAY,
    INTENT_MEDIA_SELECT,
    INTENT_MEDIA_PLAYER_SELECT,
    INTENT_MEDIA_ADD,
)

INTENT_DESCRIPTIONS: Final[dict[str, str]] = {
    INTENT_QUEUE_NEXT: "Advance to the next item in a Jellyfin Media Assistant queue.",
    INTENT_QUEUE_WHATS_PLAYING: "Report what is currently playing on a Jellyfin Media Assistant player.",
    INTENT_QUEUE_WHAT_JUST_PLAYED: "Report the most recently completed Jellyfin Media Assistant queue item.",
    INTENT_QUEUE_STATUS: "Report the current Jellyfin Media Assistant queue status.",
    INTENT_QUEUE_CLEAR: "Clear a Jellyfin Media Assistant queue and queue history.",
    INTENT_QUEUE_SHUFFLE: "Shuffle upcoming Jellyfin Media Assistant queue items.",
    INTENT_QUEUE_REPEAT_ITEM_ENABLE: "Enable repeat-item mode for a Jellyfin Media Assistant queue.",
    INTENT_QUEUE_REPEAT_QUEUE_ENABLE: "Enable repeat-queue mode for a Jellyfin Media Assistant queue.",
    INTENT_QUEUE_REPEAT_OFF: "Disable Jellyfin Media Assistant repeat modes.",
    INTENT_QUEUE_REPEAT_ITEM_TOGGLE: "Toggle Jellyfin Media Assistant repeat-item mode.",
    INTENT_QUEUE_REPEAT_QUEUE_TOGGLE: "Toggle Jellyfin Media Assistant repeat-queue mode.",
    INTENT_MUSIC_ALBUM_PLAY: "Play a specific Jellyfin music album.",
    INTENT_MUSIC_ALBUM_ADD: "Add a specific Jellyfin music album to the queue.",
    INTENT_MUSIC_SONG_PLAY: "Play a specific Jellyfin song.",
    INTENT_MUSIC_SONG_ADD: "Add a specific Jellyfin song to the queue.",
    INTENT_MUSIC_ARTIST_PLAY: "Play available Jellyfin songs by a specific artist.",
    INTENT_MUSIC_ARTIST_ADD: "Add available Jellyfin songs by a specific artist to the queue.",
    INTENT_MOVIE_PLAY: "Play a specific Jellyfin movie.",
    INTENT_MOVIE_ADD: "Add a specific Jellyfin movie to the queue.",
    INTENT_EPISODE_TITLE_PLAY: "Play a Jellyfin TV episode by episode title.",
    INTENT_EPISODE_TITLE_ADD: "Add a Jellyfin TV episode by episode title to the queue.",
    INTENT_SHOW_PLAY: "Play a Jellyfin show, season, or episode.",
    INTENT_SHOW_ADD: "Add a Jellyfin show, season, or episode to the queue.",
    INTENT_MEDIA_PLAY: "Play a Jellyfin media request.",
    INTENT_MEDIA_SELECT: "Select a numbered pending Jellyfin media result.",
    INTENT_MEDIA_PLAYER_SELECT: "Resume a pending Jellyfin request with a spoken media player.",
    INTENT_MEDIA_ADD: "Add a Jellyfin media request to the queue.",
}

_QUEUE_OPERATIONS: Final[dict[str, str]] = {
    INTENT_QUEUE_NEXT: "queue_next",
    INTENT_QUEUE_WHATS_PLAYING: "whats_playing",
    INTENT_QUEUE_WHAT_JUST_PLAYED: "what_just_played",
    INTENT_QUEUE_STATUS: "queue_status",
    INTENT_QUEUE_CLEAR: "queue_clear",
    INTENT_QUEUE_SHUFFLE: "queue_shuffle",
    INTENT_QUEUE_REPEAT_ITEM_ENABLE: "repeat_item_enable",
    INTENT_QUEUE_REPEAT_QUEUE_ENABLE: "repeat_queue_enable",
    INTENT_QUEUE_REPEAT_OFF: "repeat_off",
    INTENT_QUEUE_REPEAT_ITEM_TOGGLE: "repeat_item_toggle",
    INTENT_QUEUE_REPEAT_QUEUE_TOGGLE: "repeat_queue_toggle",
}

_MEDIA_REQUESTS: Final[dict[str, tuple[str, str | None, str]]] = {
    INTENT_MUSIC_ALBUM_PLAY: ("album_request", "MusicAlbum", "play"),
    INTENT_MUSIC_ALBUM_ADD: ("album_request", "MusicAlbum", "add"),
    INTENT_MUSIC_SONG_PLAY: ("song_request", "Audio", "play"),
    INTENT_MUSIC_SONG_ADD: ("song_request", "Audio", "add"),
    INTENT_MUSIC_ARTIST_PLAY: ("artist_request", "MusicArtist", "play"),
    INTENT_MUSIC_ARTIST_ADD: ("artist_request", "MusicArtist", "add"),
    INTENT_MOVIE_PLAY: ("movie_request", "Movie", "play"),
    INTENT_MOVIE_ADD: ("movie_request", "Movie", "add"),
    INTENT_EPISODE_TITLE_PLAY: ("episode_request", "Episode", "play"),
    INTENT_EPISODE_TITLE_ADD: ("episode_request", "Episode", "add"),
    INTENT_SHOW_PLAY: ("show_request", "Series", "play"),
    INTENT_SHOW_ADD: ("show_request", "Series", "add"),
    INTENT_MEDIA_PLAY: ("media", None, "play"),
    INTENT_MEDIA_ADD: ("media", None, "add"),
}

_SPLIT_ARTIST_INTENTS: Final = {
    INTENT_MUSIC_ALBUM_PLAY,
    INTENT_MUSIC_ALBUM_ADD,
    INTENT_MUSIC_SONG_PLAY,
    INTENT_MUSIC_SONG_ADD,
}
_EPISODE_TITLE_INTENTS: Final = {
    INTENT_EPISODE_TITLE_PLAY,
    INTENT_EPISODE_TITLE_ADD,
}
_SEASON_EPISODE_INTENTS: Final = {
    INTENT_SHOW_PLAY,
    INTENT_SHOW_ADD,
    INTENT_MEDIA_PLAY,
    INTENT_MEDIA_ADD,
}

_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_PUNCTUATION_RE = re.compile(r"[.!?,;:]+$")
_BY_RE = re.compile(r"^(.+)\s+by\s+(.+)$", re.IGNORECASE)
_FROM_RE = re.compile(r"\s+from\s+", re.IGNORECASE)
_SERIES_PREFIX_RE = re.compile(
    r"^(?:the\s+)?(?:show|series|tv show|television show)\s+",
    re.IGNORECASE,
)


class VoiceIntentValidationError(ValueError):
    """Raised when a native voice intent is missing required request data."""


@dataclass(frozen=True, slots=True)
class VoiceScriptCall:
    """One canonical Home Assistant action produced by a native voice intent."""

    service: str
    data: dict[str, Any]
    domain: str = DOMAIN


def clean_request_text(value: Any) -> str:
    """Match the request cleanup previously performed by intent_script YAML."""

    text = "" if value is None else str(value)
    text = _WHITESPACE_RE.sub(" ", text.strip())
    text = _TRAILING_PUNCTUATION_RE.sub("", text).strip()
    return text


def _optional_text(slots: Mapping[str, Any], name: str) -> str:
    value = slots.get(name)
    return "" if value in (None, "") else str(value).strip()


def _optional_positive_int(slots: Mapping[str, Any], name: str) -> int | None:
    value = slots.get(name)
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _required_clean_request(slots: Mapping[str, Any], name: str) -> str:
    value = clean_request_text(slots.get(name))
    if not value:
        raise VoiceIntentValidationError(f"Missing required voice slot: {name}")
    return value


def _split_artist_request(request: str) -> tuple[str, str]:
    match = _BY_RE.match(request)
    if match is None:
        return request, ""
    return match.group(1).strip(), match.group(2).strip()


def _split_episode_request(request: str) -> tuple[str, str]:
    match = _FROM_RE.search(request)
    if match is None:
        return request, ""

    episode = request[: match.start()].strip()
    # The historical Jinja expression used a greedy prefix removal for the
    # series side, so preserve the final " from " delimiter if more than one
    # appears in the spoken request.
    matches = list(_FROM_RE.finditer(request))
    series = request[matches[-1].end() :].strip()
    series = _SERIES_PREFIX_RE.sub("", series).strip()
    return episode, series


def _requested_player(slots: Mapping[str, Any]) -> str:
    return _optional_text(slots, "media_player_request") or _optional_text(
        slots, "media_player"
    )


def build_voice_script_call(
    intent_type: str,
    slots: Mapping[str, Any],
) -> VoiceScriptCall:
    """Translate one canonical voice intent into a native Jellyfin Assist action."""

    if intent_type in _QUEUE_OPERATIONS:
        return VoiceScriptCall(
            SERVICE_QUEUE_COMMAND,
            {
                "operation": _QUEUE_OPERATIONS[intent_type],
                "media_player": _requested_player(slots),
            },
            domain=DOMAIN,
        )

    if intent_type == INTENT_MEDIA_SELECT:
        selection = _optional_positive_int(slots, "selection")
        if selection is None:
            raise VoiceIntentValidationError("Please provide a valid result number.")
        return VoiceScriptCall(
            SERVICE_PLAY_PENDING_MEDIA,
            {"selection": selection},
            domain=DOMAIN,
        )

    if intent_type == INTENT_MEDIA_PLAYER_SELECT:
        player = _required_clean_request(slots, "media_player_request")
        player_kind = clean_request_text(slots.get("media_player_kind"))
        if player_kind:
            player = f"{player} {player_kind}".strip()
        return VoiceScriptCall(
            SERVICE_RESUME_PENDING_MEDIA_REQUEST,
            {"media_player": player},
            domain=DOMAIN,
        )

    media_spec = _MEDIA_REQUESTS.get(intent_type)
    if media_spec is None:
        raise VoiceIntentValidationError(f"Unsupported voice intent: {intent_type}")

    request_slot, media_type, operation = media_spec
    request = _required_clean_request(slots, request_slot)
    artist = ""
    series = ""

    if intent_type in _SPLIT_ARTIST_INTENTS:
        request, artist = _split_artist_request(request)
    elif intent_type in _EPISODE_TITLE_INTENTS:
        request, series = _split_episode_request(request)

    data: dict[str, Any] = {
        "query": request,
        "media_player": _optional_text(slots, "media_player"),
        "operation": operation,
    }
    if media_type is not None:
        data["media_type"] = media_type
    if artist:
        data["artist"] = artist
    elif intent_type in _SPLIT_ARTIST_INTENTS:
        data["artist"] = ""
    if intent_type in _EPISODE_TITLE_INTENTS:
        data["series"] = series
    if intent_type in _SEASON_EPISODE_INTENTS:
        data["season"] = _optional_positive_int(slots, "season")
        data["episode"] = _optional_positive_int(slots, "episode")

    return VoiceScriptCall(SERVICE_MEDIA_ORCHESTRATOR, data, domain=DOMAIN)


__all__ = [
    "CUSTOM_SENTENCE_FILENAME",
    "CUSTOM_SENTENCE_LANGUAGE",
    "INTENT_DESCRIPTIONS",
    "NATIVE_INTENT_TYPES",
    "VoiceIntentValidationError",
    "VoiceScriptCall",
    "build_voice_script_call",
    "clean_request_text",
]
