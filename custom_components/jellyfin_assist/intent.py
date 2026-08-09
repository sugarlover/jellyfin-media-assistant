"""Native Home Assistant intent handlers for Jellyfin Media Assistant."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .voice import (
    INTENT_DESCRIPTIONS,
    NATIVE_INTENT_TYPES,
    VoiceIntentValidationError,
    build_voice_script_call,
)


def _slot_values(intent_obj: intent.Intent) -> dict[str, Any]:
    """Flatten Home Assistant slot metadata to the values used by old YAML."""

    values: dict[str, Any] = {}
    for name, slot in intent_obj.slots.items():
        if isinstance(slot, Mapping):
            values[name] = slot.get("value")
        else:
            values[name] = slot
    return values


def _speech_from_result(result: Mapping[str, Any]) -> str:
    """Preserve the established Jellyfin Assist response contract."""

    for key in ("speak", "message", "display"):
        value = result.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return "Jellyfin Media Assistant completed the request."


class JellyfinAssistIntentHandler(intent.IntentHandler):
    """Dispatch one native Assist intent to a canonical Jellyfin Assist action."""

    def __init__(self, intent_type: str) -> None:
        self.intent_type = intent_type
        self.description = INTENT_DESCRIPTIONS[intent_type]

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle one voice request without duplicating media runtime behavior."""

        try:
            script_call = build_voice_script_call(
                self.intent_type,
                _slot_values(intent_obj),
            )
        except VoiceIntentValidationError as err:
            response = intent_obj.create_response()
            response.async_set_speech(str(err))
            return response

        try:
            result = await intent_obj.hass.services.async_call(
                script_call.domain,
                script_call.service,
                script_call.data,
                blocking=True,
                return_response=True,
                context=intent_obj.context,
            )
        except Exception as err:
            raise intent.IntentHandleError(
                f"Jellyfin Media Assistant could not run {script_call.service}: {err}"
            ) from err

        if not isinstance(result, Mapping):
            raise intent.IntentHandleError(
                f"Jellyfin Media Assistant action {script_call.domain}.{script_call.service} returned no response"
            )

        response = intent_obj.create_response()
        response.async_set_speech(_speech_from_result(result))
        return response


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register canonical Jellyfin Media Assistant voice intents."""

    for intent_type in NATIVE_INTENT_TYPES:
        intent.async_register(hass, JellyfinAssistIntentHandler(intent_type))


__all__ = ["JellyfinAssistIntentHandler", "async_setup_intents"]
