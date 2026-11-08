"""Native and legacy-compatible Jellyfin item lookup helpers.

The successful response shape intentionally matches JellyHA 1.2.0 get_item.
Derived behavior is attributed in THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .runtime import JellyfinAssistRuntime


def enrich_jellyha_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy enriched exactly like JellyHA's get_item action."""

    result = dict(item)
    media_sources = result.get("MediaSources")
    if isinstance(media_sources, list) and media_sources:
        first_source = media_sources[0]
        result["media_streams"] = (
            first_source.get("MediaStreams", [])
            if isinstance(first_source, Mapping)
            else []
        )
    elif "MediaStreams" in result:
        result["media_streams"] = result.get("MediaStreams")

    user_data = result.get("UserData")
    if not isinstance(user_data, Mapping):
        user_data = {}
    result["is_favorite"] = user_data.get("IsFavorite", False)
    result["is_played"] = user_data.get("Played", False)
    return result


async def async_get_native_item(
    runtime: JellyfinAssistRuntime,
    item_id: str,
) -> dict[str, Any]:
    """Fetch and enrich one item with the native read-only client."""

    item = await runtime.client.async_get_item(runtime.user_id, item_id)
    return enrich_jellyha_item(item)


__all__ = [
    "async_get_native_item",
    "enrich_jellyha_item",
]
