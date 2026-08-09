"""Release guardrails for the completed Jellyfin Assist namespace/YAML migration."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Final

import yaml

ROOT: Final = Path(__file__).resolve().parents[2]
HA: Final = ROOT / "reference" / "current-working" / "home-assistant"
SCRIPTS: Final = HA / "scripts.yaml"
CONFIGURATION: Final = HA / "configuration.yaml"
SENTENCES: Final = ROOT / "custom_components" / "jellyfin_assist" / "custom_sentences" / "en" / "jellyfin_assist_media.yaml"
QUEUE_SERVICE: Final = ROOT / "reference" / "current-working" / "queue-service"
INTEGRATION: Final = ROOT / "custom_components" / "jellyfin_assist"


def test_project_owned_scripts_yaml_is_fully_retired() -> None:
    assert not SCRIPTS.exists()
    configuration = CONFIGURATION.read_text(encoding="utf-8")
    assert "script: !include scripts.yaml" not in configuration


def test_integration_runtime_contains_no_home_assistant_script_calls() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in INTEGRATION.rglob("*.py"))
    assert "script.jellyha_" not in source
    assert "script.jellyfin_assist_" not in source
    assert 'domain: str = "script"' not in source


def test_new_user_facing_text_no_longer_calls_the_project_jellyha() -> None:
    assert "JellyHA " not in CONFIGURATION.read_text(encoding="utf-8")


def test_legacy_rest_helpers_and_intent_script_are_retired() -> None:
    configuration = CONFIGURATION.read_text(encoding="utf-8")
    assert "rest_command:" not in configuration
    assert "input_text." not in configuration
    assert "input_boolean." not in configuration
    assert "intent_script:" not in configuration
    assert re.search(r"(?m)^  JellyHA[A-Za-z0-9_]+:\s*$", configuration) is None


def test_canonical_sentence_namespace_only() -> None:
    sentence_data = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))
    sentence_intents = set(sentence_data["intents"])
    assert sentence_intents
    assert all(name.startswith("JellyfinAssist") for name in sentence_intents)


def test_external_queue_service_is_fully_retired() -> None:
    assert not QUEUE_SERVICE.exists()
    assert not (INTEGRATION / "queue.py").exists()
    assert (INTEGRATION / "queue_store.py").exists()
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8") for path in INTEGRATION.rglob("*.py")
    )
    assert "QueueServiceClient" not in runtime_text
    assert "DEFAULT_QUEUE_SERVICE_PORT" not in runtime_text
    assert "8787" not in runtime_text


def test_deferred_queue_remove_is_not_exposed_as_native_action() -> None:
    services_text = (INTEGRATION / "services.yaml").read_text(encoding="utf-8")
    assert "queue_remove:" not in services_text
    assert "queue_settings:" not in services_text
    assert "queue_set_repeat:" in services_text


def test_temporary_yaml_bridge_actions_are_not_exposed_after_orchestrator_migration() -> None:
    services_text = (INTEGRATION / "services.yaml").read_text(encoding="utf-8")
    for retired in (
        "pending_selection_get", "pending_selection_set", "pending_selection_clear",
        "play_item", "queue_add_item", "prepare_play_session",
    ):
        assert re.search(rf"(?m)^{retired}:\s*$", services_text) is None
    for native in ("media_orchestrator", "play_pending_media", "resume_pending_media_request"):
        assert re.search(rf"(?m)^{native}:\s*$", services_text)
