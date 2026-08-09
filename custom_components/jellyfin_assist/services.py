"""Home Assistant action registration for Jellyfin Media Assistant."""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging
from typing import Any, cast

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .action import (
    CatalogUnavailableError,
    SearchActionValidationError,
    execute_search_action,
    parse_search_action_request,
)
from .const import (
    ATTR_ALBUM,
    ATTR_ALBUM_ID,
    ATTR_ARTIST,
    ATTR_ARTIST_ID,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_MEDIA_TYPE,
    ATTR_MEDIA_PLAYER,
    ATTR_MEDIA_PLAYER_NAME,
    ATTR_OPERATION,
    ATTR_OVERWRITE_USER_MODIFIED,
    ATTR_QUERY,
    ATTR_REPEAT_ITEM,
    ATTR_REPEAT_QUEUE,
    ATTR_EPISODE,
    ATTR_EPISODE_TITLE,
    ATTR_ENTITY_ID,
    ATTR_ID,
    ATTR_ITEM_ID,
    ATTR_SELECTION,
    ATTR_NAME,
    ATTR_SEASON,
    ATTR_SERIES,
    ATTR_SERIES_ID,
    ATTR_TYPE,
    ATTR_YEAR,
    DOMAIN,
    MAX_YEAR,
    MIN_YEAR,
    PLAYER_RESOLUTION_OPERATIONS,
    QUEUE_PLAYER_OPERATIONS,
    SERVICE_GET_ALBUM_TRACKS,
    SERVICE_GET_ARTIST_TRACKS,
    SERVICE_GET_ITEM,
    SERVICE_PLAY_ON_CHROMECAST,
    SERVICE_QUEUE_ADD,
    SERVICE_QUEUE_CLEAR,
    SERVICE_QUEUE_GET,
    SERVICE_QUEUE_NEXT,
    SERVICE_QUEUE_SET_REPEAT,
    SERVICE_QUEUE_SHUFFLE,
    SERVICE_QUEUE_COMMAND,
    SERVICE_MEDIA_ORCHESTRATOR,
    SERVICE_PLAY_PENDING_MEDIA,
    SERVICE_RESUME_PENDING_MEDIA_REQUEST,
    SERVICE_REPAIR_VOICE_SENTENCES,
    SERVICE_RESOLVE_MEDIA_PLAYER,
    SERVICE_RESUME_MEDIA_REQUEST,
    SERVICE_SEARCH_EPISODE,
    SERVICE_SEARCH_EPISODE_TITLE,
    SERVICE_SEARCH_SEASON,
    SERVICE_SEARCH,
)
from .player_matching import (
    PlayerCandidate,
    PlayerMatch,
    recover_trailing_player,
    resolve_player_text,
)
from .runtime import JellyfinAssistRuntime
from .item_lookup import async_get_native_item
from .playback import (
    ChromecastPlaybackError,
    NoNextUpEpisodeError,
    async_play_on_chromecast,
)
from .api import JellyfinApiError
from .queue_store import QueueStoreError
from .queue_control import async_queue_command
from .orchestration import (
    async_media_orchestrator,
    async_play_pending_media,
    async_resume_pending_media_request,
)
from .search import SUPPORTED_CATALOG_MEDIA_TYPES
from .voice_sentences import async_provision_voice_sentences

_LOGGER = logging.getLogger(__name__)


_SEARCH_FIELDS: dict[Any, Any] = {
    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    vol.Required(ATTR_QUERY): cv.string,
    vol.Optional(ATTR_MEDIA_TYPE): vol.In(sorted(SUPPORTED_CATALOG_MEDIA_TYPES)),
    vol.Optional(ATTR_ARTIST): cv.string,
    vol.Optional(ATTR_ALBUM): cv.string,
    vol.Optional(ATTR_SERIES): cv.string,
    vol.Optional(ATTR_YEAR): vol.All(
        vol.Coerce(int),
        vol.Range(min=MIN_YEAR, max=MAX_YEAR),
    ),
}

SEARCH_ACTION_SCHEMA = vol.Schema(_SEARCH_FIELDS)
_MEDIA_REQUEST_CONTEXT_FIELDS: dict[Any, Any] = {
    vol.Optional(ATTR_QUERY): cv.string,
    vol.Optional(ATTR_OPERATION): vol.In(PLAYER_RESOLUTION_OPERATIONS),
    vol.Optional(ATTR_MEDIA_TYPE): cv.string,
    vol.Optional(ATTR_ARTIST): cv.string,
    vol.Optional(ATTR_ALBUM): cv.string,
    vol.Optional(ATTR_SERIES): cv.string,
    vol.Optional(ATTR_YEAR): object,
    vol.Optional(ATTR_SEASON): object,
    vol.Optional(ATTR_EPISODE): object,
}


GET_ITEM_ACTION_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_ITEM_ID): cv.string,
    }
)

