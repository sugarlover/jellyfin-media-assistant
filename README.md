# Jellyfin Media Assistant

<p align="center">
  <img src="https://raw.githubusercontent.com/sugarlover/jellyfin-media-assistant/main/custom_components/jellyfin_assist/brand/icon.png"
       alt="Jellyfin Media Assistant icon"
       width="180">
</p>

Jellyfin Media Assistant is a Home Assistant custom integration that lets Home Assistant Assist search a Jellyfin library, play media on Chromecast targets, and manage persistent per-player queues with natural-language commands.

> **Public beta:** `0.1.0-beta.1` is available for public testing. Chromecast is the tested and supported playback platform. Other Home Assistant media players are experimental and may not work correctly yet.

Jellyfin Media Assistant is an independent community project and is not affiliated with or endorsed by the Jellyfin project or Nabu Casa/Home Assistant.

## Why I built this

I don't currently have AI with my Home Assistant and I wanted to be able to control all my media by Assist. I installed the JellyHA integration and made some custom sentences and intents. I use my phone's speech-to-text inside Assist and that caused issues with Jellyfin's search - It's too literal. If I spoke a number it would be spelled out, then the Jellyfin search would return nothing. If I missed a hyphen or a single letter was off, the search would be empty.

I started by creating a robust search that could handle common speech-to-text and swipe issues. During that process the project just kept getting bigger so I decided to make it a standalone integration. My goal was to make the integration handle natural(ish) speech with just the use of Assist, no AI. See the documentation for more details and command examples.

