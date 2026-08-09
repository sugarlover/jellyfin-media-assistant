"""Native media resolution and orchestration formerly implemented as YAML scripts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    DOMAIN,
    QUEUE_PLAYER_OPERATIONS,
    SERVICE_GET_ALBUM_TRACKS,
    SERVICE_GET_ARTIST_TRACKS,
    SERVICE_QUEUE_ADD,
    SERVICE_QUEUE_CLEAR,
    SERVICE_RESOLVE_MEDIA_PLAYER,
    SERVICE_RESUME_MEDIA_REQUEST,
    SERVICE_SEARCH,
    SERVICE_SEARCH_EPISODE,
    SERVICE_SEARCH_SEASON,
)
from .item_lookup import async_get_native_item
from .media_actions import async_play_item, async_prepare_play_session, async_queue_add_item
from .queue_control import async_queue_command
from .runtime import JellyfinAssistRuntime

_PLAYABLE_ITEM_TYPES = frozenset({"Movie", "Episode", "Audio", "MusicVideo", "Video"})
_CONTAINER_ITEM_TYPES = frozenset({"series", "musicalbum", "musicartist"})
_WHITESPACE_RE = re.compile(r"\s+")
_NORMALIZE_KEY_RE = re.compile(r"[^a-z0-9]+")


def _text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "None", "none"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _runtime_action_data(runtime: JellyfinAssistRuntime, data: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(data)
    if runtime.entry_id:
        result.setdefault(ATTR_CONFIG_ENTRY_ID, runtime.entry_id)
    return result


async def _action(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    service: str,
    data: Mapping[str, Any],
    *,
    context: Any = None,
) -> dict[str, Any]:
    """Call one native Jellyfin Assist action and normalize its response."""

    response = await hass.services.async_call(
        DOMAIN,
        service,
        _runtime_action_data(runtime, data),
        blocking=True,
        return_response=True,
        context=context,
    )
    return dict(response) if isinstance(response, Mapping) else {}


def _state_friendly_name(hass: Any, entity_id: str) -> str:
    state = hass.states.get(entity_id) if getattr(hass, "states", None) else None
    attrs = getattr(state, "attributes", {}) or {}
    return _text(attrs.get("friendly_name")) or entity_id


def _requested_entity_display_name(requested_player: str) -> str:
    requested = _text(requested_player)
    if not requested.startswith("media_player."):
        return ""
    return requested.split(".", 1)[1].replace("_", " ").title().replace(" Tv", " TV")


def _clean_message(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _base_result(
    *,
    success: bool,
    status: str,
    operation: str,
    intent: Any,
    query: Any,
    message: str,
    jellyfin_id: Any = None,
    item: Any = None,
    items: Sequence[Any] | None = None,
    playback_plan: Sequence[Any] | None = None,
    media_player: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "success": success,
        "status": status,
        "operation": operation,
        "intent": intent,
        "query": query,
        "message": message,
        "speak": message,
        "display": message,
        "jellyfin_id": jellyfin_id,
        "item": item,
        "items": list(items or []),
        "playback_plan": list(playback_plan or []),
        "media_player": media_player,
        **extra,
    }


def _normalize_key(value: Any) -> str:
    text = _text(value).lower().replace("’", "'").replace("&", "and")
    return _NORMALIZE_KEY_RE.sub(" ", text).strip()


def _runtime_minutes(raw: Mapping[str, Any]) -> int | None:
    ticks = raw.get("RunTimeTicks")
    if ticks is None:
        return None
    try:
        return round(int(ticks or 0) / 600_000_000)
    except (TypeError, ValueError):
        return None


def normalize_jellyfin_item(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one raw Jellyfin item using the historical script contract."""

    item_type = _text(raw.get("Type"))
    item_type_key = item_type.lower()
    artists = raw.get("Artists")
    artist_name = ""
    if isinstance(artists, Sequence) and not isinstance(artists, (str, bytes)) and artists:
        artist_name = _text(artists[0])
    user_data = raw.get("UserData") if isinstance(raw.get("UserData"), Mapping) else {}
    parent_index = raw.get("ParentIndexNumber")
    index = raw.get("IndexNumber")
    return {
        "id": raw.get("Id"),
        "name": raw.get("Name", "Unknown"),
        "type": item_type,
        "year": raw.get("ProductionYear"),
        "runtime_minutes": _runtime_minutes(raw),
        "genres": list(raw.get("Genres") or []),
        "rating": raw.get("CommunityRating"),
        "description": raw.get("Overview") or "",
        "series_name": raw.get("SeriesName") or "",
        "series_id": raw.get("SeriesId") or "",
        "season_name": f"Season {parent_index}" if item_type_key == "episode" and parent_index is not None else "",
        "season_number": parent_index if item_type_key == "episode" else None,
        "index_number": index,
        "episode_number": index if item_type_key == "episode" else None,
        "disc_number": parent_index if item_type_key == "audio" else None,
        "track_number": index if item_type_key == "audio" else None,
        "artist_name": artist_name,
        "album_artist": raw.get("AlbumArtist") or "",
        "album": raw.get("Album") or "",
        "is_played": bool(user_data.get("Played", False)),
        "is_favorite": bool(user_data.get("IsFavorite", False)),
        "official_rating": raw.get("OfficialRating"),
        "community_rating": raw.get("CommunityRating"),
    }


async def _search(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    query: str,
    media_type: str | None = None,
    artist: str = "",
    series: str = "",
    year: int | None = None,
    context: Any = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"query": query}
    if media_type:
        data["media_type"] = media_type
    if artist:
        data["artist"] = artist
    if series:
        data["series"] = series
    if year is not None:
        data["year"] = year
    response = await _action(hass, runtime, SERVICE_SEARCH, data, context=context)
    return response if isinstance(response, Mapping) else {"items": []}


