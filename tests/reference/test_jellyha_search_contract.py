"""Characterize the frozen JellyHA ``search`` action contract.

This suite protects the known stable boundary before robust matching is added.
It deliberately parses the frozen reference source instead of importing Home
Assistant, so it can run in a small and deterministic test environment.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
SERVICES_PY: Final = (
    REPOSITORY_ROOT
    / "reference"
    / "current-working"
    / "jellyha"
    / "services.py"
)
SERVICES_YAML: Final = SERVICES_PY.with_name("services.yaml")

EXPECTED_SEARCH_FIELDS: Final = {
    "query",
    "media_type",
    "limit",
    "is_played",
    "is_favorite",
    "genre",
    "year",
    "min_rating",
    "season",
    "episode",
    "entity_id",
    "config_entry_id",
}

EXPECTED_MEDIA_TYPES: Final = [
    "Movie",
    "Series",
    "Episode",
    "Audio",
    "MusicAlbum",
    "MusicArtist",
    "MusicVideo",
    "Video",
    "Playlist",
    "BoxSet",
]

EXPECTED_LIBRARY_KEYWORDS: Final = {
    "user_id": "user_id",
    "limit": "limit",
    "search_term": "query",
    "item_types": "[media_type] if media_type else None",
    "is_played": "call.data.get('is_played')",
    "is_favorite": "call.data.get('is_favorite')",
    "genre": "call.data.get('genre')",
    "year": "call.data.get('year')",
    "min_rating": "call.data.get('min_rating')",
    "season": "call.data.get('season')",
    "episode": "call.data.get('episode')",
}


@dataclass(frozen=True)
class SchemaField:
    """A field declared in a Voluptuous schema."""

    name: str
    marker: str
    default: object | None
    validator: ast.AST


def _parse_services_module() -> ast.Module:
    """Parse the frozen service implementation."""
    return ast.parse(SERVICES_PY.read_text(encoding="utf-8"), filename=str(SERVICES_PY))


def _dotted_name(node: ast.AST) -> str:
    """Return a dotted name for a Name/Attribute expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal(node: ast.AST) -> object:
    """Evaluate an AST node that is expected to contain only literals."""
    return ast.literal_eval(node)


def _find_assignment(module: ast.Module, name: str) -> ast.AST:
    """Return the value assigned to a top-level name."""
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in statement.targets):
            return statement.value
    raise AssertionError(f"Top-level assignment {name!r} was not found in {SERVICES_PY}")


def _find_async_function(tree: ast.AST, name: str) -> ast.AsyncFunctionDef:
    """Find an async function anywhere in an AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Async function {name!r} was not found in {SERVICES_PY}")


def _find_calls(tree: ast.AST, dotted_name: str) -> list[ast.Call]:
    """Find calls whose callable has the requested dotted name."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _dotted_name(node.func) == dotted_name
    ]


def _schema_fields(module: ast.Module) -> dict[str, SchemaField]:
    """Extract fields from the frozen ``SEARCH_SCHEMA`` declaration."""
    schema_assignment = _find_assignment(module, "SEARCH_SCHEMA")
    assert isinstance(schema_assignment, ast.Call)
    assert _dotted_name(schema_assignment.func) == "vol.Schema"
    assert len(schema_assignment.args) == 1

    schema_dict = schema_assignment.args[0]
    assert isinstance(schema_dict, ast.Dict)

    fields: dict[str, SchemaField] = {}
    for key_node, validator in zip(schema_dict.keys, schema_dict.values, strict=True):
        assert isinstance(key_node, ast.Call)
        marker = _dotted_name(key_node.func)
        assert marker in {"vol.Optional", "vol.Required"}
        assert key_node.args

        field_name = _literal(key_node.args[0])
        assert isinstance(field_name, str)

        default: object | None = None
        for keyword in key_node.keywords:
            if keyword.arg == "default":
                default = _literal(keyword.value)

        fields[field_name] = SchemaField(
            name=field_name,
            marker=marker,
            default=default,
            validator=validator,
        )

    return fields


def _source(node: ast.AST) -> str:
    """Render a normalized source fragment for stable comparisons."""
    return ast.unparse(node)


def test_reference_files_exist() -> None:
    """The frozen implementation and action description must remain available."""
    assert SERVICES_PY.is_file()
    assert SERVICES_YAML.is_file()


def test_search_schema_fields_and_defaults_are_frozen() -> None:
    """Record the currently accepted Python action fields and default limit."""
    module = _parse_services_module()
    fields = _schema_fields(module)

    assert set(fields) == EXPECTED_SEARCH_FIELDS
    assert all(field.marker == "vol.Optional" for field in fields.values())
    assert fields["limit"].default == 5
    assert all(
        field.default is None
        for name, field in fields.items()
        if name != "limit"
    )


