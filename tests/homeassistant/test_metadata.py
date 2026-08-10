"""Static integration metadata and UI-contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "custom_components" / "jellyfin_assist"


def test_manifest_is_loadable_custom_integration() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == "jellyfin_assist"
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "service"
    assert manifest["version"] == "0.1.0-beta.2"
    assert manifest["dependencies"] == ["cast"]
    assert manifest["documentation"] == "https://github.com/sugarlover/jellyfin-media-assistant#readme"
    assert manifest["issue_tracker"] == "https://github.com/sugarlover/jellyfin-media-assistant/issues"
    assert manifest["codeowners"] == ["@sugarlover"]
    assert manifest["requirements"] == []


def test_custom_integration_uses_flat_english_translation_file() -> None:
    translations = json.loads(
        (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8")
    )

    assert translations["title"] == "Jellyfin Media Assistant"
    assert translations["config"]["step"]["user"]["data"]["api_key"] == "API key"
    assert "exceptions" in translations
    assert translations["services"]["search"]["fields"]["query"]["name"] == "Query"
    assert translations["services"]["refresh_catalog"]["name"] == "Refresh Jellyfin catalog"
    assert translations["services"]["get_item"]["fields"]["item_id"]["name"] == "Item ID"
    assert translations["services"]["play_on_chromecast"]["fields"]["entity_id"]["name"] == "Media player"
    assert translations["options"]["step"]["init"]["data"]["default_media_player"] == "Default Media Player"
    assert translations["options"]["step"]["init"]["data"]["playback_targets"] == "Playback Targets"
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    assert strings["options"] == translations["options"]
    assert translations["services"]["resolve_media_player"]["fields"]["media_player"]["name"] == "Media player"


def test_services_yaml_describes_catalog_refresh_action() -> None:
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))

    fields = services["refresh_catalog"]["fields"]
    assert fields["config_entry_id"]["required"] is False
    assert fields["config_entry_id"]["selector"]["config_entry"]["integration"] == "jellyfin_assist"


def test_services_yaml_describes_response_only_search_inputs() -> None:
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))
    fields = services["search"]["fields"]

    assert fields["query"]["required"] is True
    assert fields["config_entry_id"]["required"] is False
    assert fields["media_type"]["selector"]["select"]["options"] == [
        "Movie",
        "Series",
        "Episode",
        "Audio",
        "MusicAlbum",
        "MusicArtist",
    ]


def test_services_yaml_describes_player_resolution_and_resume_actions() -> None:
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))

    resolve_fields = services["resolve_media_player"]["fields"]
    assert resolve_fields["config_entry_id"]["required"] is False
    assert resolve_fields["media_player"]["required"] is False
    assert "text" in resolve_fields["media_player"]["selector"]

    resume_fields = services["resume_media_request"]["fields"]
    assert resume_fields["config_entry_id"]["required"] is False
    assert resume_fields["media_player"]["required"] is True
    assert "text" in resume_fields["media_player"]["selector"]


def test_services_yaml_describes_standalone_native_get_item() -> None:
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))

    native = services["get_item"]["fields"]
    assert native["config_entry_id"]["required"] is False
    assert native["item_id"]["required"] is True
    assert "compare_get_item" not in services


def test_services_yaml_describes_parallel_native_chromecast_action() -> None:
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))
    fields = services["play_on_chromecast"]["fields"]

    assert fields["config_entry_id"]["required"] is False
    assert fields["config_entry_id"]["selector"]["config_entry"]["integration"] == "jellyfin_assist"
    assert fields["entity_id"]["required"] is True
    assert fields["entity_id"]["selector"]["entity"]["domain"] == "media_player"
    assert fields["item_id"]["required"] is True


def test_services_yaml_describes_native_queue_actions() -> None:
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))

    expected = {
        "queue_get",
        "queue_add",
        "queue_next",
        "queue_clear",
        "queue_set_repeat",
        "queue_shuffle",
    }
    assert expected <= set(services)
    assert services["queue_add"]["fields"]["id"]["required"] is True
    assert "queue_remove" not in services
    assert services["queue_set_repeat"]["fields"]["repeat_item"]["required"] is True


def test_services_yaml_describes_native_media_orchestration_actions() -> None:
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))

    expected = {
        "media_orchestrator",
        "play_pending_media",
        "resume_pending_media_request",
    }
    assert expected <= set(services)
    assert services["media_orchestrator"]["fields"]["query"]["required"] is True
    assert services["play_pending_media"]["fields"]["selection"]["required"] is True
    assert services["resume_pending_media_request"]["fields"]["media_player"]["required"] is True

    retired_bridges = {
        "pending_selection_get",
        "pending_selection_set",
        "pending_selection_clear",
        "play_item",
        "queue_add_item",
        "prepare_play_session",
    }
    assert retired_bridges.isdisjoint(services)


def test_services_yaml_describes_native_library_query_actions() -> None:
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))

    expected = {
        "search_season",
        "search_episode",
        "search_episode_title",
        "get_album_tracks",
        "get_artist_tracks",
    }
    assert expected <= set(services)
    assert services["search_season"]["fields"]["series_id"]["required"] is True
    assert services["search_episode"]["fields"]["episode"]["required"] is True
    assert services["search_episode_title"]["fields"]["episode_title"]["required"] is True
    assert services["get_album_tracks"]["fields"]["album_id"]["required"] is True
    assert services["get_artist_tracks"]["fields"]["artist_id"]["required"] is True
