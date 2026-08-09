# Jellyfin Media Assistant

Jellyfin Media Assistant is a Home Assistant custom integration that lets Home Assistant Assist search a Jellyfin library, play media on Chromecast targets, and manage persistent per-player queues using natural-language voice commands.

> **Public beta:** `0.1.0-beta.1` is being prepared for first public testing. Chromecast is the tested and supported playback platform. Other Home Assistant media players are experimental and may not work correctly yet.

Jellyfin Media Assistant is an independent community project and is not affiliated with or endorsed by the Jellyfin project or Nabu Casa/Home Assistant.

## What it does

- Searches movies, series, episodes, songs, albums, and artists in Jellyfin.
- Handles common punctuation, spacing, numeric, and speech/transcription variations when matching titles.
- Plays resolved Jellyfin media through Home Assistant on Chromecast targets.
- Supports explicit requests such as movies, songs, albums, artists, seasons, and episodes.
- Presents numbered choices when a request has multiple plausible matches.
- Maintains a persistent queue per configured player.
- Supports Next, What's Playing, What Just Played, Queue Status, Clear Queue, Shuffle, Repeat Item, Repeat Queue, and Repeat Off.
- Automatically advances after a queued item finishes.
- Automatically installs and updates the managed English Assist sentence file.
- Provides diagnostics with secrets redacted.

## Requirements

- Home Assistant **2026.7.0 or newer**.
- A Jellyfin server reachable from Home Assistant.
- A Jellyfin API key and the Jellyfin user ID whose accessible libraries should be searched.
- For supported playback, a Chromecast exposed to Home Assistant as a `media_player` entity.
- HACS is recommended for installation but is not required for a manual install.

Tested for the first beta with Home Assistant 2026.7.x, Jellyfin 10.11.x, and Chromecast playback.

## Installation with HACS

Until Jellyfin Media Assistant is included in HACS' default repository list, install it as a custom repository:

1. Open HACS in Home Assistant.
2. Open **Custom repositories**.
3. Add `https://github.com/sugarlover/jellyfin-media-assistant` as an **Integration** repository.
4. Find **Jellyfin Media Assistant** in HACS and install it.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration** and select **Jellyfin Media Assistant**.

The GitHub repository must be public before HACS can install it. The beta release checklist covers that publication step.

## Manual installation

1. Copy `custom_components/jellyfin_assist` from this repository into your Home Assistant configuration directory as `custom_components/jellyfin_assist`.
2. Restart Home Assistant.
3. Add **Jellyfin Media Assistant** from **Settings → Devices & services**.

No separate Python installation, Docker container, queue service, YAML script package, helper entities, REST commands, or automations are required.

## Configuration

### 1. Connect Jellyfin

The setup flow asks for:

- **Jellyfin server URL** — for example, the local URL Home Assistant uses to reach Jellyfin.
- **API key** — create a dedicated key in Jellyfin for Home Assistant/Jellyfin Media Assistant.
- **Jellyfin user ID** — the user whose library access defines the searchable catalog.
- **Verify SSL certificate** — keep enabled for trusted certificates; disable only when required for a trusted local self-signed setup.

The API key is stored in the Home Assistant config entry and is redacted from diagnostics.

### 2. Configure playback targets

Open **Settings → Devices & services → Jellyfin Media Assistant → Configure**.

- **Default Media Player** is used when a voice request does not name a player.
- **Playback Targets** limits the media players Jellyfin Media Assistant may resolve and use.

Home Assistant friendly names and area context are used for player resolution. Instance-specific aliases are not hard-coded into the integration.

### 3. Use Assist

The integration provisions its managed English sentence file automatically during setup/update. No manual `custom_sentences` copy is normally required.

Example commands:

- “Play Jurassic World on the basement TV.”
- “Play the album Weathered by Creed on the attic TV.”
- “Play music by Creed.”
- “Play season 1 of the show The Twilight Zone.”
- “Play the episode Where Is Everybody from The Twilight Zone.”
- “What's playing on the attic TV?”
- “Shuffle the queue on the attic TV.”
- “Next song on the attic TV.”
- “Repeat this song.”
- “Repeat the queue.”
- “Turn repeat off.”

If a search has several plausible matches, Assist lists numbered choices. Reply with a number such as “1” or “Number 1.”

## Queue behavior

Queues are stored persistently in Home Assistant's `.storage` through the integration. Queue state survives Home Assistant restarts and is maintained separately per playback target.

Starting a new **Play** request creates a new playback session and resets repeat modes. **Add/Queue** requests append media to the existing queue.

## Supported and experimental playback

**Supported for the first beta:** Chromecast media players.

Other Home Assistant `media_player` platforms are experimental. They may appear as selectable targets, but the current playback path is built and tested around Chromecast behavior. Community feedback and issue reports for other platforms are welcome.

## Diagnostics and troubleshooting

Download diagnostics from **Settings → Devices & services → Jellyfin Media Assistant**. Diagnostics report catalog status, player configuration, queue storage/advancement, pending selection, and voice-sentence status while redacting the API key.

Useful checks:

- Confirm Home Assistant can reach the Jellyfin server URL.
- Confirm the API key and user ID are valid and the selected Jellyfin user can see the requested library.
- Confirm the desired Chromecast is available as a Home Assistant `media_player` entity and included in Playback Targets.
- In diagnostics, verify `all_native_intent_handlers_registered` and `custom_sentences_current` are `true` when troubleshooting Assist.
- If the managed voice sentence file was customized, Home Assistant will preserve it and raise a Repair issue instead of silently overwriting it. The `jellyfin_assist.repair_voice_sentences` action can restore the packaged copy when explicitly requested.

For reproducible bugs, include Home Assistant/Jellyfin versions, the voice/action request, the response or error, and redacted Jellyfin Media Assistant diagnostics in a GitHub issue.

## Upgrading and rollback

Before beta upgrades, keep a normal Home Assistant backup. HACS can install a selected GitHub release when releases are published. Queue and catalog state are stored outside the integration source directory in Home Assistant storage, so replacing the integration code does not intentionally erase those data stores.

If an update fails, restore the previous HACS release or restore the Home Assistant backup and report the issue.

## Privacy and network behavior

Jellyfin Media Assistant communicates locally with the configured Jellyfin server and Home Assistant's media-player services. It does not require a cloud service of its own and does not include telemetry.

## Development

Run the local test and release-audit gates with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tools.configuration_surface_audit
.\.venv\Scripts\python.exe -m tools.jellyha_dependency_audit
```

GitHub Actions also run pytest and hassfest. HACS repository validation is enabled during the final publication stage after the repository is public and the required brand asset is present.

## License and attribution

Jellyfin Media Assistant is licensed under the [MIT License](LICENSE).

Portions of the native Jellyfin implementation were adapted from JellyHA under its MIT license. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the provenance documentation in `docs/` for attribution and the retained upstream reference.

## Release status

The first public beta is being prepared on the `release/pre-beta` branch. See [CHANGELOG.md](CHANGELOG.md) for the beta contents.
