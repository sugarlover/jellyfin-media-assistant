# Configuration

Jellyfin Media Assistant owns its configuration through the Home Assistant config entry and options flow. A supported installation does not require Jellyfin Media Assistant YAML in `configuration.yaml`.

Current config-entry schema: **1.3**.

## Jellyfin connection settings

These values are stored in config-entry data and validated during setup:

| Setting | Required | Purpose |
|---|---:|---|
| `server_url` | Yes | Complete HTTP(S) base URL Home Assistant uses to reach Jellyfin. |
| `api_key` | Yes | Jellyfin API key used by the integration. |
| `user_id` | Yes | Jellyfin user whose accessible libraries define the searchable catalog. |
| `verify_ssl` | No | Whether HTTPS certificates are verified; defaults to `true`. |

The URL must be a complete `http://` or `https://` URL without embedded credentials, query parameters, or fragments.

The API key is stored in the Home Assistant config entry and redacted from diagnostics.

## Playback options

Open **Settings → Devices & services → Jellyfin Media Assistant → Configure**.

| Option | Required | Purpose |
|---|---:|---|
| Default Media Player | No | Used when a media or queue request does not name a player. |
| Playback Targets | No | Additional allowed `media_player` entities for Jellyfin Media Assistant. |

The default player is automatically part of the effective allowed-target set; it does not need to be selected twice.

### Player resolution

Jellyfin Media Assistant derives player names from Home Assistant instead of maintaining a private alias table.

Resolution uses, in conservative order:

1. an explicit `media_player.*` entity ID;
2. normalized Home Assistant friendly names;
3. Home Assistant entity-registry aliases;
4. bounded normalization/typo recovery when an allowlist of playback targets is available; and
5. the configured default when no player was requested.

Add instance-specific synonyms through the normal Home Assistant entity aliases. Do not edit the packaged custom sentence file just to add household player names.

A configured entity that no longer exists is not silently used as a default. An existing but currently unavailable entity can still be resolved so playback can return the platform-specific failure.

## Search catalog and cache

At setup, the integration validates Jellyfin and maintains a local search catalog for the configured Jellyfin user. Catalog metadata is cached in Home Assistant storage so a previously populated integration can start with its cache if Jellyfin is temporarily unavailable.

The cache contains sanitized catalog metadata, not the Jellyfin API key.

## Queue persistence

Per-player queue/session state is owned by Jellyfin Media Assistant and persisted using Home Assistant storage. There is no queue-service URL or external queue daemon in the current schema.

Queue state includes the current position, history/previous item information, upcoming items, and repeat settings. Mutating queue operations are serialized and saved through the integration-owned store.

A new `play` operation starts a fresh queue session and resets Repeat Item and Repeat Queue. `add` appends to the current queue without resetting repeat state.

## Pending request state

Two conversational states are held in memory per config entry:

- a pending media choice when several search results require a numbered selection; and
- a pending media request when Jellyfin Media Assistant needs the user to specify a playback target.

These states are intentionally temporary and do not survive an integration/Home Assistant restart.

## Managed Assist sentences

The canonical English sentence file ships inside the integration at:

```text
custom_components/jellyfin_assist/custom_sentences/en/jellyfin_assist_media.yaml
```

During setup/update, Jellyfin Media Assistant manages the runtime copy under Home Assistant's `custom_sentences/en/` directory.

- Missing managed file: install the packaged copy.
- Unchanged managed file: update it when the packaged version changes.
- User-modified managed file: preserve it and create a Home Assistant Repair issue instead of overwriting it.

`jellyfin_assist.repair_voice_sentences` is troubleshooting/recovery tooling. It can explicitly restore the packaged version when requested.

## Diagnostics

Downloaded diagnostics report information such as:

- stored/current config-entry schema version;
- Jellyfin connection/catalog state;
- whether startup used the offline catalog cache;
- default and allowed playback targets;
- recent player-resolution diagnostics;
- queue storage and automatic-advancement state;
- pending selection/request state; and
- managed voice-sentence and registered-intent status.

Secrets such as the API key are redacted.

## Configuration migration

Schema 1.3 accepts earlier development entries and normalizes them without discarding unknown values.

Notable compatibility behavior:

- legacy `default_media_player` and `playback_targets` values stored in config-entry data are moved to options;
- explicit options take precedence over legacy data;
- scalar legacy playback-target values are converted to a list;
- blanks and duplicates are removed; and
- the retired `queue_service_url` key is removed from both data and options.

The migration is idempotent.
