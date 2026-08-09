# Sanitized Compatibility Fixtures

This directory contains a small sanitized Home Assistant compatibility fixture retained for regression tests.

It is **not** a deployment package, a live Home Assistant backup, or the supported installation surface. New users should follow the root README and `docs/quick-start.md`.

The fixture contains only public/example values and intentionally excludes credentials, live queue data, databases, logs, Home Assistant `.storage` data, unrelated household automation, and private filesystem/network details.

The current Jellyfin Media Assistant runtime is implemented under `custom_components/jellyfin_assist/`. Historical JellyHA source used during migration is not distributed here; third-party attribution is retained in `THIRD_PARTY_NOTICES.md` and `docs/provenance/`.
