# Sanitized compatibility-fixture tests

These tests inspect the small sanitized fixtures under `reference/current-working/` that still protect compatibility boundaries from the earlier Home Assistant YAML implementation.

They are not installation examples and they are not a second implementation of Jellyfin Media Assistant. New behavior should be tested against the native integration under `tests/homeassistant/`, `tests/search/`, or `tests/matching/` whenever possible.

The historical JellyHA source-contract fixtures were removed when the public documentation/repository surface was cleaned up because JellyHA is no longer a runtime dependency. JellyHA provenance is retained under `docs/provenance/`.