PLAY_ON_CHROMECAST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_ENTITY_ID): cv.string,
        vol.Required(ATTR_ITEM_ID): cv.string,
    }
)

RESOLVE_MEDIA_PLAYER_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_MEDIA_PLAYER): cv.string,
        **_MEDIA_REQUEST_CONTEXT_FIELDS,
    }
)

RESUME_MEDIA_REQUEST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MEDIA_PLAYER): cv.string,
    }
)

SEARCH_SEASON_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SERIES_ID): cv.string,
        vol.Required(ATTR_SEASON): vol.All(vol.Coerce(int), vol.Range(min=0, max=1000)),
    }
)

SEARCH_EPISODE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SERIES_ID): cv.string,
        vol.Required(ATTR_SEASON): vol.All(vol.Coerce(int), vol.Range(min=0, max=1000)),
        vol.Required(ATTR_EPISODE): vol.All(vol.Coerce(int), vol.Range(min=0, max=10000)),
    }
)

SEARCH_EPISODE_TITLE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SERIES_ID): cv.string,
        vol.Required(ATTR_EPISODE_TITLE): cv.string,
    }
)

GET_ALBUM_TRACKS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_ALBUM_ID): cv.string,
    }
)

GET_ARTIST_TRACKS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_ARTIST_ID): cv.string,
    }
)

QUEUE_GET_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MEDIA_PLAYER): cv.string,
    }
)

QUEUE_ADD_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MEDIA_PLAYER): cv.string,
        vol.Required(ATTR_ID): cv.string,
        vol.Optional(ATTR_NAME): object,
        vol.Optional(ATTR_TYPE): object,
        vol.Optional(ATTR_ARTIST): object,
        vol.Optional(ATTR_ALBUM): object,
        vol.Optional(ATTR_SERIES): object,
        vol.Optional(ATTR_SEASON): object,
        vol.Optional(ATTR_EPISODE): object,
    }
)

QUEUE_SET_REPEAT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MEDIA_PLAYER): cv.string,
        vol.Required(ATTR_REPEAT_ITEM): cv.boolean,
        vol.Required(ATTR_REPEAT_QUEUE): cv.boolean,
    }
)

QUEUE_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_OPERATION): vol.In(sorted(QUEUE_PLAYER_OPERATIONS)),
        vol.Optional(ATTR_MEDIA_PLAYER): cv.string,
        vol.Optional(ATTR_MEDIA_PLAYER_NAME): cv.string,
    }
)

MEDIA_ORCHESTRATOR_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_QUERY): cv.string,
        vol.Optional(ATTR_MEDIA_PLAYER): cv.string,
        vol.Optional(ATTR_MEDIA_PLAYER_NAME): cv.string,
        vol.Optional(ATTR_OPERATION, default="play"): vol.In(("play", "add")),
        vol.Optional(ATTR_MEDIA_TYPE): cv.string,
        vol.Optional(ATTR_ARTIST): cv.string,
        vol.Optional(ATTR_YEAR): object,
        vol.Optional(ATTR_SERIES): cv.string,
        vol.Optional(ATTR_SEASON): object,
        vol.Optional(ATTR_EPISODE): object,
    }
)

PLAY_PENDING_MEDIA_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SELECTION): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    }
)

RESUME_PENDING_MEDIA_REQUEST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MEDIA_PLAYER): cv.string,
    }
)


REPAIR_VOICE_SENTENCES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_OVERWRITE_USER_MODIFIED, default=False): cv.boolean,
    }
)


def _validation_error(key: str, message: str) -> ServiceValidationError:
    """Create a user-facing, translatable service validation failure."""

    return ServiceValidationError(
        message,
        translation_domain=DOMAIN,
        translation_key=key,
    )


