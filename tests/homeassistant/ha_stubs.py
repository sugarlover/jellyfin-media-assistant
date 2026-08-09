"""Small runtime stubs for testing integration adapters without installing HA."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import sys
from types import ModuleType
from typing import Any


class _Marker:
    def __init__(self, key: Any, default: Any = None) -> None:
        self.key = key
        self.default = default

    def __hash__(self) -> int:
        return hash((self.key, self.default))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Marker) and (self.key, self.default) == (
            other.key,
            other.default,
        )


class _Schema:
    def __init__(self, schema: Any) -> None:
        self.schema = schema

    def __call__(self, value: Any) -> Any:
        return value


class _Selector:
    def __init__(self, config: Any = None) -> None:
        self.config = config


class TextSelectorType(Enum):
    URL = "url"
    PASSWORD = "password"
    TEXT = "text"


class TextSelectorConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.options = kwargs


class EntitySelectorConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.options = kwargs


class Store:
    def __init__(self, hass: Any, version: int, key: str, **kwargs: Any) -> None:
        self.hass = hass
        self.version = version
        self.key = key
        self.kwargs = kwargs

    async def async_load(self) -> dict[str, Any] | None:
        value = self.hass.storage.get(self.key)
        return dict(value) if isinstance(value, dict) else None

    async def async_save(self, data: dict[str, Any]) -> None:
        self.hass.storage[self.key] = dict(data)

    async def async_remove(self) -> None:
        self.hass.storage.pop(self.key, None)

    @classmethod
    def __class_getitem__(cls, item: Any) -> type["Store"]:
        return cls


class ConfigEntryState(Enum):
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"


class SupportsResponse(Enum):
    ONLY = "only"
    OPTIONAL = "optional"


class IssueSeverity(Enum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ServiceCall:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class ServiceValidationError(Exception):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message)
        self.translation_domain = kwargs.get("translation_domain")
        self.translation_key = kwargs.get("translation_key")


class IntentHandleError(Exception):
    pass


class IntentResponse:
    def __init__(self, language: str = "en", intent: Any = None) -> None:
        self.language = language
        self.intent = intent
        self.speech: dict[str, dict[str, Any]] = {}

    def async_set_speech(self, speech: str, speech_type: str = "plain", extra_data: Any = None) -> None:
        self.speech[speech_type] = {"speech": speech, "extra_data": extra_data}


class Intent:
    def __init__(
        self,
        hass: Any,
        slots: dict[str, Any] | None = None,
        *,
        context: Any = None,
        language: str = "en",
    ) -> None:
        self.hass = hass
        self.slots = slots or {}
        self.context = context
        self.language = language

    def create_response(self) -> IntentResponse:
        return IntentResponse(language=self.language, intent=self)


class IntentHandler:
    intent_type: str
    description: str | None = None


class ConfigEntryAuthFailed(Exception):
    pass


class ConfigEntryNotReady(Exception):
    pass


class OptionsFlow:
    def __init__(self) -> None:
        self.config_entry: Any = None

    def async_create_entry(self, *, data: dict[str, Any]) -> dict[str, Any]:
        return {"type": "create_entry", "data": data}

    def async_show_form(
        self,
        *,
        step_id: str,
        data_schema: Any,
        errors: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors,
        }

    def add_suggested_values_to_schema(
        self, schema: Any, suggested_values: dict[str, Any]
    ) -> Any:
        self.suggested_values = dict(suggested_values)
        return schema


class OptionsFlowWithReload(OptionsFlow):
    pass


class ConfigFlow:
    VERSION = 1
    MINOR_VERSION = 1

    def __init_subclass__(cls, **kwargs: Any) -> None:
        cls.domain = kwargs.pop("domain", None)
        super().__init_subclass__()

    def __init__(self) -> None:
        self.hass: Any = None
        self.unique_id: str | None = None

    async def async_set_unique_id(self, unique_id: str) -> None:
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self) -> None:
        return None

    def async_create_entry(self, *, title: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(
        self,
        *,
        step_id: str,
        data_schema: Any,
        errors: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors,
        }


def install_homeassistant_stubs() -> None:
    """Install only the HA modules imported by this integration."""

    vol = ModuleType("voluptuous")
    vol.Schema = _Schema
    vol.Required = lambda key, default=None: _Marker(key, default)
    vol.Optional = lambda key, default=None: _Marker(key, default)
    vol.In = lambda values: ("in", tuple(values))
    vol.All = lambda *validators: ("all", validators)
    vol.Coerce = lambda target: ("coerce", target)
    vol.Range = lambda **kwargs: ("range", kwargs)
    sys.modules.setdefault("voluptuous", vol)

    root = ModuleType("homeassistant")
    config_entries = ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntryState = ConfigEntryState
    config_entries.ConfigEntry = object
    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigFlowResult = dict
    config_entries.OptionsFlow = OptionsFlow
    config_entries.OptionsFlowWithReload = OptionsFlowWithReload

    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda func: func
    core.ServiceCall = ServiceCall
    core.ServiceResponse = dict
    core.SupportsResponse = SupportsResponse

    exceptions = ModuleType("homeassistant.exceptions")
    exceptions.ServiceValidationError = ServiceValidationError
    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady

    helpers = ModuleType("homeassistant.helpers")
    intent = ModuleType("homeassistant.helpers.intent")
    intent.Intent = Intent
    intent.IntentHandler = IntentHandler
    intent.IntentResponse = IntentResponse
    intent.IntentHandleError = IntentHandleError

    def async_register_intent(hass: Any, handler: Any) -> None:
        hass.data.setdefault("intent", {})[handler.intent_type] = handler

    def async_get_intents(hass: Any) -> list[Any]:
        return list(hass.data.get("intent", {}).values())

    intent.async_register = async_register_intent
    intent.async_get = async_get_intents

    config_validation = ModuleType("homeassistant.helpers.config_validation")
    config_validation.string = str
    config_validation.boolean = bool
    aiohttp_client = ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: hass.session
    storage = ModuleType("homeassistant.helpers.storage")
    storage.Store = Store
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")
    issue_registry.IssueSeverity = IssueSeverity

    def async_create_issue(hass: Any, domain: str, issue_id: str, **kwargs: Any) -> None:
        hass.issues[(domain, issue_id)] = dict(kwargs)

    def async_delete_issue(hass: Any, domain: str, issue_id: str) -> None:
        hass.issues.pop((domain, issue_id), None)

    issue_registry.async_create_issue = async_create_issue
    issue_registry.async_delete_issue = async_delete_issue
    selector = ModuleType("homeassistant.helpers.selector")
    event = ModuleType("homeassistant.helpers.event")

    def async_track_state_change_event(hass: Any, entity_ids: list[str], action: Any) -> Any:
        hass.tracked_state_changes.append((tuple(entity_ids), action))

        def unsubscribe() -> None:
            hass.unsubscribed_state_changes.append(tuple(entity_ids))

        return unsubscribe

    event.async_track_state_change_event = async_track_state_change_event
    selector.BooleanSelector = _Selector
    selector.EntitySelector = _Selector
    selector.EntitySelectorConfig = EntitySelectorConfig
    selector.TextSelector = _Selector
    selector.TextSelectorConfig = TextSelectorConfig
    selector.TextSelectorType = TextSelectorType
    entity_registry = ModuleType("homeassistant.helpers.entity_registry")
    entity_registry.async_get = lambda hass: hass.entity_registry
    entity_registry.async_get_entity_aliases = (
        lambda hass, entry, allow_empty=True: list(entry.aliases)
        if entry.aliases
        else ([] if allow_empty else [
            entry.entity_id.removeprefix("media_player.").replace("_", " ").title()
        ])
    )

    components = ModuleType("homeassistant.components")
    diagnostics = ModuleType("homeassistant.components.diagnostics")

    def async_redact_data(data: dict[str, Any], keys: set[str]) -> dict[str, Any]:
        return {key: ("**REDACTED**" if key in keys else value) for key, value in data.items()}

    diagnostics.async_redact_data = async_redact_data

    root.config_entries = config_entries
    root.helpers = helpers
    root.components = components
    helpers.intent = intent
    helpers.config_validation = config_validation
    helpers.aiohttp_client = aiohttp_client
    helpers.storage = storage
    helpers.issue_registry = issue_registry
    helpers.selector = selector
    helpers.event = event
    helpers.entity_registry = entity_registry
    components.diagnostics = diagnostics

    modules = {
        "homeassistant": root,
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": core,
        "homeassistant.exceptions": exceptions,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.intent": intent,
        "homeassistant.helpers.config_validation": config_validation,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
        "homeassistant.helpers.storage": storage,
        "homeassistant.helpers.issue_registry": issue_registry,
        "homeassistant.helpers.selector": selector,
        "homeassistant.helpers.event": event,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.components": components,
        "homeassistant.components.diagnostics": diagnostics,
    }
    for name, module in modules.items():
        sys.modules.setdefault(name, module)




class FakeState:
    def __init__(
        self,
        entity_id: str,
        *,
        friendly_name: str | None = None,
        state: str = "idle",
    ) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = {
            "friendly_name": friendly_name
            or entity_id.removeprefix("media_player.").replace("_", " ").title()
        }


class FakeStates:
    def __init__(self, states: list[FakeState] | None = None) -> None:
        self._states = {state.entity_id: state for state in (states or [])}

    def get(self, entity_id: str) -> FakeState | None:
        return self._states.get(entity_id)

    def async_all(self, domain: str | None = None) -> list[FakeState]:
        if domain is None:
            return list(self._states.values())
        prefix = f"{domain}."
        return [state for state in self._states.values() if state.entity_id.startswith(prefix)]


class FakeRegistryEntry:
    def __init__(self, entity_id: str, aliases: list[str] | None = None) -> None:
        self.entity_id = entity_id
        self.aliases = list(aliases or [])


class FakeEntityRegistry:
    def __init__(self, entries: list[FakeRegistryEntry] | None = None) -> None:
        self._entries = {entry.entity_id: entry for entry in (entries or [])}

    def async_get(self, entity_id: str) -> FakeRegistryEntry | None:
        return self._entries.get(entity_id)


class FakeServices:
    def __init__(self) -> None:
        self.registered: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self.registered

    def async_register(
        self,
        domain: str,
        service: str,
        handler: Any,
        **kwargs: Any,
    ) -> None:
        self.registered[(domain, service)] = {"handler": handler, **kwargs}

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        blocking: bool = False,
        return_response: bool = False,
        context: Any = None,
    ) -> Any:
        self.calls.append(
            {
                "domain": domain,
                "service": service,
                "data": dict(data),
                "blocking": blocking,
                "return_response": return_response,
                "context": context,
            }
        )
        registered = self.registered[(domain, service)]
        return await registered["handler"](ServiceCall(dict(data)))


class FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


class FakeConfigEntries:
    def __init__(self, entries: list[Any] | None = None) -> None:
        self.entries = entries or []

    def async_loaded_entries(self, domain: str) -> list[Any]:
        return [entry for entry in self.entries if entry.domain == domain and entry.state is ConfigEntryState.LOADED]

    def async_entries(self, domain: str) -> list[Any]:
        return [entry for entry in self.entries if entry.domain == domain]

    def async_get_entry(self, entry_id: str) -> Any:
        return next((entry for entry in self.entries if entry.entry_id == entry_id), None)

    def async_update_entry(
        self,
        entry: Any,
        *,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        version: int | None = None,
        minor_version: int | None = None,
    ) -> None:
        if data is not None:
            entry.data = dict(data)
        if options is not None:
            entry.options = dict(options)
        if version is not None:
            entry.version = version
        if minor_version is not None:
            entry.minor_version = minor_version
        entry.update_count += 1


class FakeHass:
    def __init__(
        self,
        root: Path,
        *,
        session: Any = None,
        entries: list[Any] | None = None,
        states: list[FakeState] | None = None,
        registry_entries: list[FakeRegistryEntry] | None = None,
    ) -> None:
        self.config = FakeConfig(root)
        self.data: dict[Any, Any] = {}
        self.storage: dict[str, Any] = {}
        self.issues: dict[tuple[str, str], dict[str, Any]] = {}
        self.services = FakeServices()
        self.config_entries = FakeConfigEntries(entries)
        self.session = session
        default_states = states if states is not None else [
            FakeState("media_player.example_chromecast", friendly_name="Example Chromecast"),
            FakeState("media_player.example_secondary_chromecast", friendly_name="Example Secondary Chromecast"),
        ]
        self.states = FakeStates(default_states)
        default_registry = registry_entries if registry_entries is not None else [
            FakeRegistryEntry("media_player.example_chromecast", ["Example Chromecast"]),
            FakeRegistryEntry("media_player.example_secondary_chromecast", ["Example Secondary Chromecast"]),
        ]
        self.entity_registry = FakeEntityRegistry(default_registry)
        self.tracked_state_changes: list[tuple[tuple[str, ...], Any]] = []
        self.unsubscribed_state_changes: list[tuple[str, ...]] = []

    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        return target(*args)


class FakeEntry:
    def __init__(
        self,
        entry_id: str,
        data: dict[str, Any],
        *,
        options: dict[str, Any] | None = None,
        version: int = 1,
        minor_version: int = 1,
    ) -> None:
        self.entry_id = entry_id
        self.data = data
        self.options = options or {}
        self.domain = "jellyfin_assist"
        self.state = ConfigEntryState.LOADED
        self.runtime_data: Any = None
        self.background_tasks: list[tuple[str, Any]] = []
        self.state_cache_clear_count = 0
        self.version = version
        self.minor_version = minor_version
        self.update_count = 0
        self.unload_callbacks: list[Any] = []

    def clear_state_cache(self) -> None:
        self.state_cache_clear_count += 1

    def async_create_background_task(
        self,
        hass: Any,
        coro: Any,
        name: str,
    ) -> None:
        self.background_tasks.append((name, coro))
        coro.close()

    def async_on_unload(self, callback: Any) -> None:
        self.unload_callbacks.append(callback)