I am grateful to zupancicmarko for their work on [JellyHA](https://github.com/zupancicmarko/JellyHA) and for the inspiration! Back to AI typing.

## AI-assisted development

This project has been developed with extensive AI-assisted coding. The maintainer defines the requirements and architecture, makes product and compatibility decisions, and validates behavior through automated tests and live Home Assistant/Jellyfin use. AI tools have been used heavily to generate, revise, review, and document implementation code.

Because of that workflow, regression tests, diagnostics, reproducible bug reports, and real-world validation are treated as important parts of the project rather than optional extras. Contributions and code review are welcome.

## Features

- Searches movies, series, episodes, songs, albums, and artists in Jellyfin.
- Handles common punctuation, spacing, numeric, and speech/transcription variations when matching titles.
- Uses title plus optional artist, series, media-type, season, episode, and year context.
- Plays resolved Jellyfin media through Home Assistant on Chromecast targets.
- Expands albums, artists, and TV seasons into playable queue items.
- Presents numbered choices when a request has multiple plausible matches.
- Maintains a persistent queue per configured playback target.
- Supports Next, What's Playing, What Just Played, Queue Status, Clear Queue, Shuffle, Repeat Item, Repeat Queue, and Repeat Off.
- Automatically advances after a queued item finishes.
- Automatically installs and updates its managed English Assist sentence file.
- Provides diagnostics with secrets redacted.

## Future ideas

Jellyfin Media Assistant is still in beta. Some ideas being considered for future releases include:

- Continue where I left off and recent-media history
- Additional natural-language Assist sentence variations
- “What’s playing next?” queue queries
- Removing individual items from a queue
- Expanded support and testing for media players beyond Chromecast
- Continued improvements to speech-to-text tolerant search and matching

These are roadmap ideas, not commitments to a particular release or schedule.

## Requirements

- Home Assistant **2026.7.0 or newer**.
- A Jellyfin server reachable from Home Assistant.
- A Jellyfin API key and the Jellyfin user ID whose accessible libraries should be searched.
- For supported playback, a Chromecast exposed to Home Assistant as a `media_player` entity.
- HACS is recommended for installation but is not required for a manual install.

The first beta has been tested with Home Assistant 2026.7.x, Jellyfin 10.11.x, and Chromecast playback.

### Jellyfin integration not required

You do **not** need to install Home Assistant's Jellyfin integration to use Jellyfin Media Assistant.

Jellyfin Media Assistant connects directly to your Jellyfin server using the **server URL, API key, and Jellyfin user ID** provided during setup. Playback is then sent to the Home Assistant media players you configure for the integration.

In other words, you need:

* Home Assistant
* A Jellyfin server
* A Jellyfin API key and user ID
* At least one compatible Home Assistant media player

The separate Home Assistant Jellyfin integration is optional and is not a dependency of Jellyfin Media Assistant.


## Quick start

1. Install Jellyfin Media Assistant through HACS as a custom integration repository, or copy `custom_components/jellyfin_assist` into Home Assistant manually.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Jellyfin Media Assistant**.
4. Enter the Jellyfin server URL, API key, Jellyfin user ID, and SSL-verification preference.
5. Open the integration's **Configure** dialog and choose a default media player and/or allowed playback targets.
6. Use Home Assistant Assist. The managed English sentence file is provisioned automatically.

A typical request looks like:

> Play the movie The Martian on the living room TV.

See the [Quick Start](docs/quick-start.md) for the full setup path and [Voice & Assist Command Guide](docs/voice-commands.md) for tested command forms.

## Installation with HACS

Until Jellyfin Media Assistant is included in HACS' default repository list, install it as a custom repository:

1. Open HACS in Home Assistant.
2. Open **Custom repositories**.
3. Add `https://github.com/sugarlover/jellyfin-media-assistant` as an **Integration** repository.
4. Find **Jellyfin Media Assistant** in HACS and install it.
5. Restart Home Assistant.
6. Add **Jellyfin Media Assistant** from **Settings → Devices & services**.

## Manual installation

1. Copy `custom_components/jellyfin_assist` from this repository into the Home Assistant configuration directory as `custom_components/jellyfin_assist`.
2. Restart Home Assistant.
3. Add **Jellyfin Media Assistant** from **Settings → Devices & services**.

No separate Python installation, Docker queue container, external queue service, YAML script package, helper entities, REST commands, or queue-advancement automation are required.

## Documentation

### For users

- [Quick Start](docs/quick-start.md) — install, configure, and send a first request.
- [Voice & Assist Command Guide](docs/voice-commands.md) — canonical play, add, selection, queue, and repeat phrases.
- [Configuration](docs/configuration.md) — connection settings, playback targets, aliases, persistence, and diagnostics.
- [Known Limitations](docs/known-limitations.md) — current beta boundaries and deferred behavior.

### For contributors

- [Architecture](docs/architecture.md) — request flow, search/matching pipeline, queue model, playback path, state ownership, and module map.
- [Developer Guide](docs/developer-guide.md) — local test setup, repository layout, validation gates, and where to make common changes.
- [Contributing](CONTRIBUTING.md) — contribution expectations and pull-request checklist.

## Supported and experimental playback

**Supported for the first beta:** Chromecast media players.

Other Home Assistant `media_player` platforms are experimental. They may appear as selectable targets, but the current playback strategy has been developed and tested around Chromecast behavior. Community feedback and issue reports for other platforms are welcome.

Home Assistant remains responsible for native player controls such as pause, resume, stop, mute, volume, and power. Jellyfin Media Assistant intentionally avoids claiming those broad commands.

## Queue behavior

Queues are persisted by the integration through Home Assistant storage and maintained separately per playback target. Queue state survives Home Assistant restarts.

Starting a new **Play** request creates a fresh playback session and resets repeat modes. **Add/Queue** requests append media to the existing queue. Automatic advancement verifies that the completed Home Assistant media item corresponds to the current Jellyfin queue item before advancing.

### Catalog behavior

> **Catalog refresh time:** Refreshing the catalog may take several seconds to a minute or more depending on the size of your Jellyfin library and the performance of your server and Home Assistant system. During testing, a catalog containing about 3,800 items took approximately 37 seconds to refresh. The action may appear idle while the catalog is being downloaded and indexed; allow it to finish before running it again.

Jellyfin Media Assistant maintains a local metadata catalog of the media available to the configured Jellyfin user. Searches are performed against this local index so that title normalization, speech-to-text correction, fuzzy matching, and other search improvements can be applied quickly.

When the integration is started for the first time, the catalog is downloaded from Jellyfin. On later Home Assistant starts or integration reloads, the saved catalog is loaded immediately and refreshed from Jellyfin in the background.

The last working catalog remains available if Jellyfin is temporarily unavailable or a refresh fails.

If media has been added to or removed from Jellyfin since the last catalog refresh, use the `jellyfin_assist.refresh_catalog` action to update the search catalog without restarting Home Assistant.

## Diagnostics and troubleshooting

Download diagnostics from **Settings → Devices & services → Jellyfin Media Assistant**. Diagnostics include catalog, player configuration, queue storage/advancement, pending-selection, and voice-sentence status while redacting the API key.

Useful checks:

- Confirm Home Assistant can reach the configured Jellyfin URL.
- Confirm the API key and user ID are valid and that the selected Jellyfin user can see the requested library.
- Confirm the desired Chromecast is available as a Home Assistant `media_player` and included in Playback Targets when an allowlist is configured.
- In diagnostics, verify that native intent handlers are registered and the managed sentence file is current when troubleshooting Assist.
- If the managed voice sentence file was customized, the integration preserves it and raises a Home Assistant Repair issue instead of silently overwriting it. The `jellyfin_assist.repair_voice_sentences` action can explicitly restore the packaged copy.

For reproducible bugs, include Home Assistant and Jellyfin versions, the request, the response/error, the playback target platform, and redacted Jellyfin Media Assistant diagnostics.

## Privacy and network behavior

Jellyfin Media Assistant communicates with the configured Jellyfin server and Home Assistant's media-player services. It does not require a cloud service of its own and does not include telemetry.

## Development

The project uses automated tests plus release-safety audits. Start with the [Developer Guide](docs/developer-guide.md) and [Architecture](docs/architecture.md).

The standard local gates are:

```powershell
python -m pytest -q
python -m tools.configuration_surface_audit
python -m tools.jellyha_dependency_audit
python -m tools.repository_packaging_audit
```

GitHub Actions also run pytest, Hassfest, and HACS repository validation at the appropriate release stage.

## License and attribution

Jellyfin Media Assistant is licensed under the [MIT License](LICENSE).

Portions of the native Jellyfin implementation were adapted from JellyHA under its MIT license. JellyHA is **not** a runtime dependency. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [JellyHA provenance](docs/provenance/jellyha.json) for attribution and source details.

## Release status

The first public beta, `0.1.0-beta.1`, is now available. See [CHANGELOG.md](CHANGELOG.md) for release contents and [Known Limitations](docs/known-limitations.md) for current boundaries.
