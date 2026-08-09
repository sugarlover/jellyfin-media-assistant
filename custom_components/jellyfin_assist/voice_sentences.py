"""Managed Assist sentence provisioning for Jellyfin Media Assistant."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .voice import CUSTOM_SENTENCE_FILENAME, CUSTOM_SENTENCE_LANGUAGE

_LOGGER = logging.getLogger(__name__)

VOICE_SENTENCE_STORE_KEY: Final = f"{DOMAIN}.voice_sentences"
VOICE_SENTENCE_STORE_VERSION: Final = 1
VOICE_SENTENCE_USER_MODIFIED_ISSUE: Final = "voice_sentences_user_modified"
VOICE_SENTENCE_INSTALL_FAILED_ISSUE: Final = "voice_sentences_install_failed"

PACKAGED_SENTENCE_PATH: Final = (
    Path(__file__).parent
    / "custom_sentences"
    / CUSTOM_SENTENCE_LANGUAGE
    / CUSTOM_SENTENCE_FILENAME
)


@dataclass(frozen=True, slots=True)
class VoiceSentenceState:
    """Current or most recent managed-sentence provisioning state."""

    status: str
    managed: bool
    packaged: bool
    installed: bool
    current: bool
    user_modified: bool
    reload_attempted: bool = False
    reload_succeeded: bool = False
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable action/diagnostic payload."""

        return asdict(self)


def _installed_sentence_path(hass: HomeAssistant) -> Path:
    return Path(
        hass.config.path(
            "custom_sentences",
            CUSTOM_SENTENCE_LANGUAGE,
            CUSTOM_SENTENCE_FILENAME,
        )
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_sentence_files(
    packaged_path: Path,
    installed_path: Path,
) -> tuple[bytes | None, bytes | None]:
    packaged = packaged_path.read_bytes() if packaged_path.is_file() else None
    installed = installed_path.read_bytes() if installed_path.is_file() else None
    return packaged, installed


def _write_sentence_file(installed_path: Path, data: bytes) -> None:
    installed_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{installed_path.name}.",
            suffix=".tmp",
            dir=installed_path.parent,
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, installed_path)
    finally:
        if temporary_name is not None:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()


def _remove_sentence_file(installed_path: Path) -> None:
    if installed_path.is_file():
        installed_path.unlink()


def _metadata_store(hass: HomeAssistant) -> Store[dict[str, Any]]:
    return Store[dict[str, Any]](
        hass,
        VOICE_SENTENCE_STORE_VERSION,
        VOICE_SENTENCE_STORE_KEY,
        private=True,
        atomic_writes=True,
    )


