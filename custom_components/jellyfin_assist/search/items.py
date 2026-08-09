"""Shared conversion helpers for raw or transformed Jellyfin catalog items.

The search engine encounters two closely related item shapes during the
migration away from JellyHA search:

* raw Jellyfin dictionaries (``Id``, ``Name``, ``Type``, ``Artists``), and
* JellyHA-transformed dictionaries (``id``, ``name``, ``type``,
  ``artist_name``).

This module provides one Home-Assistant-independent conversion boundary so the
remote retrieval path and the local catalog index cannot drift apart.  It also
extracts provider identifiers used for narrowly scoped logical grouping.  The
first grouping rule is deliberately conservative: only ``MusicArtist`` records
sharing a trusted MusicBrainz artist identifier may be grouped automatically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from ..matching.aliases import stylized_numeric_aliases
from ..matching.context import MediaCandidate


_NON_ALPHANUMERIC_RE = re.compile(r"[^a-z0-9]+")
_MUSIC_ARTIST_TYPE = "musicartist"
_MUSICBRAINZ_ARTIST_KEYS = frozenset({"musicbrainzartist", "musicbrainz"})


def first_nonempty(item: Mapping[str, Any], *keys: str) -> str | None:
    """Return the first non-empty string stored under ``keys``."""

    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def catalog_item_id(item: Mapping[str, Any]) -> str | None:
    """Return a normalized Jellyfin item ID from either supported item shape."""

    return first_nonempty(item, "id", "Id")


def _normalize_provider_key(value: str) -> str:
    return _NON_ALPHANUMERIC_RE.sub("", value.casefold())


def _normalize_provider_value(value: str) -> str:
    """Normalize a provider identifier without changing its identity."""

    return value.strip().strip("{}").casefold()


def catalog_provider_ids(
    item: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    """Return normalized provider-ID pairs from either supported item shape.

    Provider names are case- and punctuation-folded, and identifier values are
    whitespace/braces trimmed and case-folded.  Empty or non-string entries are
    ignored.  The stable sorted tuple is safe to store in frozen diagnostics.
    """

    raw: Any = item.get("provider_ids")
    if not isinstance(raw, Mapping):
        raw = item.get("ProviderIds")
    if not isinstance(raw, Mapping):
        return ()

    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        normalized_key = _normalize_provider_key(key)
        normalized_value = _normalize_provider_value(value)
        if normalized_key and normalized_value:
            normalized[normalized_key] = normalized_value
    return tuple(sorted(normalized.items()))


def trusted_logical_group_key(
    item: Mapping[str, Any],
    media_type: str | None = None,
) -> str | None:
    """Return a conservative logical-group key for one catalog item.

    Only music artists with a trusted MusicBrainz artist ID are currently
    eligible.  Same-name records without provider IDs, conflicting IDs, and all
    non-artist media remain physically separate.
    """

    resolved_type = media_type or first_nonempty(item, "type", "Type")
    if not isinstance(resolved_type, str):
        return None
    normalized_type = _NON_ALPHANUMERIC_RE.sub("", resolved_type.casefold())
    if normalized_type != _MUSIC_ARTIST_TYPE:
        return None

    providers = dict(catalog_provider_ids(item))
    for key in _MUSICBRAINZ_ARTIST_KEYS:
        value = providers.get(key)
        if value:
            return f"musicartist:musicbrainzartist:{value}"
    return None


def first_artist(item: Mapping[str, Any]) -> str | None:
    """Return the first useful artist value from a catalog item."""

    direct = first_nonempty(
        item,
        "artist_name",
        "artist",
        "Artist",
        "album_artist",
        "AlbumArtist",
    )
    if direct is not None:
        return direct

    for key in ("artists", "Artists"):
        value = item.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for artist in value:
                if isinstance(artist, str) and artist.strip():
                    return artist.strip()
    return None


def first_year(item: Mapping[str, Any]) -> int | str | None:
    """Return the first production-year value without changing its meaning."""

    for key in ("year", "ProductionYear"):
        value = item.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def catalog_item_to_media_candidate(
    item: Mapping[str, Any],
    *,
    item_id: str | None = None,
) -> MediaCandidate | None:
    """Convert one catalog mapping into a ranking candidate.

    ``None`` is returned only when the item has no usable title.  Callers that
    require an ID may pass a previously validated ``item_id``; otherwise the ID
    is read from the mapping.
    """

    key = item_id or catalog_item_id(item)
    if key is None:
        return None

    title = first_nonempty(item, "name", "Name", "title", "Title")
    if title is None:
        return None

    media_type = first_nonempty(item, "type", "Type")
    return MediaCandidate(
        key=key,
        title=title,
        media_type=media_type,
        artist=first_artist(item),
        album=first_nonempty(item, "album", "Album"),
        series=first_nonempty(
            item,
            "series_name",
            "SeriesName",
            "series",
            "Series",
        ),
        year=first_year(item),
        title_aliases=stylized_numeric_aliases(title, media_type),
        provider_ids=catalog_provider_ids(item),
        physical_keys=(key,),
    )