def _items(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = response.get("items", [])
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _raw_items(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    content = response.get("content")
    raw = content.get("Items", []) if isinstance(content, Mapping) else []
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _series_episode_item(raw: Mapping[str, Any], *, series_name: str, series_id: str, default_season: int) -> dict[str, Any]:
    season = raw.get("ParentIndexNumber")
    episode = raw.get("IndexNumber")
    return {
        "id": raw.get("Id"),
        "name": raw.get("Name", ""),
        "type": "Episode",
        "year": raw.get("ProductionYear"),
        "series_name": series_name,
        "series_id": series_id,
        "season": int(season) if season is not None else default_season,
        "episode": int(episode or 0),
        "runtime_minutes": _runtime_minutes(raw) or 0,
        "official_rating": raw.get("OfficialRating", ""),
    }


def _album_track_item(raw: Mapping[str, Any], *, album_name: str, album_artist_name: str) -> dict[str, Any]:
    artists = raw.get("Artists")
    track_artist = album_artist_name
    if isinstance(artists, Sequence) and not isinstance(artists, (str, bytes)) and artists:
        track_artist = _text(artists[0]) or album_artist_name
    disc = int(raw.get("ParentIndexNumber") or 1)
    track = int(raw.get("IndexNumber") or 0)
    return {
        "id": raw.get("Id"),
        "name": raw.get("Name", ""),
        "type": "Audio",
        "year": raw.get("ProductionYear"),
        "runtime_minutes": _runtime_minutes(raw) or 0,
        "artist_name": track_artist,
        "album_artist": raw.get("AlbumArtist") or album_artist_name,
        "album": raw.get("Album") or album_name,
        "parent_index_number": disc,
        "index_number": track,
        "disc_number": disc,
        "track_number": track,
    }


def _artist_track_item(raw: Mapping[str, Any], *, artist_name: str) -> dict[str, Any]:
    artists = raw.get("Artists")
    track_artist = artist_name
    if isinstance(artists, Sequence) and not isinstance(artists, (str, bytes)) and artists:
        track_artist = _text(artists[0]) or artist_name
    disc = int(raw.get("ParentIndexNumber") or 1)
    track = int(raw.get("IndexNumber") or 0)
    return {
        "id": raw.get("Id"),
        "name": raw.get("Name", ""),
        "type": "Audio",
        "year": raw.get("ProductionYear"),
        "runtime_minutes": _runtime_minutes(raw) or 0,
        "artist_name": track_artist,
        "album_artist": raw.get("AlbumArtist") or "",
        "album": raw.get("Album") or "",
        "parent_index_number": disc,
        "index_number": track,
        "disc_number": disc,
        "track_number": track,
    }


async def async_resolve_tv_episode(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    series_id: str,
    series_name: str,
    season: int,
    episode: int,
    context: Any = None,
) -> dict[str, Any]:
    """Resolve a numbered episode with the historical resolver contract."""

    response = await _action(
        hass,
        runtime,
        SERVICE_SEARCH_EPISODE,
        {"series_id": series_id, "season": season, "episode": episode},
        context=context,
    )
    status = int(response.get("status", 0) or 0)
    raw = _raw_items(response)
    success = status == 200 and len(raw) == 1
    if status != 200:
        resolver_status = "api_error"
        message = f"The Jellyfin episode search failed with HTTP status {status}."
    elif not raw:
        resolver_status = "not_found"
        message = f"No episode was found for {series_name}, season {season}, episode {episode}."
    elif len(raw) > 1:
        resolver_status = "multiple_matches"
        message = f"Jellyfin returned multiple episodes for {series_name}, season {season}, episode {episode}."
    else:
        resolver_status = "resolved"
        message = f"Found {raw[0].get('Name', '')} — {series_name}, season {season}, episode {episode}."
    return {
        "success": success,
        "status": resolver_status,
        "http_status": status,
        "jellyfin_id": raw[0].get("Id") if len(raw) == 1 else None,
        "episode_name": raw[0].get("Name", "") if len(raw) == 1 else "",
        "series_id": series_id,
        "series_name": series_name,
        "season": season,
        "episode": episode,
        "message": message,
    }


async def async_resolve_episode_title(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    episode_title: str,
    series_name: str,
    media_player: str = "",
    context: Any = None,
) -> dict[str, Any]:
    """Resolve an episode title inside one exact parent series."""

    series_search = await _search(
        hass,
        runtime,
        query=series_name,
        media_type="Series",
        context=context,
    )
    candidates = _items(series_search)
    key = _normalize_key(series_name)
    exact = [item for item in candidates if _normalize_key(item.get("name")) == key]
    series_items = exact or candidates
    if not series_items:
        message = f'I could not find the TV series "{series_name}" needed to find "{episode_title}".'
        return _base_result(
            success=False,
            status="series_not_found",
            operation="resolve",
            intent="Episode",
            query=episode_title,
            message=message,
            media_player=media_player,
            media_type="Episode",
        )
    if len(series_items) > 1:
        message = f'I found more than one TV series matching "{series_name}". Please use a more specific series title.'
        return _base_result(
            success=False,
            status="series_ambiguous",
            operation="resolve",
            intent="Episode",
            query=episode_title,
            message=message,
            media_player=media_player,
            items=series_items,
            media_type="Episode",
        )

    series_item = series_items[0]
    series_id = _text(series_item.get("id"))
    resolved_series_name = _text(series_item.get("name")) or series_name
    response = await _action(
        hass,
        runtime,
        "search_episode_title",
        {"series_id": series_id, "episode_title": episode_title},
        context=context,
    )
    status = int(response.get("status", 0) or 0)
    raw_candidates = _raw_items(response)
    title_key = _normalize_key(episode_title)
    exact_episodes = [item for item in raw_candidates if _normalize_key(item.get("Name")) == title_key]
    raw_episodes = exact_episodes or raw_candidates
    if status != 200:
        message = f'Jellyfin could not search {resolved_series_name} for "{episode_title}".'
        return _base_result(
            success=False,
            status="episode_lookup_failed",
            operation="resolve",
            intent="Episode",
            query=episode_title,
            message=message,
            media_player=media_player,
            media_type="Episode",
            http_status=status,
        )

    normalized = []
    for raw in raw_episodes:
        season = raw.get("ParentIndexNumber")
        episode = raw.get("IndexNumber")
        normalized.append(
            {
                "id": raw.get("Id"),
                "name": raw.get("Name", ""),
                "type": "Episode",
                "year": raw.get("ProductionYear"),
                "runtime_minutes": _runtime_minutes(raw) or 0,
                "genres": list(raw.get("Genres") or []),
                "rating": raw.get("CommunityRating"),
                "description": raw.get("Overview") or "",
                "series_name": resolved_series_name,
                "series_id": series_id,
                "season_name": f"Season {season}" if season is not None else "",
                "season_number": season,
                "episode_number": episode,
                "parent_index_number": season,
                "index_number": episode,
                "official_rating": raw.get("OfficialRating") or "",
            }
        )
    if not normalized:
        message = f'I could not find anything matching "{episode_title}" from {resolved_series_name}.'
        return _base_result(
            success=False,
            status="not_found",
            operation="resolve",
            intent="Episode",
            query=episode_title,
            message=message,
            media_player=media_player,
            media_type="Episode",
        )
    if len(normalized) > 1:
        message = f'I found {len(normalized)} episodes named "{episode_title}" in {resolved_series_name}. Please select one.'
        return _base_result(
            success=False,
            status="multiple_matches",
            operation="resolve",
            intent="Episode",
            query=episode_title,
            message=message,
            media_player=media_player,
            items=normalized,
            media_type="Episode",
        )

    selected = normalized[0]
    description = _text(selected.get("name")) or episode_title
    description += f" from {resolved_series_name}"
    if selected.get("season_number") is not None:
        description += f", Season {selected['season_number']}"
    if selected.get("episode_number") is not None:
        description += f", Episode {selected['episode_number']}"
    message = _clean_message(f"Found {description}.")
    return _base_result(
        success=True,
        status="resolved",
        operation="resolve",
        intent="Episode",
        query=episode_title,
        message=message,
        jellyfin_id=selected.get("id"),
        item=selected,
        items=normalized,
        playback_plan=[selected],
        media_player=media_player,
        media_type="Episode",
    )


async def async_resolve_media_intent(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    query: str,
    media_type: str | None = None,
    artist: str = "",
    year: int | None = None,
    series: str = "",
    season: int | None = None,
    episode: int | None = None,
    context: Any = None,
) -> dict[str, Any]:
    """Resolve one media request into the established playback-plan contract."""

    requested_type = _text(media_type) or None
    requested_artist = _text(artist)
    requested_year = _optional_int(year)
    requested_series = _text(series)
    requested_season = _optional_int(season)
    requested_episode = _optional_int(episode)

    if requested_season is not None and requested_episode is not None:
        series_search = await _search(
            hass,
            runtime,
            query=query,
            media_type="Series",
            context=context,
        )
        series_items = _items(series_search)
        if not series_items:
            message = (
                f'I could not find the TV series "{query}" needed to resolve '
                f"Season {requested_season}, Episode {requested_episode}."
            )
            return _base_result(
                success=False,
                status="series_not_found",
                operation="resolve",
                intent="Episode",
                query=query,
                message=message,
                media_type="Series",
                season=requested_season,
                episode=requested_episode,
            )
        if len(series_items) > 1:
            message = f'I found {len(series_items)} TV series matching "{query}". Please select one.'
            return _base_result(
                success=False,
                status="multiple_series_matches",
                operation="resolve",
                intent="Episode",
                query=query,
                message=message,
                items=series_items,
                media_type="Series",
                season=requested_season,
                episode=requested_episode,
            )
        selected_series = series_items[0]
        series_id = _text(selected_series.get("id"))
        resolved_series_name = _text(selected_series.get("name")) or query
        episode_resolution = await async_resolve_tv_episode(
            hass,
            runtime,
            series_id=series_id,
            series_name=resolved_series_name,
            season=requested_season,
            episode=requested_episode,
            context=context,
        )
        episode_item = {
            "id": episode_resolution.get("jellyfin_id"),
            "name": episode_resolution.get("episode_name", ""),
            "type": "Episode",
            "series_name": resolved_series_name,
            "series_id": series_id,
            "season": requested_season,
            "episode": requested_episode,
        }
        found = bool(episode_resolution.get("jellyfin_id"))
        message = _text(episode_resolution.get("message")) or "Unable to resolve the requested episode."
        return _base_result(
            success=bool(episode_resolution.get("success", False)),
            status=_text(episode_resolution.get("status")) or "unknown",
            operation="resolve",
            intent="Episode",
            query=query,
            message=message,
            jellyfin_id=episode_resolution.get("jellyfin_id"),
            item=episode_item if found else None,
            items=[episode_item] if found else [],
            playback_plan=[episode_item] if found else [],
            media_type="Episode",
            season=requested_season,
            episode=requested_episode,
        )

    primary = await _search(
        hass,
        runtime,
        query=query,
        media_type=requested_type,
        artist=requested_artist,
        series=requested_series,
        year=requested_year,
        context=context,
    )
    primary_items = _items(primary)
    episode_items: list[dict[str, Any]] = []
    audio_items: list[dict[str, Any]] = []
    if requested_type is None and not primary_items:
        episode_search = await _search(
            hass,
            runtime,
            query=query,
            media_type="Episode",
            artist=requested_artist,
            series=requested_series,
            year=requested_year,
            context=context,
        )
        episode_items = _items(episode_search)
        if not episode_items:
            audio_search = await _search(
                hass,
                runtime,
                query=query,
                media_type="Audio",
                artist=requested_artist,
                series=requested_series,
                year=requested_year,
                context=context,
            )
            audio_items = _items(audio_search)

    search_items = episode_items or audio_items or primary_items
    fallback_media_type: str | None = requested_type
    if fallback_media_type is None and episode_items:
        fallback_media_type = "Episode"
    elif fallback_media_type is None and audio_items:
        fallback_media_type = "Audio"

    if not search_items:
        message = f'I could not find anything matching "{query}"'
        if requested_artist:
            message += f" by {requested_artist}"
        if requested_series:
            message += f" from {requested_series}"
        message += "."
        return _base_result(
            success=False,
            status="not_found",
            operation="resolve",
            intent=fallback_media_type,
            query=query,
            message=message,
            media_type=requested_type,
        )

    if len(search_items) > 1:
        message = f'I found {len(search_items)} possible matches for "{query}". Please select one.'
        return _base_result(
            success=False,
            status="multiple_matches",
            operation="resolve",
            intent=fallback_media_type,
            query=query,
            message=message,
            items=search_items,
            media_type=fallback_media_type,
        )

    selected = search_items[0]
    selected_type = _text(selected.get("type"))
    selected_type_key = selected_type.lower()
    selected_id = _text(selected.get("id"))
    selected_name = _text(selected.get("name")) or query

    if selected_type_key == "series":
        resolved_season = requested_season or 1
        response = await _action(
            hass,
            runtime,
            SERVICE_SEARCH_SEASON,
            {"series_id": selected_id, "season": resolved_season},
            context=context,
        )
        status = int(response.get("status", 0) or 0)
        season_items = _raw_items(response)
        if status != 200:
            message = f"I found {selected_name}, but I could not retrieve Season {resolved_season} from Jellyfin."
            return _base_result(
                success=False,
                status="season_lookup_failed",
                operation="resolve",
                intent="Series",
                query=query,
                message=message,
                jellyfin_id=selected_id,
                item=selected,
                items=search_items,
                media_type="Series",
                season=resolved_season,
            )
        if not season_items:
            message = f"I found {selected_name}, but Season {resolved_season} has no episodes in Jellyfin."
            return _base_result(
                success=False,
                status="season_not_found",
                operation="resolve",
                intent="Series",
                query=query,
                message=message,
                jellyfin_id=selected_id,
                item=selected,
                items=search_items,
                media_type="Series",
                season=resolved_season,
            )
        plan = [
            _series_episode_item(
                raw,
                series_name=selected_name,
                series_id=selected_id,
                default_season=resolved_season,
            )
            for raw in season_items
        ]
        message = f"Found {selected_name}. Season {resolved_season} contains {len(season_items)} episodes."
        return _base_result(
            success=True,
            status="resolved",
            operation="resolve",
            intent="Series",
            query=query,
            message=message,
            jellyfin_id=selected_id,
            item=selected,
            items=search_items,
            playback_plan=plan,
            media_type="Series",
            season=resolved_season,
        )

    if selected_type_key == "musicalbum":
        response = await _action(
            hass,
            runtime,
            SERVICE_GET_ALBUM_TRACKS,
            {"album_id": selected_id},
            context=context,
        )
        status = int(response.get("status", 0) or 0)
        album_items = _raw_items(response)
        album_artist = _text(selected.get("album_artist")) or _text(selected.get("artist_name"))
        if status != 200:
            message = f"I found {selected_name}, but I could not retrieve its tracks from Jellyfin."
            return _base_result(
                success=False,
                status="album_lookup_failed",
                operation="resolve",
                intent="MusicAlbum",
                query=query,
                message=message,
                jellyfin_id=selected_id,
                item=selected,
                items=search_items,
                media_type="MusicAlbum",
            )
        if not album_items:
            message = f"I found {selected_name}, but it has no playable tracks in Jellyfin."
            return _base_result(
                success=False,
                status="album_empty",
                operation="resolve",
                intent="MusicAlbum",
                query=query,
                message=message,
                jellyfin_id=selected_id,
                item=selected,
                items=search_items,
                media_type="MusicAlbum",
            )
        plan = [
            _album_track_item(raw, album_name=selected_name, album_artist_name=album_artist)
            for raw in album_items
        ]
        suffix = f" by {album_artist}" if album_artist else ""
        plural = "s" if len(album_items) != 1 else ""
        message = f"Found {selected_name}{suffix}. The album contains {len(album_items)} track{plural}."
        return _base_result(
            success=True,
            status="resolved",
            operation="resolve",
            intent="MusicAlbum",
            query=query,
            message=message,
            jellyfin_id=selected_id,
            item=selected,
            items=search_items,
            playback_plan=plan,
            media_type="MusicAlbum",
        )

    if selected_type_key == "musicartist":
        physical_ids = selected.get("physical_ids")
        if not isinstance(physical_ids, list) or not physical_ids:
            physical_ids = [selected_id]
        response = await _action(
            hass,
            runtime,
            SERVICE_GET_ARTIST_TRACKS,
            {"artist_id": ",".join(_text(value) for value in physical_ids if _text(value))},
            context=context,
        )
        status = int(response.get("status", 0) or 0)
        artist_items = _raw_items(response)
        artist_name = _text(selected.get("name")) or selected_name
        if status != 200:
            message = f"I found {artist_name}, but I could not retrieve the artist's tracks from Jellyfin."
            return _base_result(
                success=False,
                status="artist_lookup_failed",
                operation="resolve",
                intent="MusicArtist",
                query=query,
                message=message,
                jellyfin_id=selected_id,
                item=selected,
                items=search_items,
                media_type="MusicArtist",
            )
        if not artist_items:
            message = f"I found {artist_name}, but Jellyfin has no playable tracks for that artist."
            return _base_result(
                success=False,
                status="artist_empty",
                operation="resolve",
                intent="MusicArtist",
                query=query,
                message=message,
                jellyfin_id=selected_id,
                item=selected,
                items=search_items,
                media_type="MusicArtist",
            )
        artist_items.sort(
            key=lambda raw: (
                int(raw.get("ProductionYear") or 9999),
                _text(raw.get("Album")).lower(),
                int(raw.get("ParentIndexNumber") or 1),
                int(raw.get("IndexNumber") or 0),
                _text(raw.get("Name")).lower(),
            )
        )
        plan = [_artist_track_item(raw, artist_name=artist_name) for raw in artist_items]
        message = f"Found {artist_name}. The artist has {len(artist_items)} playable tracks."
        return _base_result(
            success=True,
            status="resolved",
            operation="resolve",
            intent="MusicArtist",
            query=query,
            message=message,
            jellyfin_id=selected_id,
            item=selected,
            items=search_items,
            playback_plan=plan,
            media_type="MusicArtist",
        )

    year_text = f" ({selected.get('year')})" if selected.get("year") else ""
    message = f"I found {selected_name}{year_text} as a {selected_type}."
    result = _base_result(
        success=True,
        status="resolved",
        operation="resolve",
        intent=selected_type,
        query=query,
        message=message,
        jellyfin_id=selected_id,
        item=selected,
        items=search_items,
        playback_plan=[selected],
        media_type=selected_type,
    )
    result["display"] = f"I found {selected_name}{year_text} — {selected_type}."
    return result


async def _normalize_playback_plan(
    runtime: JellyfinAssistRuntime,
    playback_plan: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for value in playback_plan:
        item = dict(value)
        if _text(item.get("type")) != "Episode":
            normalized.append(item)
            continue
        existing_series = _text(item.get("series_name")) or _text(item.get("series"))
        existing_season = (
            item.get("season_number")
            if item.get("season_number") is not None
            else item.get("parent_index_number")
            if item.get("parent_index_number") is not None
            else item.get("season")
        )
        existing_episode = (
            item.get("episode_number")
            if item.get("episode_number") is not None
            else item.get("index_number")
            if item.get("index_number") is not None
            else item.get("episode")
        )
        raw: dict[str, Any] = {}
        if not existing_series or existing_season in (None, "") or existing_episode in (None, ""):
            try:
                raw = await async_get_native_item(runtime, _text(item.get("id")))
            except Exception:
                raw = {}
        normalized.append(
            {
                "id": item.get("id"),
                "name": item.get("name", "Unknown"),
                "type": "Episode",
                "year": item.get("year") if item.get("year") is not None else raw.get("ProductionYear"),
                "runtime_minutes": item.get("runtime_minutes"),
                "genres": list(item.get("genres") or []),
                "rating": item.get("rating") if item.get("rating") is not None else raw.get("CommunityRating"),
                "description": item.get("description") or raw.get("Overview") or "",
                "series_name": existing_series or raw.get("SeriesName") or "",
                "series_id": item.get("series_id") or raw.get("SeriesId") or "",
                "season": existing_season if existing_season not in (None, "") else raw.get("ParentIndexNumber", ""),
                "episode": existing_episode if existing_episode not in (None, "") else raw.get("IndexNumber", ""),
                "official_rating": item.get("official_rating") or raw.get("OfficialRating") or "",
            }
        )
    return normalized


def _pending_choice_text(items: Sequence[Mapping[str, Any]]) -> str:
    choices: list[str] = []
    for index, item in enumerate(items, start=1):
        choice = f"{index}. {_text(item.get('name')) or 'Unknown'}"
        item_type = _text(item.get("type")).lower()
        artist = _text(item.get("artist_name")) or _text(item.get("album_artist"))
        if item_type == "audio" and artist:
            choice += f" by {artist}"
        if item.get("year"):
            choice += f" ({item.get('year')})"
        choices.append(choice)
    return "\n".join(choices)


def _play_description(resolver: Mapping[str, Any], first_item: Mapping[str, Any], query: str) -> str:
    intent = _text(resolver.get("intent"))
    if intent == "Series":
        resolver_item = resolver.get("item") if isinstance(resolver.get("item"), Mapping) else {}
        series_name = _text(resolver_item.get("name")) or _text(first_item.get("series_name")) or query
        season = resolver.get("season") or first_item.get("season") or 1
        return f"{series_name}, Season {season}"
    if intent == "Episode":
        description = _text(first_item.get("name")) or "the requested episode"
        series_name = _text(first_item.get("series_name"))
        if series_name:
            description += f" from {series_name}"
        if first_item.get("season") is not None:
            description += f", Season {first_item.get('season')}"
        if first_item.get("episode") is not None:
            description += f", Episode {first_item.get('episode')}"
        return description
    if _text(first_item.get("type")) == "Audio":
        description = _text(first_item.get("name")) or "the requested audio"
        artist = _text(first_item.get("artist_name")) or _text(first_item.get("album_artist"))
        if artist:
            description += f" by {artist}"
        return description
    description = _text(first_item.get("name")) or "the requested media"
    if first_item.get("year"):
        description += f" ({first_item.get('year')})"
    return description


def _added_description(resolver: Mapping[str, Any], playback_plan: Sequence[Mapping[str, Any]], query: str) -> str:
    if len(playback_plan) == 1:
        item = playback_plan[0]
        description = _text(item.get("name")) or "the requested media"
        if item.get("year"):
            description += f" ({item.get('year')})"
        return description
    if _text(resolver.get("intent")) == "Series":
        resolver_item = resolver.get("item") if isinstance(resolver.get("item"), Mapping) else {}
        series_name = _text(resolver_item.get("name")) or _text(playback_plan[0].get("series_name")) or query
        season = resolver.get("season") or playback_plan[0].get("season") or 1
        return f"Season {season} of {series_name}"
    return f"{len(playback_plan)} items"


async def async_media_orchestrator(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    query: str,
    media_player: str = "",
    media_player_display_name: str = "",
    operation: str = "play",
    media_type: str | None = None,
    artist: str = "",
    year: int | None = None,
    series: str = "",
    season: int | None = None,
    episode: int | None = None,
    context: Any = None,
) -> dict[str, Any]:
    """Resolve a media request, manage the queue, and play or add its plan."""

    requested_operation = _text(operation).lower() or "play"
    requested_player = _text(media_player)
    requested_display = _text(media_player_display_name)
    resolution = await _action(
        hass,
        runtime,
        SERVICE_RESOLVE_MEDIA_PLAYER,
        {
            "media_player": requested_player,
            "query": query,
            "operation": requested_operation,
            "media_type": _text(media_type),
            "artist": _text(artist),
            "series": _text(series),
            "year": year if year is not None else "",
            "season": season if season is not None else "",
            "episode": episode if episode is not None else "",
        },
        context=context,
    )
    if not resolution.get("success", False):
        reason = _text(resolution.get("reason"))
        message = (
            "I found more than one matching media player. Which one would you like me to use?"
            if reason == "explicit_player_ambiguous"
            else "I could not use that media player. Which media player would you like me to use?"
            if reason == "explicit_player_not_found"
            else "Which media player would you like me to use?"
        )
        resolved_type = resolution.get("media_type") or media_type
        return _base_result(
            success=False,
            status="media_player_required",
            operation=requested_operation,
            intent=resolved_type,
            query=resolution.get("query") or query,
            message=message,
            media_type=resolved_type,
            player_resolution=resolution,
        )

    resolved_player = _text(resolution.get("media_player"))
    resolved_player_name = (
        requested_display
        or _requested_entity_display_name(requested_player)
        or _text(resolution.get("media_player_name"))
        or _state_friendly_name(hass, resolved_player)
    )
    resolved_query = _text(resolution.get("query")) or query
    resolved_media_type = _text(resolution.get("media_type")) or _text(media_type) or None
    resolved_artist = _text(resolution.get("artist")) or _text(artist)
    resolved_series = _text(resolution.get("series")) or _text(series)
    resolved_year = _optional_int(resolution.get("year")) or _optional_int(year)
    resolved_season = _optional_int(resolution.get("season")) or _optional_int(season)
    resolved_episode = _optional_int(resolution.get("episode")) or _optional_int(episode)

    resolver = await async_resolve_media_intent(
        hass,
        runtime,
        query=resolved_query,
        media_type=resolved_media_type,
        artist=resolved_artist,
        year=resolved_year,
        series=resolved_series,
        season=resolved_season,
        episode=resolved_episode,
        context=context,
    )
    if not resolver.get("success", False):
        if resolver.get("status") in {"multiple_matches", "multiple_series_matches"}:
            pending_items = [dict(item) for item in resolver.get("items", []) if isinstance(item, Mapping)]
            runtime.pending_selection = {
                "items": pending_items,
                "media_player": resolved_player,
                "operation": requested_operation,
                "query": resolver.get("query", query),
                "intent": resolver.get("intent") or resolver.get("media_type") or _text(media_type),
            }
            heading = f'I found {len(pending_items)} possible matches for "{resolver.get("query", query)}".'
            choices = _pending_choice_text(pending_items)
            pending_response = f"{heading}\n{choices}\n\nPlease select a number."
            return _base_result(
                success=False,
                status=_text(resolver.get("status")),
                operation=requested_operation,
                intent=resolver.get("intent"),
                query=resolver.get("query", query),
                message=pending_response,
                jellyfin_id=resolver.get("jellyfin_id"),
                item=resolver.get("item"),
                items=pending_items,
                media_player=resolved_player,
                media_type=resolver.get("media_type"),
                season=resolver.get("season"),
                episode=resolver.get("episode"),
            )
        result = dict(resolver)
        result.setdefault("operation", requested_operation)
        result.setdefault("media_player", resolved_player)
        return result

    raw_plan = [dict(item) for item in resolver.get("playback_plan", []) if isinstance(item, Mapping)]
    if not raw_plan:
        action_wording = "add to the queue" if requested_operation == "add" else "play"
        message = f"I resolved the media request, but there are no items available to {action_wording}."
        return _base_result(
            success=False,
            status="empty_playback_plan",
            operation=requested_operation,
            intent=resolver.get("intent"),
            query=resolver.get("query"),
            message=message,
            jellyfin_id=resolver.get("jellyfin_id"),
            item=resolver.get("item"),
            items=resolver.get("items", []),
            media_player=resolved_player,
        )

    playback_plan = await _normalize_playback_plan(runtime, raw_plan)

    if requested_operation == "add":
        add_results: list[dict[str, Any]] = []
        for item in playback_plan:
            add_result = await async_queue_add_item(
                hass,
                runtime,
                item=item,
                media_player=resolved_player,
            )
            add_results.append(add_result)
            if not add_result.get("success", False):
                message = (
                    f"I found {_text(item.get('name')) or 'the requested media'}, but I could not add it "
                    f"to the queue for {_state_friendly_name(hass, resolved_player)}."
                )
                return _base_result(
                    success=False,
                    status="queue_add_failed",
                    operation="add",
                    intent=resolver.get("intent"),
                    query=resolver.get("query"),
                    message=message,
                    jellyfin_id=item.get("id"),
                    item=item,
                    items=resolver.get("items", []),
                    playback_plan=playback_plan,
                    media_player=resolved_player,
                    add_results=add_results,
                )
        description = _clean_message(_added_description(resolver, playback_plan, query))
        message = f"Added {description} to the queue for {resolved_player_name}."
        one_item = playback_plan[0] if len(playback_plan) == 1 else None
        return _base_result(
            success=True,
            status="added",
            operation="add",
            intent=resolver.get("intent"),
            query=resolver.get("query"),
            message=message,
            jellyfin_id=one_item.get("id") if one_item else None,
            item=one_item,
            items=resolver.get("items", []),
            playback_plan=playback_plan,
            media_player=resolved_player,
            media_player_name=resolved_player_name,
            add_results=add_results,
        )

    session = await async_prepare_play_session(hass, runtime, media_player=resolved_player)
    if not session.get("success", False):
        message = f"I resolved the media request, but I could not reset the repeat settings for {resolved_player_name}."
        return _base_result(
            success=False,
            status="repeat_reset_failed",
            operation="play",
            intent=resolver.get("intent"),
            query=resolver.get("query"),
            message=message,
            jellyfin_id=resolver.get("jellyfin_id"),
            item=resolver.get("item"),
            items=resolver.get("items", []),
            playback_plan=playback_plan,
            media_player=resolved_player,
            repeat_reset_response=session,
        )

    clear_response = await _action(
        hass,
        runtime,
        SERVICE_QUEUE_CLEAR,
        {"media_player": resolved_player},
        context=context,
    )
    if int(clear_response.get("status", 0) or 0) != 200:
        message = "I resolved the media request, but I could not clear the media queue."
        return _base_result(
            success=False,
            status="queue_clear_failed",
            operation="play",
            intent=resolver.get("intent"),
            query=resolver.get("query"),
            message=message,
            jellyfin_id=resolver.get("jellyfin_id"),
            item=resolver.get("item"),
            items=resolver.get("items", []),
            playback_plan=playback_plan,
            media_player=resolved_player,
            queue_response=clear_response,
        )

    last_queue_response: dict[str, Any] = clear_response
    for item in playback_plan:
        item_type = _text(item.get("type"))
        queue_response = await _action(
            hass,
            runtime,
            SERVICE_QUEUE_ADD,
            {
                "media_player": resolved_player,
                "id": _text(item.get("id")),
                "name": _text(item.get("name")),
                "type": item_type,
                "artist": _text(item.get("artist_name")) or _text(item.get("album_artist")) or _text(item.get("artist")),
                "album": _text(item.get("album")),
                "series": _text(item.get("series_name")) or _text(item.get("series")),
                "season": "" if item_type == "Audio" else item.get("season_name") or item.get("season") or "",
                "episode": "" if item_type == "Audio" else item.get("index_number") if item.get("index_number") is not None else item.get("episode") or "",
            },
            context=context,
        )
        last_queue_response = queue_response
        if int(queue_response.get("status", 0) or 0) != 200:
            message = f"I resolved the media request, but I could not add {_text(item.get('name')) or 'an item'} to the media queue."
            return _base_result(
                success=False,
                status="queue_add_failed",
                operation="play",
                intent=resolver.get("intent"),
                query=resolver.get("query"),
                message=message,
                jellyfin_id=item.get("id"),
                item=item,
                items=resolver.get("items", []),
                playback_plan=playback_plan,
                media_player=resolved_player,
                queue_response=queue_response,
            )

    first_item = playback_plan[0]
    playback = await async_play_item(hass, runtime, item=first_item, media_player=resolved_player)
    success = bool(playback.get("success", False))
    description = _clean_message(_play_description(resolver, first_item, query))
    message = (
        f"Playing {description} on {resolved_player_name}."
        if success
        else f"Queued {len(playback_plan)} item{'s' if len(playback_plan) != 1 else ''}, but playback failed."
    )
    return _base_result(
        success=success,
        status="playing" if success else "playback_failed",
        operation="play",
        intent=resolver.get("intent"),
        query=resolver.get("query"),
        message=message,
        jellyfin_id=first_item.get("id"),
        item=first_item,
        items=resolver.get("items", []),
        playback_plan=playback_plan,
        media_player=resolved_player,
        media_player_name=resolved_player_name,
        queue_response=last_queue_response,
        playback_response=playback,
    )


def _pending_direct_description(item: Mapping[str, Any]) -> str:
    item_type = _text(item.get("type"))
    name = _text(item.get("name")) or "the requested media"
    if item_type == "Episode":
        description = name
        if _text(item.get("series_name")):
            description += f" from {_text(item.get('series_name'))}"
        if item.get("season_number") is not None:
            description += f", Season {item.get('season_number')}"
        if item.get("episode_number") is not None:
            description += f", Episode {item.get('episode_number')}"
        return description
    if item_type == "Audio":
        description = name
        artist = _text(item.get("artist_name")) or _text(item.get("album_artist"))
        if artist:
            description += f" by {artist}"
        if _text(item.get("album")):
            description += f" from {_text(item.get('album'))}"
        return description
    if item_type == "MusicVideo":
        description = name
        artist = _text(item.get("artist_name")) or _text(item.get("album_artist"))
        if artist:
            description += f" by {artist}"
        return description
    if item.get("year"):
        return f"{name} ({item.get('year')})"
    return name


async def async_play_pending_media(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    selection: int,
    context: Any = None,
) -> dict[str, Any]:
    """Resume one pending multiple-match request by selection number."""

    pending = runtime.pending_selection if isinstance(runtime.pending_selection, Mapping) else {}
    pending_items_raw = pending.get("items", []) if isinstance(pending, Mapping) else []
    pending_items = [dict(item) for item in pending_items_raw if isinstance(item, Mapping)] if isinstance(pending_items_raw, list) else []
    pending_player = _text(pending.get("media_player")) if isinstance(pending, Mapping) else ""
    pending_operation = _text(pending.get("operation")).lower() if isinstance(pending, Mapping) else "play"
    if pending_operation not in {"play", "add"}:
        pending_operation = "play"
    pending_query = _text(pending.get("query")) if isinstance(pending, Mapping) else ""
    pending_intent = _text(pending.get("intent")) if isinstance(pending, Mapping) else ""
    try:
        selected_number = int(selection)
    except (TypeError, ValueError):
        selected_number = 0

    if not pending_items or pending_player in {"", "unknown", "unavailable"}:
        return _base_result(
            success=False,
            status="no_pending_selection",
            operation=pending_operation,
            intent=pending_intent or None,
            query=pending_query or None,
            message="There is no pending media selection.",
            media_player=pending_player,
        )
    if selected_number < 1 or selected_number > len(pending_items):
        message = f"Selection {selected_number} is not one of the available media results."
        result = _base_result(
            success=False,
            status="invalid_selection",
            operation=pending_operation,
            intent=pending_intent or None,
            query=pending_query or None,
            message=message,
            media_player=pending_player,
        )
        result["pending_items"] = pending_items
        return result

    selected_id = _text(pending_items[selected_number - 1].get("id"))
    if not selected_id:
        message = f"Selection {selected_number} is not one of the available media results."
        return _base_result(
            success=False,
            status="invalid_selection",
            operation=pending_operation,
            intent=pending_intent or None,
            query=pending_query or None,
            message=message,
            media_player=pending_player,
            pending_items=pending_items,
        )

    try:
        raw = await async_get_native_item(runtime, selected_id)
    except Exception as err:
        return _base_result(
            success=False,
            status="item_lookup_failed",
            operation=pending_operation,
            intent=pending_intent or None,
            query=pending_query or None,
            message="I could not retrieve the selected media item from Jellyfin.",
            jellyfin_id=selected_id,
            media_player=pending_player,
            item_response={"error": str(err)},
        )
    if not raw.get("Id") or not raw.get("Name") or not raw.get("Type"):
        return _base_result(
            success=False,
            status="item_lookup_failed",
            operation=pending_operation,
            intent=pending_intent or None,
            query=pending_query or None,
            message="I could not retrieve the selected media item from Jellyfin.",
            jellyfin_id=selected_id,
            media_player=pending_player,
            item_response={"item": dict(raw)},
        )

    item = normalize_jellyfin_item(raw)
    selected_type = _text(item.get("type"))
    selected_type_key = selected_type.lower()
    selected_name = _text(item.get("name"))
    if selected_type_key in _CONTAINER_ITEM_TYPES:
        result = await async_media_orchestrator(
            hass,
            runtime,
            query=selected_name,
            media_player=pending_player,
            operation=pending_operation,
            media_type=selected_type,
            artist=(
                _text(item.get("artist_name")) or _text(item.get("album_artist"))
                if selected_type_key == "musicalbum"
                else ""
            ),
            year=_optional_int(item.get("year")),
            context=context,
        )
        if pending_query:
            result["query"] = pending_query
        if pending_intent:
            result["intent"] = pending_intent
        if result.get("success", False):
            runtime.pending_selection = None
        return result

    if selected_type not in _PLAYABLE_ITEM_TYPES:
        message = f"I found {selected_name}, but that type of item cannot be queued directly."
        return _base_result(
            success=False,
            status="not_playable",
            operation=pending_operation,
            intent=selected_type,
            query=pending_query or None,
            message=message,
            jellyfin_id=selected_id,
            item=item,
            items=[item],
            media_player=pending_player,
        )

    playback_plan = [item]
    if pending_operation == "add":
        response = await _action(
            hass,
            runtime,
            SERVICE_QUEUE_ADD,
            {
                "media_player": pending_player,
                "id": selected_id,
                "name": selected_name,
                "type": selected_type,
                "artist": _text(item.get("artist_name")) or _text(item.get("album_artist")),
                "album": _text(item.get("album")),
                "series": _text(item.get("series_name")),
                "season": item.get("season_number") if item.get("season_number") is not None else "",
                "episode": item.get("episode_number") if item.get("episode_number") is not None else "",
            },
            context=context,
        )
        body = response.get("content") if isinstance(response.get("content"), Mapping) else {}
        if int(response.get("status", 0) or 0) != 200 or not body.get("success", False):
            message = f"I found {selected_name}, but I could not add it to the media queue."
            return _base_result(
                success=False,
                status="queue_add_failed",
                operation="add",
                intent=selected_type,
                query=pending_query or None,
                message=message,
                jellyfin_id=selected_id,
                item=item,
                items=[item],
                playback_plan=playback_plan,
                media_player=pending_player,
                queue_response=response,
            )
        runtime.pending_selection = None
        description = selected_name + (f" ({item.get('year')})" if item.get("year") else "")
        message = f"Added {description} to the queue for {_state_friendly_name(hass, pending_player)}."
        return _base_result(
            success=True,
            status="added",
            operation="add",
            intent=selected_type,
            query=pending_query or None,
            message=message,
            jellyfin_id=selected_id,
            item=item,
            items=[item],
            playback_plan=playback_plan,
            media_player=pending_player,
            queue_response=response,
        )

    session = await async_prepare_play_session(hass, runtime, media_player=pending_player)
    if not session.get("success", False):
        message = f"I found {selected_name}, but I could not reset the repeat settings for {_state_friendly_name(hass, pending_player)}."
        return _base_result(
            success=False,
            status="repeat_reset_failed",
            operation="play",
            intent=selected_type,
            query=pending_query or None,
            message=message,
            jellyfin_id=selected_id,
            item=item,
            items=[item],
            playback_plan=playback_plan,
            media_player=pending_player,
            repeat_reset_response=session,
        )

    clear_response = await _action(
        hass,
        runtime,
        SERVICE_QUEUE_CLEAR,
        {"media_player": pending_player},
        context=context,
    )
    if int(clear_response.get("status", 0) or 0) != 200:
        return _base_result(
            success=False,
            status="queue_clear_failed",
            operation="play",
            intent=selected_type,
            query=pending_query or None,
            message=f"I found {selected_name}, but I could not clear the media queue.",
            jellyfin_id=selected_id,
            item=item,
            items=[item],
            playback_plan=playback_plan,
            media_player=pending_player,
            queue_response=clear_response,
        )
    queue_response = await _action(
        hass,
        runtime,
        SERVICE_QUEUE_ADD,
        {
            "media_player": pending_player,
            "id": selected_id,
            "name": selected_name,
            "type": selected_type,
            "artist": _text(item.get("artist_name")) or _text(item.get("album_artist")),
            "album": _text(item.get("album")),
            "series": _text(item.get("series_name")),
            "season": item.get("season_number") if item.get("season_number") is not None else "",
            "episode": item.get("episode_number") if item.get("episode_number") is not None else "",
        },
        context=context,
    )
    body = queue_response.get("content") if isinstance(queue_response.get("content"), Mapping) else {}
    if int(queue_response.get("status", 0) or 0) != 200 or not body.get("success", False):
        return _base_result(
            success=False,
            status="queue_add_failed",
            operation="play",
            intent=selected_type,
            query=pending_query or None,
            message=f"I found {selected_name}, but I could not add it to the media queue.",
            jellyfin_id=selected_id,
            item=item,
            items=[item],
            playback_plan=playback_plan,
            media_player=pending_player,
            queue_response=queue_response,
        )
    playback = await async_play_item(hass, runtime, item=item, media_player=pending_player)
    success = bool(playback.get("success", False))
    if success:
        runtime.pending_selection = None
    description = _clean_message(_pending_direct_description(item))
    message = (
        f"Playing {description} on {_state_friendly_name(hass, pending_player)}."
        if success
        else f"I found {selected_name}, but playback failed."
    )
    return _base_result(
        success=success,
        status="playing" if success else "playback_failed",
        operation="play",
        intent=selected_type,
        query=pending_query or None,
        message=message,
        jellyfin_id=selected_id,
        item=item,
        items=[item],
        playback_plan=playback_plan,
        media_player=pending_player,
        queue_response=queue_response,
        playback_response=playback,
    )


async def async_resume_pending_media_request(
    hass: Any,
    runtime: JellyfinAssistRuntime,
    *,
    media_player: str,
    context: Any = None,
) -> dict[str, Any]:
    """Resume the media or queue request waiting for a player selection."""

    pending = await _action(
        hass,
        runtime,
        SERVICE_RESUME_MEDIA_REQUEST,
        {"media_player": media_player},
        context=context,
    )
    if not pending.get("success", False):
        message = (
            "That media player is not available."
            if pending.get("status") == "invalid_media_player"
            else "There is no media request waiting for a player."
        )
        return _base_result(
            success=False,
            status=_text(pending.get("status")) or "no_pending_media_request",
            operation="resume",
            intent=None,
            query=None,
            message=message,
            media_player=media_player,
        )

    operation = _text(pending.get("operation")) or "play"
    if operation in QUEUE_PLAYER_OPERATIONS:
        return await async_queue_command(
            hass,
            runtime,
            operation=operation,
            media_player=_text(pending.get("media_player")),
            media_player_display_name=_text(pending.get("media_player_name")),
            context=context,
        )
    return await async_media_orchestrator(
        hass,
        runtime,
        query=_text(pending.get("query")),
        media_player=_text(pending.get("media_player")),
        media_player_display_name=_text(pending.get("media_player_name")),
        operation=operation,
        media_type=_text(pending.get("media_type")) or None,
        artist=_text(pending.get("artist")),
        year=_optional_int(pending.get("year")),
        series=_text(pending.get("series")),
        season=_optional_int(pending.get("season")),
        episode=_optional_int(pending.get("episode")),
        context=context,
    )


__all__ = [
    "async_media_orchestrator",
    "async_play_pending_media",
    "async_resolve_episode_title",
    "async_resolve_media_intent",
    "async_resolve_tv_episode",
    "async_resume_pending_media_request",
    "normalize_jellyfin_item",
]
