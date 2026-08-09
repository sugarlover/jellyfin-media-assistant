# Changelog

All notable changes to Jellyfin Media Assistant will be documented here.

The project uses semantic versioning for public releases.

## [0.1.0-beta.1] - 2026-08-09

First public beta candidate.

### Added

- Manual `jellyfin_assist.refresh_catalog` action for refreshing the Jellyfin search catalog without restarting Home Assistant.
- Native Jellyfin catalog search with tolerant title matching.
- Native Jellyfin item lookup and Chromecast playback.
- Home Assistant Assist intents for movies, TV, music, ambiguous-result selection, and queue control.
- Per-player persistent queues with Next, Clear, Shuffle, Repeat Item, Repeat Queue, queue status, and automatic advancement.
- Config-entry UI for Jellyfin connection details and playback targets.
- Automatic provisioning and repair of managed English Assist sentence definitions.
- Diagnostics for connection, catalog, player configuration, queue advancement, pending selection, and voice onboarding.
- User quick-start, voice-command, configuration, architecture, developer, and known-limitations documentation.

### Changed

- Jellyfin Media Assistant no longer depends on JellyHA at runtime.
- Queue persistence now lives in Home Assistant storage; no external queue server, Python process, Docker container, or port 8787 is required.
- Home Assistant YAML scripts, helpers, REST commands, `intent_script`, and queue-advancement automations are no longer required.
- Historical migration-step documents and the full vendored JellyHA source snapshot were removed from the public repository; durable provenance and the upstream MIT license are retained.

### Support status

- Chromecast playback is the tested and supported playback platform for this beta.
- Other Home Assistant media-player platforms are experimental and community-tested.
- English Assist sentences are included in this beta.
