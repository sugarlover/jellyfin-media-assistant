"""Characterize the stable JellyHA Chromecast playback action contract.

The production YAML still calls ``jellyha.play_on_chromecast``.  These tests
freeze that boundary before Jellyfin Media Assistant registers a parallel
native action for live parity testing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import yaml

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
SERVICES_PY: Final = (
    REPOSITORY_ROOT / "reference" / "current-working" / "jellyha" / "services.py"
)
SERVICES_YAML: Final = SERVICES_PY.with_name("services.yaml")


def _parse() -> ast.Module:
    return ast.parse(SERVICES_PY.read_text(encoding="utf-8"), filename=str(SERVICES_PY))


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _source(node: ast.AST) -> str:
    return ast.unparse(node)


def _find_assignment(module: ast.Module, name: str) -> ast.AST:
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return statement.value
    raise AssertionError(f"Missing assignment {name!r}")


def _find_async_function(module: ast.Module, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(module):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing async function {name!r}")


def _find_calls(tree: ast.AST, dotted_name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _dotted_name(node.func) == dotted_name
    ]


def test_play_on_chromecast_action_fields_are_frozen() -> None:
    service_doc = yaml.safe_load(SERVICES_YAML.read_text(encoding="utf-8"))
    fields = service_doc["play_on_chromecast"]["fields"]

    assert set(fields) == {"entity_id", "item_id", "config_entry_id"}
    assert fields["entity_id"]["required"] is True
    assert fields["item_id"]["required"] is True
    assert fields["config_entry_id"]["required"] is False

    module = _parse()
    schema = _find_assignment(module, "PLAY_ON_CHROMECAST_SCHEMA")
    assert isinstance(schema, ast.Call)
    schema_dict = schema.args[0]
    assert isinstance(schema_dict, ast.Dict)
    python_fields = {
        ast.literal_eval(key.args[0])
        for key in schema_dict.keys
        if isinstance(key, ast.Call) and key.args
    }
    assert python_fields == {
        "entity_id",
        "item_id",
        "server_entity_id",
        "config_entry_id",
    }


def test_playback_fetches_item_and_resolves_series_or_season_to_next_up() -> None:
    handler = _find_async_function(_parse(), "async_play_on_device")

    get_item_calls = _find_calls(handler, "api.get_item")
    next_up_calls = _find_calls(handler, "api.get_next_up_episode")

    assert len(get_item_calls) == 1
    assert [_source(arg) for arg in get_item_calls[0].args] == ["user_id", "item_id"]
    assert len(next_up_calls) == 1
    assert [_source(arg) for arg in next_up_calls[0].args] == ["user_id", "series_id"]


def test_playback_uses_executor_model_discovery_and_media_strategy() -> None:
    handler = _find_async_function(_parse(), "async_play_on_device")

    executor_calls = _find_calls(handler, "hass.async_add_executor_job")
    analyze_calls = _find_calls(handler, "MediaStrategy.analyze_media")
    playback_info_calls = _find_calls(handler, "MediaStrategy.get_playback_info")

    assert len(executor_calls) == 1
    assert _source(executor_calls[0].args[0]) == "MediaStrategy.discover_chromecast_model"
    assert _source(executor_calls[0].args[1]) == "hass"
    assert _source(executor_calls[0].args[2]) == "target_entity_id"
    assert len(analyze_calls) == 1
    assert _source(analyze_calls[0].args[0]) == "item"
    assert len(playback_info_calls) == 1
    assert [_source(arg) for arg in playback_info_calls[0].args[:5]] == [
        "api._server_url",
        "api._api_key",
        "item_id",
        "media_info",
        "model_name",
    ]


def test_playback_delegates_actual_cast_to_home_assistant_play_media() -> None:
    handler = _find_async_function(_parse(), "async_play_on_device")
    service_calls = _find_calls(handler, "hass.services.async_call")

    matching = [
        call
        for call in service_calls
        if len(call.args) >= 2
        and _source(call.args[0]) == "MEDIA_PLAYER_DOMAIN"
        and _source(call.args[1]) == "SERVICE_PLAY_MEDIA"
    ]
    assert len(matching) == 1
    call = matching[0]
    assert any(
        keyword.arg == "blocking" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in call.keywords
    )

    payload = call.args[2]
    assert isinstance(payload, ast.Dict)
    payload_source = _source(payload)
    assert "ATTR_MEDIA_CONTENT_ID: playback_info['media_url']" in payload_source
    assert "ATTR_MEDIA_CONTENT_TYPE: playback_info['content_type']" in payload_source
    assert "'autoplay': True" in payload_source
    assert "'metadata': metadata" in payload_source


def test_episode_metadata_fields_are_preserved() -> None:
    handler = _find_async_function(_parse(), "async_play_on_device")
    source = _source(handler)

    assert "'metadataType': 1" in source
    assert "'seriesTitle': item.get('SeriesName')" in source
    assert "'season': item.get('ParentIndexNumber')" in source
    assert "'episode': item.get('IndexNumber')" in source