def test_search_schema_media_types_are_frozen() -> None:
    """Record the media types accepted by the current Python action schema."""
    module = _parse_services_module()
    media_type_validator = _schema_fields(module)["media_type"].validator

    assert isinstance(media_type_validator, ast.Call)
    assert _dotted_name(media_type_validator.func) == "vol.In"
    assert len(media_type_validator.args) == 1
    assert _literal(media_type_validator.args[0]) == EXPECTED_MEDIA_TYPES


def test_search_action_documentation_matches_python_schema() -> None:
    """Keep the service UI field list aligned with the Python schema."""
    service_descriptions = yaml.safe_load(SERVICES_YAML.read_text(encoding="utf-8"))
    assert isinstance(service_descriptions, dict)

    search_description = service_descriptions["search"]
    documented_fields = search_description["fields"]

    # entity_id is accepted programmatically for coordinator resolution but is
    # intentionally not exposed in the service UI.
    assert set(documented_fields) == EXPECTED_SEARCH_FIELDS - {"entity_id"}

    media_options = documented_fields["media_type"]["selector"]["select"]["options"]
    assert [option["value"] for option in media_options] == EXPECTED_MEDIA_TYPES


def test_non_artist_search_is_a_single_jellyfin_library_query() -> None:
    """Record the exact parameter pass-through used for normal media searches."""
    module = _parse_services_module()
    async_search = _find_async_function(module, "async_search")
    calls = _find_calls(async_search, "coordinator._api.get_library_items")

    assert len(calls) == 1
    call = calls[0]
    assert not call.args
    assert {keyword.arg for keyword in call.keywords} == set(EXPECTED_LIBRARY_KEYWORDS)

    actual_keywords = {
        keyword.arg: _source(keyword.value)
        for keyword in call.keywords
        if keyword.arg is not None
    }
    assert actual_keywords == EXPECTED_LIBRARY_KEYWORDS


def test_music_artist_search_uses_album_artist_endpoint() -> None:
    """Record the current special-case Jellyfin endpoint for artist searches."""
    module = _parse_services_module()
    async_search = _find_async_function(module, "async_search")
    request_calls = _find_calls(async_search, "coordinator._api._request")

    matching_calls = [
        call
        for call in request_calls
        if len(call.args) >= 2
        and _literal(call.args[0]) == "GET"
        and _literal(call.args[1]) == "/Artists/AlbumArtists"
    ]
    assert len(matching_calls) == 1


def test_search_transforms_every_returned_jellyfin_item() -> None:
    """Record the item-transform boundary used by downstream YAML scripts."""
    module = _parse_services_module()
    async_search = _find_async_function(module, "async_search")
    transform_calls = _find_calls(async_search, "coordinator._async_transform_item")
    gather_calls = _find_calls(async_search, "asyncio.gather")

    assert len(transform_calls) == 1
    assert len(gather_calls) == 1
    assert _source(transform_calls[0].args[0]) == "item"


def test_search_response_shape_is_items_only() -> None:
    """Protect the response key consumed by the stable resolver."""
    module = _parse_services_module()
    async_search = _find_async_function(module, "async_search")

    dictionary_returns = [
        node.value
        for node in ast.walk(async_search)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    ]
    assert len(dictionary_returns) == 1

    response = dictionary_returns[0]
    assert [_literal(key) for key in response.keys] == ["items"]
    assert [_source(value) for value in response.values] == ["results"]


def test_search_is_registered_as_a_response_only_action() -> None:
    """Record that callers must request and receive a service response."""
    module = _parse_services_module()
    register_services = _find_async_function(module, "async_register_services")

    service_map_assignments = [
        node
        for node in register_services.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "service_map"
            for target in node.targets
        )
    ]
    assert len(service_map_assignments) == 1

    service_map = service_map_assignments[0].value
    assert isinstance(service_map, ast.List)

    search_entries = [
        element
        for element in service_map.elts
        if isinstance(element, ast.Tuple)
        and element.elts
        and _source(element.elts[0]) == "SERVICE_SEARCH"
    ]
    assert len(search_entries) == 1
    assert [_source(element) for element in search_entries[0].elts] == [
        "SERVICE_SEARCH",
        "async_search",
        "SEARCH_SCHEMA",
        "True",
    ]


def test_search_does_not_invoke_playback_or_queue_services() -> None:
    """Protect the separation between search and the stable execution pipeline."""
    module = _parse_services_module()
    async_search = _find_async_function(module, "async_search")

    called_names = {
        _dotted_name(node.func)
        for node in ast.walk(async_search)
        if isinstance(node, ast.Call)
    }

    assert "hass.services.async_call" not in called_names
    assert not any("queue" in name.casefold() for name in called_names)
    assert not any("play" in name.casefold() for name in called_names)
