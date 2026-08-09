"""Native and legacy-compatible Jellyfin item lookup helpers.

The successful response shape intentionally matches JellyHA 1.2.0 get_item.
Derived behavior is attributed in THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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


def _diff_paths(left: Any, right: Any, path: str = "$") -> list[str]:
    """Return deterministic JSON-style paths whose values differ."""

    if isinstance(left, Mapping) and isinstance(right, Mapping):
        differences: list[str] = []
        for key in sorted(set(left) | set(right), key=str):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                differences.append(child)
            else:
                differences.extend(_diff_paths(left[key], right[key], child))
        return differences
    if isinstance(left, list) and isinstance(right, list):
        differences = []
        if len(left) != len(right):
            differences.append(f"{path}.length")
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            differences.extend(_diff_paths(left_item, right_item, f"{path}[{index}]"))
        return differences
    return [] if left == right else [path]


@dataclass(frozen=True, slots=True)
class ItemParity:
    """Exact response-parity result for native and JellyHA item lookups."""

    exact_match: bool
    differing_paths: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "agree" if self.exact_match else "differ",
            "exact_match": self.exact_match,
            "differing_paths": list(self.differing_paths),
        }


def compare_item_responses(
    native_response: Mapping[str, Any],
    jellyha_response: Mapping[str, Any],
) -> ItemParity:
    """Compare complete response mappings without weakening the contract."""

    differences = tuple(_diff_paths(native_response, jellyha_response))
    return ItemParity(exact_match=not differences, differing_paths=differences)


__all__ = [
    "ItemParity",
    "async_get_native_item",
    "compare_item_responses",
    "enrich_jellyha_item",
]