def _managed_sha256(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("managed_sha256")
    return value if isinstance(value, str) else None


def _state_from_hashes(
    *,
    packaged_data: bytes | None,
    installed_data: bytes | None,
    managed_sha256: str | None,
) -> VoiceSentenceState:
    if packaged_data is None:
        return VoiceSentenceState(
            status="packaged_missing",
            managed=managed_sha256 is not None,
            packaged=False,
            installed=installed_data is not None,
            current=False,
            user_modified=False,
        )

    if installed_data is None:
        return VoiceSentenceState(
            status="missing",
            managed=managed_sha256 is not None,
            packaged=True,
            installed=False,
            current=False,
            user_modified=False,
        )

    packaged_sha256 = _sha256_bytes(packaged_data)
    installed_sha256 = _sha256_bytes(installed_data)
    if packaged_sha256 == installed_sha256:
        return VoiceSentenceState(
            status="current",
            managed=managed_sha256 == installed_sha256,
            packaged=True,
            installed=True,
            current=True,
            user_modified=False,
        )

    if managed_sha256 == installed_sha256:
        return VoiceSentenceState(
            status="outdated",
            managed=True,
            packaged=True,
            installed=True,
            current=False,
            user_modified=False,
        )

    if managed_sha256 is not None:
        return VoiceSentenceState(
            status="user_modified",
            managed=True,
            packaged=True,
            installed=True,
            current=False,
            user_modified=True,
        )

    return VoiceSentenceState(
        status="unmanaged_existing",
        managed=False,
        packaged=True,
        installed=True,
        current=False,
        user_modified=True,
    )


async def _async_load_metadata(hass: HomeAssistant) -> tuple[Store[dict[str, Any]], dict[str, Any]]:
    store = _metadata_store(hass)
    metadata = await store.async_load() or {}
    return store, metadata


async def async_inspect_voice_sentences(hass: HomeAssistant) -> VoiceSentenceState:
    """Inspect packaged and installed sentence state without modifying files."""

    try:
        _store, metadata = await _async_load_metadata(hass)
    except Exception as err:  # pragma: no cover - storage failures are environment-specific.
        _LOGGER.warning("Could not load Jellyfin Assist voice sentence metadata: %s", err)
        metadata = {}

    try:
        packaged_data, installed_data = await hass.async_add_executor_job(
            _read_sentence_files,
            PACKAGED_SENTENCE_PATH,
            _installed_sentence_path(hass),
        )
    except OSError as err:
        return VoiceSentenceState(
            status="inspection_failed",
            managed=False,
            packaged=False,
            installed=False,
            current=False,
            user_modified=False,
            error=str(err),
        )

    return _state_from_hashes(
        packaged_data=packaged_data,
        installed_data=installed_data,
        managed_sha256=_managed_sha256(metadata),
    )


def _clear_voice_sentence_issues(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, VOICE_SENTENCE_USER_MODIFIED_ISSUE)
    ir.async_delete_issue(hass, DOMAIN, VOICE_SENTENCE_INSTALL_FAILED_ISSUE)


def _create_user_modified_issue(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, VOICE_SENTENCE_INSTALL_FAILED_ISSUE)
    ir.async_create_issue(
        hass,
        DOMAIN,
        VOICE_SENTENCE_USER_MODIFIED_ISSUE,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="voice_sentences_user_modified",
    )


def _create_install_failed_issue(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, VOICE_SENTENCE_USER_MODIFIED_ISSUE)
    ir.async_create_issue(
        hass,
        DOMAIN,
        VOICE_SENTENCE_INSTALL_FAILED_ISSUE,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="voice_sentences_install_failed",
    )


async def _async_reload_conversation(hass: HomeAssistant) -> tuple[bool, bool]:
    if not hass.services.has_service("conversation", "reload"):
        return False, False

    try:
        await hass.services.async_call(
            "conversation",
            "reload",
            {},
            blocking=True,
        )
    except Exception as err:  # pragma: no cover - HA service errors are environment-specific.
        _LOGGER.warning("Could not reload Home Assistant conversation agents: %s", err)
        return True, False
    return True, True


async def async_provision_voice_sentences(
    hass: HomeAssistant,
    *,
    overwrite_user_modified: bool = False,
) -> VoiceSentenceState:
    """Install or update the managed Assist sentence file when it is safe."""

    try:
        store, metadata = await _async_load_metadata(hass)
    except Exception as err:  # pragma: no cover - storage failures are environment-specific.
        _LOGGER.error("Could not load Jellyfin Assist voice sentence metadata: %s", err)
        _create_install_failed_issue(hass)
        return VoiceSentenceState(
            status="install_failed",
            managed=False,
            packaged=True,
            installed=False,
            current=False,
            user_modified=False,
            error=str(err),
        )

    installed_path = _installed_sentence_path(hass)
    try:
        packaged_data, installed_data = await hass.async_add_executor_job(
            _read_sentence_files,
            PACKAGED_SENTENCE_PATH,
            installed_path,
        )
    except OSError as err:
        _LOGGER.error("Could not inspect Jellyfin Assist voice sentences: %s", err)
        _create_install_failed_issue(hass)
        return VoiceSentenceState(
            status="install_failed",
            managed=False,
            packaged=False,
            installed=False,
            current=False,
            user_modified=False,
            error=str(err),
        )

    observed = _state_from_hashes(
        packaged_data=packaged_data,
        installed_data=installed_data,
        managed_sha256=_managed_sha256(metadata),
    )
    if packaged_data is None:
        _LOGGER.error("Packaged Jellyfin Assist voice sentence file is missing")
        _create_install_failed_issue(hass)
        return VoiceSentenceState(
            status="packaged_missing",
            managed=observed.managed,
            packaged=False,
            installed=observed.installed,
            current=False,
            user_modified=False,
            error="Packaged voice sentence file is missing.",
        )

    packaged_sha256 = _sha256_bytes(packaged_data)

    if observed.current:
        try:
            if _managed_sha256(metadata) != packaged_sha256:
                await store.async_save(
                    {
                        "language": CUSTOM_SENTENCE_LANGUAGE,
                        "filename": CUSTOM_SENTENCE_FILENAME,
                        "managed_sha256": packaged_sha256,
                    }
                )
        except Exception as err:  # pragma: no cover - storage failures are environment-specific.
            _LOGGER.error("Could not adopt Jellyfin Assist voice sentence metadata: %s", err)
            _create_install_failed_issue(hass)
            return VoiceSentenceState(
                status="install_failed",
                managed=False,
                packaged=True,
                installed=True,
                current=True,
                user_modified=False,
                error=str(err),
            )
        _clear_voice_sentence_issues(hass)
        return VoiceSentenceState(
            status="current",
            managed=True,
            packaged=True,
            installed=True,
            current=True,
            user_modified=False,
        )

    if observed.user_modified and not overwrite_user_modified:
        _LOGGER.warning(
            "The Jellyfin Assist voice sentence file has local content; leaving it unchanged"
        )
        _create_user_modified_issue(hass)
        return observed

    previous_status = observed.status
    try:
        await hass.async_add_executor_job(
            _write_sentence_file,
            installed_path,
            packaged_data,
        )
        await store.async_save(
            {
                "language": CUSTOM_SENTENCE_LANGUAGE,
                "filename": CUSTOM_SENTENCE_FILENAME,
                "managed_sha256": packaged_sha256,
            }
        )
    except Exception as err:  # pragma: no cover - storage/filesystem failures are environment-specific.
        _LOGGER.error("Could not install Jellyfin Assist voice sentences: %s", err)
        _create_install_failed_issue(hass)
        return VoiceSentenceState(
            status="install_failed",
            managed=observed.managed,
            packaged=True,
            installed=observed.installed,
            current=False,
            user_modified=observed.user_modified,
            error=str(err),
        )

    reload_attempted, reload_succeeded = await _async_reload_conversation(hass)
    _clear_voice_sentence_issues(hass)
    if previous_status == "missing":
        status = "installed"
    elif observed.user_modified:
        status = "repaired"
    else:
        status = "updated"

    return VoiceSentenceState(
        status=status,
        managed=True,
        packaged=True,
        installed=True,
        current=True,
        user_modified=False,
        reload_attempted=reload_attempted,
        reload_succeeded=reload_succeeded,
    )


async def async_remove_managed_voice_sentences(hass: HomeAssistant) -> bool:
    """Remove an unchanged managed sentence file during final-entry removal."""

    try:
        store, metadata = await _async_load_metadata(hass)
    except Exception as err:  # pragma: no cover - storage failures are environment-specific.
        _LOGGER.warning("Could not load voice sentence metadata during cleanup: %s", err)
        return False

    managed_sha256 = _managed_sha256(metadata)
    installed_path = _installed_sentence_path(hass)
    try:
        _packaged_data, installed_data = await hass.async_add_executor_job(
            _read_sentence_files,
            PACKAGED_SENTENCE_PATH,
            installed_path,
        )
        if (
            installed_data is not None
            and managed_sha256 is not None
            and _sha256_bytes(installed_data) == managed_sha256
        ):
            await hass.async_add_executor_job(_remove_sentence_file, installed_path)
            await _async_reload_conversation(hass)
        await store.async_remove()
    except Exception as err:  # pragma: no cover - storage/filesystem failures are environment-specific.
        _LOGGER.warning("Could not clean up Jellyfin Assist voice sentences: %s", err)
        return False

    _clear_voice_sentence_issues(hass)
    return True


__all__ = [
    "PACKAGED_SENTENCE_PATH",
    "VOICE_SENTENCE_INSTALL_FAILED_ISSUE",
    "VOICE_SENTENCE_STORE_KEY",
    "VOICE_SENTENCE_USER_MODIFIED_ISSUE",
    "VoiceSentenceState",
    "async_inspect_voice_sentences",
    "async_provision_voice_sentences",
    "async_remove_managed_voice_sentences",
]