def _resolve_runtime(hass: HomeAssistant, call: ServiceCall) -> JellyfinAssistRuntime:
    """Resolve a loaded config entry, inferring it only when unambiguous."""

    requested_entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if requested_entry_id:
        entry = hass.config_entries.async_get_entry(requested_entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise _validation_error(
                "config_entry_not_found",
                "The selected Jellyfin Media Assistant configuration was not found.",
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise _validation_error(
                "config_entry_not_loaded",
                "The selected Jellyfin Media Assistant configuration is not loaded.",
            )
        return cast(JellyfinAssistRuntime, entry.runtime_data)

    loaded_entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if len(loaded_entries) == 1:
        return cast(JellyfinAssistRuntime, loaded_entries[0].runtime_data)

    raise _validation_error(
        "config_entry_required",
        "Choose a Jellyfin Media Assistant configuration.",
    )


def _parse_and_execute(
    runtime: JellyfinAssistRuntime,
    call: ServiceCall,
) -> tuple[Any, ServiceResponse]:
    request = parse_search_action_request(call.data)
    return request, execute_search_action(runtime, request)


def _clean_text(value: Any) -> str:
    """Return a trimmed optional text value."""

    return str(value).strip() if value not in (None, "") else ""


def _clean_optional_int(value: Any) -> int | None:
    """Return a positive integer or None for empty request context."""

    if value in (None, "", "None", "none"):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _media_player_is_available(hass: HomeAssistant, entity_id: str) -> bool:
    """Validate a media-player entity without requiring it to be powered on."""

    if not entity_id.startswith("media_player."):
        return False
    states = getattr(hass, "states", None)
    if states is None or not hasattr(states, "get"):
        return True
    return states.get(entity_id) is not None


def _request_context_from_call(call: ServiceCall) -> dict[str, Any]:
    """Build normalized request context used by recovery and player follow-ups."""

    return {
        ATTR_QUERY: _clean_text(call.data.get(ATTR_QUERY)),
        ATTR_OPERATION: _clean_text(call.data.get(ATTR_OPERATION)) or "play",
        ATTR_MEDIA_TYPE: _clean_text(call.data.get(ATTR_MEDIA_TYPE)) or None,
        ATTR_ARTIST: _clean_text(call.data.get(ATTR_ARTIST)),
        ATTR_ALBUM: _clean_text(call.data.get(ATTR_ALBUM)),
        ATTR_SERIES: _clean_text(call.data.get(ATTR_SERIES)),
        ATTR_YEAR: _clean_optional_int(call.data.get(ATTR_YEAR)),
        ATTR_SEASON: _clean_optional_int(call.data.get(ATTR_SEASON)),
        ATTR_EPISODE: _clean_optional_int(call.data.get(ATTR_EPISODE)),
    }


def _pending_request_from_context(context: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return a storable media or queue request for a player follow-up."""

    operation = _clean_text(context.get(ATTR_OPERATION)) or "play"
    if not _clean_text(context.get(ATTR_QUERY)) and operation not in QUEUE_PLAYER_OPERATIONS:
        return None
    return dict(context)


def _state_name(state: Any, entity_id: str) -> str:
    """Return the best currently available display name for an entity."""

    attributes = getattr(state, "attributes", {}) or {}
    friendly_name = _clean_text(attributes.get("friendly_name"))
    if friendly_name:
        return friendly_name
    return entity_id.removeprefix("media_player.").replace("_", " ").title()


def _candidate_entity_ids(
    hass: HomeAssistant,
    runtime: JellyfinAssistRuntime,
) -> tuple[str, ...]:
    """Return allowed active player IDs, preserving configured target order."""

    if runtime.playback_targets:
        return tuple(
            entity_id
            for entity_id in runtime.playback_targets
            if _media_player_is_available(hass, entity_id)
        )

    states = getattr(hass, "states", None)
    if states is None or not hasattr(states, "async_all"):
        seeds = [runtime.default_media_player] if runtime.default_media_player else []
        return tuple(entity_id for entity_id in seeds if entity_id)
    return tuple(
        state.entity_id
        for state in states.async_all("media_player")
        if getattr(state, "entity_id", "").startswith("media_player.")
    )


def _player_candidates(
    hass: HomeAssistant,
    runtime: JellyfinAssistRuntime,
) -> tuple[PlayerCandidate, ...]:
    """Read native Home Assistant names and ordered aliases for allowed targets."""

    registry = er.async_get(hass)
    states = getattr(hass, "states", None)
    candidates: list[PlayerCandidate] = []
    for entity_id in _candidate_entity_ids(hass, runtime):
        state = states.get(entity_id) if states is not None and hasattr(states, "get") else None
        name = _state_name(state, entity_id)
        aliases: list[str] = []
        entry = registry.async_get(entity_id) if registry is not None else None
        if entry is not None:
            aliases.extend(er.async_get_entity_aliases(hass, entry, allow_empty=False))
        aliases.append(entity_id.removeprefix("media_player.").replace("_", " "))
        candidates.append(
            PlayerCandidate(
                entity_id=entity_id,
                name=name,
                aliases=tuple(dict.fromkeys(alias for alias in aliases if alias)),
            )
        )
    return tuple(candidates)


def _resolution_diagnostics(
    match: PlayerMatch | None,
    *,
    source: str | None,
    trailing_recovery_used: bool,
    default_used: bool,
    recovery_field: str | None = None,
) -> dict[str, Any]:
    diagnostics = (
        match.as_dict()
        if match is not None
        else {
            "status": "not_attempted",
            "original_player_text": None,
            "matched_entity_id": None,
            "matched_name": None,
            "matched_alias": None,
            "match_method": None,
            "confidence": None,
            "candidates": [],
        }
    )
    diagnostics.update(
        {
            "source": source,
            "trailing_recovery_used": trailing_recovery_used,
            "recovery_field": recovery_field,
            "default_used": default_used,
        }
    )
    return diagnostics


def _remember_resolution(
    runtime: JellyfinAssistRuntime,
    diagnostics: Mapping[str, Any],
) -> None:
    runtime.last_player_resolution = dict(diagnostics)


def _response_player_name(match: PlayerMatch, *, source: str) -> str:
    """Choose the clearest user-facing player name for one resolution."""

    if source == "default" or match.method in {
        "token_subset",
        "fuzzy_alias",
        "configured_default",
    }:
        return _clean_text(match.matched_name) or _clean_text(match.matched_alias)
    alias = _clean_text(match.matched_alias)
    if alias and not alias.startswith("media_player."):
        return alias
    return _clean_text(match.matched_name) or alias


async def async_handle_resolve_media_player(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Resolve explicit text, a swallowed suffix, or the configured default."""

    runtime = _resolve_runtime(hass, call)
    explicit_player = _clean_text(call.data.get(ATTR_MEDIA_PLAYER))
    context = _request_context_from_call(call)
    candidates = _player_candidates(hass, runtime)
    allow_fuzzy = bool(runtime.playback_targets)
    match: PlayerMatch | None = None
    recovery_field: str | None = None
    trailing_recovery_used = False
    player_phrase_detected = False

    if explicit_player:
        match = resolve_player_text(
            explicit_player,
            candidates,
            allow_fuzzy=allow_fuzzy,
        )
        player_phrase_detected = True
    else:
        recovery = recover_trailing_player(
            context,
            candidates,
            allow_fuzzy=allow_fuzzy,
        )
        context = recovery.fields
        match = recovery.match
        recovery_field = recovery.field_name
        trailing_recovery_used = recovery.player_phrase_detected
        player_phrase_detected = recovery.player_phrase_detected

    if match is not None and match.matched:
        runtime.pending_media_request = None
        diagnostics = _resolution_diagnostics(
            match,
            source="trailing_alias" if trailing_recovery_used else "explicit",
            trailing_recovery_used=trailing_recovery_used,
            default_used=False,
            recovery_field=recovery_field,
        )
        _remember_resolution(runtime, diagnostics)
        return {
            "success": True,
            "status": "resolved",
            "source": diagnostics["source"],
            ATTR_MEDIA_PLAYER: match.entity_id,
            ATTR_MEDIA_PLAYER_NAME: _response_player_name(
                match,
                source=diagnostics["source"],
            ),
            **context,
            "player_resolution": diagnostics,
        }

    if player_phrase_detected:
        pending_request = _pending_request_from_context(context)
        runtime.pending_media_request = pending_request
        reason = (
            "explicit_player_ambiguous"
            if match is not None and match.status == "ambiguous"
            else "explicit_player_not_found"
        )
        diagnostics = _resolution_diagnostics(
            match,
            source="trailing_alias" if trailing_recovery_used else "explicit",
            trailing_recovery_used=trailing_recovery_used,
            default_used=False,
            recovery_field=recovery_field,
        )
        _remember_resolution(runtime, diagnostics)
        return {
            "success": False,
            "status": "media_player_required",
            "reason": reason,
            ATTR_MEDIA_PLAYER: None,
            **context,
            "request_stored": pending_request is not None,
            "configured_default": runtime.default_media_player,
            "player_resolution": diagnostics,
        }

    default_player = _clean_text(runtime.default_media_player)
    default_is_allowed = (
        not runtime.playback_targets or default_player in runtime.playback_targets
    )
    if (
        default_player
        and default_is_allowed
        and _media_player_is_available(hass, default_player)
    ):
        runtime.pending_media_request = None
        default_candidate = next(
            (candidate for candidate in candidates if candidate.entity_id == default_player),
            PlayerCandidate(default_player, _state_name(None, default_player)),
        )
        default_match = PlayerMatch(
            status="matched",
            original_text="",
            entity_id=default_player,
            matched_name=default_candidate.name,
            matched_alias=default_candidate.name,
            method="configured_default",
            confidence=100.0,
        )
        diagnostics = _resolution_diagnostics(
            default_match,
            source="default",
            trailing_recovery_used=False,
            default_used=True,
        )
        _remember_resolution(runtime, diagnostics)
        return {
            "success": True,
            "status": "resolved",
            "source": "default",
            ATTR_MEDIA_PLAYER: default_player,
            ATTR_MEDIA_PLAYER_NAME: _response_player_name(
                default_match,
                source="default",
            ),
            **context,
            "player_resolution": diagnostics,
        }

    pending_request = _pending_request_from_context(context)
    runtime.pending_media_request = pending_request
    reason = (
        "configured_default_not_allowed"
        if default_player and not default_is_allowed
        else "configured_default_not_found"
        if default_player
        else "no_default_configured"
    )
    diagnostics = _resolution_diagnostics(
        None,
        source=None,
        trailing_recovery_used=False,
        default_used=False,
    )
    _remember_resolution(runtime, diagnostics)
    return {
        "success": False,
        "status": "media_player_required",
        "reason": reason,
        ATTR_MEDIA_PLAYER: None,
        **context,
        "request_stored": pending_request is not None,
        "configured_default": default_player or None,
        "player_resolution": diagnostics,
    }


async def async_handle_resume_media_request(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Resolve a spoken player and attach it to the pending media request."""

    runtime = _resolve_runtime(hass, call)
    player_text = _clean_text(call.data.get(ATTR_MEDIA_PLAYER))
    match = resolve_player_text(
        player_text,
        _player_candidates(hass, runtime),
        allow_fuzzy=bool(runtime.playback_targets),
    )
    diagnostics = _resolution_diagnostics(
        match,
        source="follow_up",
        trailing_recovery_used=False,
        default_used=False,
    )
    _remember_resolution(runtime, diagnostics)
    if not match.matched:
        return {
            "success": False,
            "status": (
                "media_player_ambiguous"
                if match.status == "ambiguous"
                else "invalid_media_player"
            ),
            ATTR_MEDIA_PLAYER: None,
            "player_resolution": diagnostics,
        }

    pending = runtime.pending_media_request
    if not isinstance(pending, dict):
        return {
            "success": False,
            "status": "no_pending_media_request",
            ATTR_MEDIA_PLAYER: match.entity_id,
            ATTR_MEDIA_PLAYER_NAME: _response_player_name(
                match,
                source="follow_up",
            ),
            "player_resolution": diagnostics,
        }

    runtime.pending_media_request = None
    return {
        "success": True,
        "status": "resumed",
        ATTR_MEDIA_PLAYER: match.entity_id,
        ATTR_MEDIA_PLAYER_NAME: _response_player_name(
            match,
            source="follow_up",
        ),
        **pending,
        "player_resolution": diagnostics,
    }


async def async_handle_get_item(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Fetch one Jellyfin item using the native standalone client."""

    runtime = _resolve_runtime(hass, call)
    item_id = _clean_text(call.data.get(ATTR_ITEM_ID))
    if not item_id:
        raise _validation_error("invalid_item_id", "Choose a Jellyfin item ID.")
    try:
        item = await async_get_native_item(runtime, item_id)
    except (JellyfinApiError, ValueError) as err:
        raise _validation_error("item_lookup_failed", str(err)) from err
    return {"item": item}


async def async_handle_play_on_chromecast(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Play one Jellyfin item using only the native Chromecast path."""

    runtime = _resolve_runtime(hass, call)
    target_entity_id = _clean_text(call.data.get(ATTR_ENTITY_ID))
    item_id = _clean_text(call.data.get(ATTR_ITEM_ID))

    if not target_entity_id.startswith("media_player."):
        raise _validation_error(
            "invalid_playback_target",
            "Choose a Home Assistant media_player entity.",
        )
    if not _media_player_is_available(hass, target_entity_id):
        raise _validation_error(
            "playback_target_not_found",
            "The selected media player is not available in Home Assistant.",
        )
    if not item_id:
        raise _validation_error("invalid_item_id", "Choose a Jellyfin item ID.")

    try:
        return await async_play_on_chromecast(
            hass,
            runtime,
            target_entity_id=target_entity_id,
            item_id=item_id,
        )
    except NoNextUpEpisodeError as err:
        raise _validation_error("no_next_up_episode", str(err)) from err
    except (ChromecastPlaybackError, JellyfinApiError, ValueError) as err:
        raise _validation_error("native_playback_failed", str(err)) from err


def _legacy_rest_compatible_items_response(content: Mapping[str, Any]) -> ServiceResponse:
    """Preserve the proven rest_command response shape during transport migration."""

    return {"status": 200, "content": dict(content)}


async def _async_query_items(
    runtime: JellyfinAssistRuntime,
    **kwargs: Any,
) -> ServiceResponse:
    """Execute one native read-only /Items query with legacy response compatibility."""

    try:
        content = await runtime.client.async_get_items(runtime.user_id, **kwargs)
    except (JellyfinApiError, ValueError) as err:
        raise _validation_error("library_query_failed", str(err)) from err
    return _legacy_rest_compatible_items_response(content)


async def async_handle_search_season(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Fetch the ordered episodes for one Jellyfin series season."""

    runtime = _resolve_runtime(hass, call)
    return await _async_query_items(
        runtime,
        parent_id=_clean_text(call.data.get(ATTR_SERIES_ID)),
        include_item_types="Episode",
        recursive=True,
        season=int(call.data[ATTR_SEASON]),
        sort_by="ParentIndexNumber,IndexNumber",
    )


async def async_handle_search_episode(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Fetch one episode by series, season, and episode number."""

    runtime = _resolve_runtime(hass, call)
    return await _async_query_items(
        runtime,
        parent_id=_clean_text(call.data.get(ATTR_SERIES_ID)),
        include_item_types="Episode",
        recursive=True,
        season=int(call.data[ATTR_SEASON]),
        episode=int(call.data[ATTR_EPISODE]),
    )


async def async_handle_search_episode_title(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Fetch candidate episodes by title within one series."""

    runtime = _resolve_runtime(hass, call)
    return await _async_query_items(
        runtime,
        parent_id=_clean_text(call.data.get(ATTR_SERIES_ID)),
        include_item_types="Episode",
        recursive=True,
        search_term=_clean_text(call.data.get(ATTR_EPISODE_TITLE)),
        sort_by="ParentIndexNumber,IndexNumber",
        sort_order="Ascending",
    )


async def async_handle_get_album_tracks(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Fetch ordered audio tracks for one Jellyfin album."""

    runtime = _resolve_runtime(hass, call)
    return await _async_query_items(
        runtime,
        parent_id=_clean_text(call.data.get(ATTR_ALBUM_ID)),
        include_item_types="Audio",
        recursive=True,
        sort_by="ParentIndexNumber,IndexNumber",
        sort_order="Ascending",
    )


async def async_handle_get_artist_tracks(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Fetch ordered audio tracks for one or more Jellyfin artist IDs."""

    runtime = _resolve_runtime(hass, call)
    return await _async_query_items(
        runtime,
        artist_ids=_clean_text(call.data.get(ATTR_ARTIST_ID)),
        include_item_types="Audio",
        recursive=True,
        sort_by="Album,ParentIndexNumber,IndexNumber",
        sort_order="Ascending",
    )


async def _async_queue_call(
    runtime: JellyfinAssistRuntime,
    operation: str,
    **kwargs: Any,
) -> ServiceResponse:
    """Call the native queue store while preserving the established response envelope."""

    client = runtime.queue_client
    if client is None:
        return {
            "status": 503,
            "content": {
                "success": False,
                "status": "unavailable",
                "message": "Queue storage is not available.",
            },
            "headers": {},
        }
    try:
        handler = getattr(client, f"async_{operation}")
        return await handler(**kwargs)
    except (QueueStoreError, ValueError) as err:
        return {
            "status": 503,
            "content": {
                "success": False,
                "status": "unavailable",
                "message": str(err),
            },
            "headers": {},
        }


async def async_handle_queue_get(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    runtime = _resolve_runtime(hass, call)
    return await _async_queue_call(
        runtime, "get", player=_clean_text(call.data.get(ATTR_MEDIA_PLAYER))
    )


async def async_handle_queue_add(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    runtime = _resolve_runtime(hass, call)
    item = {
        ATTR_ID: _clean_text(call.data.get(ATTR_ID)),
        ATTR_NAME: call.data.get(ATTR_NAME, ""),
        ATTR_TYPE: call.data.get(ATTR_TYPE, ""),
        ATTR_ARTIST: call.data.get(ATTR_ARTIST, ""),
        ATTR_ALBUM: call.data.get(ATTR_ALBUM, ""),
        ATTR_SERIES: call.data.get(ATTR_SERIES, ""),
        ATTR_SEASON: call.data.get(ATTR_SEASON, ""),
        ATTR_EPISODE: call.data.get(ATTR_EPISODE, ""),
    }
    return await _async_queue_call(
        runtime,
        "add",
        player=_clean_text(call.data.get(ATTR_MEDIA_PLAYER)),
        item=item,
    )


async def async_handle_queue_next(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    runtime = _resolve_runtime(hass, call)
    return await _async_queue_call(
        runtime, "next", player=_clean_text(call.data.get(ATTR_MEDIA_PLAYER))
    )


async def async_handle_queue_clear(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    runtime = _resolve_runtime(hass, call)
    return await _async_queue_call(
        runtime, "clear", player=_clean_text(call.data.get(ATTR_MEDIA_PLAYER))
    )


async def async_handle_queue_set_repeat(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    runtime = _resolve_runtime(hass, call)
    return await _async_queue_call(
        runtime,
        "settings",
        player=_clean_text(call.data.get(ATTR_MEDIA_PLAYER)),
        repeat_item=bool(call.data[ATTR_REPEAT_ITEM]),
        repeat_queue=bool(call.data[ATTR_REPEAT_QUEUE]),
    )


async def async_handle_queue_shuffle(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    runtime = _resolve_runtime(hass, call)
    return await _async_queue_call(
        runtime, "shuffle", player=_clean_text(call.data.get(ATTR_MEDIA_PLAYER))
    )


async def async_handle_queue_command(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    runtime = _resolve_runtime(hass, call)
    return await async_queue_command(
        hass,
        runtime,
        operation=_clean_text(call.data.get(ATTR_OPERATION)),
        media_player=_clean_text(call.data.get(ATTR_MEDIA_PLAYER)),
        media_player_display_name=_clean_text(call.data.get(ATTR_MEDIA_PLAYER_NAME)),
        context=getattr(call, "context", None),
    )


async def async_handle_media_orchestrator(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Run the native media resolver/orchestrator."""

    runtime = _resolve_runtime(hass, call)
    return await async_media_orchestrator(
        hass,
        runtime,
        query=_clean_text(call.data.get(ATTR_QUERY)),
        media_player=_clean_text(call.data.get(ATTR_MEDIA_PLAYER)),
        media_player_display_name=_clean_text(call.data.get(ATTR_MEDIA_PLAYER_NAME)),
        operation=_clean_text(call.data.get(ATTR_OPERATION)) or "play",
        media_type=_clean_text(call.data.get(ATTR_MEDIA_TYPE)) or None,
        artist=_clean_text(call.data.get(ATTR_ARTIST)),
        year=_clean_optional_int(call.data.get(ATTR_YEAR)),
        series=_clean_text(call.data.get(ATTR_SERIES)),
        season=_clean_optional_int(call.data.get(ATTR_SEASON)),
        episode=_clean_optional_int(call.data.get(ATTR_EPISODE)),
        context=getattr(call, "context", None),
    )


async def async_handle_play_pending_media(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Play or add one numbered pending media selection."""

    runtime = _resolve_runtime(hass, call)
    return await async_play_pending_media(
        hass,
        runtime,
        selection=int(call.data[ATTR_SELECTION]),
        context=getattr(call, "context", None),
    )


async def async_handle_resume_pending_media_request(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Resume a request that was waiting for a player choice."""

    runtime = _resolve_runtime(hass, call)
    return await async_resume_pending_media_request(
        hass,
        runtime,
        media_player=_clean_text(call.data.get(ATTR_MEDIA_PLAYER)),
        context=getattr(call, "context", None),
    )


async def async_handle_repair_voice_sentences(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Repair or reinstall the managed Jellyfin Assist voice sentence file."""

    result = await async_provision_voice_sentences(
        hass,
        overwrite_user_modified=bool(call.data.get(ATTR_OVERWRITE_USER_MODIFIED, False)),
    )
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        runtime = cast(JellyfinAssistRuntime, entry.runtime_data)
        runtime.voice_sentence_provisioning = result
    return result.as_dict()


async def async_handle_search(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Handle one read-only local catalog search action."""

    runtime = _resolve_runtime(hass, call)
    try:
        _request, response = _parse_and_execute(runtime, call)
        return response
    except SearchActionValidationError as err:
        raise _validation_error("invalid_search_request", str(err)) from err
    except CatalogUnavailableError as err:
        raise _validation_error(
            "catalog_unavailable",
            "The Jellyfin search catalog is not available yet.",
        ) from err


async def async_register_services(hass: HomeAssistant) -> None:
    """Register Jellyfin Media Assistant actions once."""

    high_level_media_actions = (
        (SERVICE_MEDIA_ORCHESTRATOR, MEDIA_ORCHESTRATOR_SCHEMA, async_handle_media_orchestrator),
        (SERVICE_PLAY_PENDING_MEDIA, PLAY_PENDING_MEDIA_SCHEMA, async_handle_play_pending_media),
        (SERVICE_RESUME_PENDING_MEDIA_REQUEST, RESUME_PENDING_MEDIA_REQUEST_SCHEMA, async_handle_resume_pending_media_request),
        (SERVICE_QUEUE_COMMAND, QUEUE_COMMAND_SCHEMA, async_handle_queue_command),
    )
    for service_name, schema, handler in high_level_media_actions:
        if hass.services.has_service(DOMAIN, service_name):
            continue

        async def handle_high_level_media_action(
            call: ServiceCall,
            *,
            _handler: Any = handler,
        ) -> ServiceResponse:
            return await _handler(hass, call)

        hass.services.async_register(
            DOMAIN,
            service_name,
            handle_high_level_media_action,
            schema=schema,
            supports_response=SupportsResponse.ONLY,
        )

    native_queue_actions = (
        (SERVICE_QUEUE_GET, QUEUE_GET_SCHEMA, async_handle_queue_get),
        (SERVICE_QUEUE_ADD, QUEUE_ADD_SCHEMA, async_handle_queue_add),
        (SERVICE_QUEUE_NEXT, QUEUE_GET_SCHEMA, async_handle_queue_next),
        (SERVICE_QUEUE_CLEAR, QUEUE_GET_SCHEMA, async_handle_queue_clear),
        (SERVICE_QUEUE_SET_REPEAT, QUEUE_SET_REPEAT_SCHEMA, async_handle_queue_set_repeat),
        (SERVICE_QUEUE_SHUFFLE, QUEUE_GET_SCHEMA, async_handle_queue_shuffle),
    )
    for service_name, schema, handler in native_queue_actions:
        if hass.services.has_service(DOMAIN, service_name):
            continue

        async def handle_queue_action(
            call: ServiceCall,
            *,
            _handler: Any = handler,
        ) -> ServiceResponse:
            return await _handler(hass, call)

        hass.services.async_register(
            DOMAIN,
            service_name,
            handle_queue_action,
            schema=schema,
            supports_response=SupportsResponse.ONLY,
        )

    native_item_queries = (
        (SERVICE_SEARCH_SEASON, SEARCH_SEASON_SCHEMA, async_handle_search_season),
        (SERVICE_SEARCH_EPISODE, SEARCH_EPISODE_SCHEMA, async_handle_search_episode),
        (
            SERVICE_SEARCH_EPISODE_TITLE,
            SEARCH_EPISODE_TITLE_SCHEMA,
            async_handle_search_episode_title,
        ),
        (SERVICE_GET_ALBUM_TRACKS, GET_ALBUM_TRACKS_SCHEMA, async_handle_get_album_tracks),
        (
            SERVICE_GET_ARTIST_TRACKS,
            GET_ARTIST_TRACKS_SCHEMA,
            async_handle_get_artist_tracks,
        ),
    )
    for service_name, schema, handler in native_item_queries:
        if hass.services.has_service(DOMAIN, service_name):
            continue

        async def handle_item_query(
            call: ServiceCall,
            *,
            _handler: Any = handler,
        ) -> ServiceResponse:
            return await _handler(hass, call)

        hass.services.async_register(
            DOMAIN,
            service_name,
            handle_item_query,
            schema=schema,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_GET_ITEM):

        async def handle_get_item(call: ServiceCall) -> ServiceResponse:
            return await async_handle_get_item(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_GET_ITEM,
            handle_get_item,
            schema=GET_ITEM_ACTION_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_PLAY_ON_CHROMECAST):

        async def handle_play_on_chromecast(call: ServiceCall) -> ServiceResponse:
            return await async_handle_play_on_chromecast(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_PLAY_ON_CHROMECAST,
            handle_play_on_chromecast,
            schema=PLAY_ON_CHROMECAST_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SEARCH):

        async def handle_search(call: ServiceCall) -> ServiceResponse:
            return await async_handle_search(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEARCH,
            handle_search,
            schema=SEARCH_ACTION_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RESOLVE_MEDIA_PLAYER):

        async def handle_resolve_media_player(call: ServiceCall) -> ServiceResponse:
            return await async_handle_resolve_media_player(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_RESOLVE_MEDIA_PLAYER,
            handle_resolve_media_player,
            schema=RESOLVE_MEDIA_PLAYER_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RESUME_MEDIA_REQUEST):

        async def handle_resume_media_request(call: ServiceCall) -> ServiceResponse:
            return await async_handle_resume_media_request(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_RESUME_MEDIA_REQUEST,
            handle_resume_media_request,
            schema=RESUME_MEDIA_REQUEST_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_REPAIR_VOICE_SENTENCES):

        async def handle_repair_voice_sentences(call: ServiceCall) -> ServiceResponse:
            return await async_handle_repair_voice_sentences(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_REPAIR_VOICE_SENTENCES,
            handle_repair_voice_sentences,
            schema=REPAIR_VOICE_SENTENCES_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )


__all__ = [
    "GET_ALBUM_TRACKS_SCHEMA",
    "GET_ARTIST_TRACKS_SCHEMA",
    "GET_ITEM_ACTION_SCHEMA",
    "PLAY_ON_CHROMECAST_SCHEMA",
    "MEDIA_ORCHESTRATOR_SCHEMA",
    "PLAY_PENDING_MEDIA_SCHEMA",
    "RESUME_PENDING_MEDIA_REQUEST_SCHEMA",
    "QUEUE_ADD_SCHEMA",
    "QUEUE_GET_SCHEMA",
    "QUEUE_SET_REPEAT_SCHEMA",
    "REPAIR_VOICE_SENTENCES_SCHEMA",
    "RESOLVE_MEDIA_PLAYER_SCHEMA",
    "RESUME_MEDIA_REQUEST_SCHEMA",
    "SEARCH_EPISODE_SCHEMA",
    "SEARCH_EPISODE_TITLE_SCHEMA",
    "SEARCH_SEASON_SCHEMA",
    "SEARCH_ACTION_SCHEMA",
    "async_handle_get_album_tracks",
    "async_handle_get_artist_tracks",
    "async_handle_get_item",
    "async_handle_media_orchestrator",
    "async_handle_play_pending_media",
    "async_handle_resume_pending_media_request",
    "async_handle_repair_voice_sentences",
    "async_handle_play_on_chromecast",
    "async_handle_queue_add",
    "async_handle_queue_clear",
    "async_handle_queue_get",
    "async_handle_queue_next",
    "async_handle_queue_set_repeat",
    "async_handle_queue_shuffle",
    "async_handle_resolve_media_player",
    "async_handle_resume_media_request",
    "async_handle_search",
    "async_handle_search_episode",
    "async_handle_search_episode_title",
    "async_handle_search_season",
    "async_register_services",
]
