# Step 41C — Public Configuration Schema and Compatibility

## Outcome

Step 41C establishes one versioned, integration-owned configuration contract for
Jellyfin Media Assistant. It centralizes normalization and adds a backwards-
compatible config-entry migration without changing search, playback, queue,
player matching, or native Home Assistant alias behavior.

Schema version: **1.3**

- major version: `1`
- minor version: `3`

The minor-version change is backwards compatible. Schema 1.3 retires the
`queue_service_url` option because queue state is now persisted natively inside
Home Assistant; existing connection and playback values are retained.

## Persisted ownership

### Config-entry data

Connection and identity values required to reach Jellyfin:

| Key | Type | Required | Default |
|---|---|---:|---|
| `server_url` | complete HTTP(S) URL | Yes | None |
| `api_key` | non-empty string | Yes | None |
| `user_id` | non-empty Jellyfin user ID | Yes | None |
| `verify_ssl` | boolean | No | `true` |

These values are normalized by `JellyfinConnectionSettings`.

### Config-entry options

User-selectable playback behavior:

| Key | Type | Required | Default |
|---|---|---:|---|
| `default_media_player` | one `media_player` entity ID | No | None |
| `playback_targets` | list of additional `media_player` entity IDs | No | Empty |

These values are normalized by `JellyfinBehaviorSettings`. Queue state is not a
user-configurable endpoint; it is integration-owned persistent state stored with
Home Assistant.

The default media player is always part of the effective allowed-target list.
It is removed from the stored `playback_targets` list so users do not have to
select the same player twice.

## Derived values that are not configuration

The integration continues to derive these values from Home Assistant:

- entity friendly names;
- entity-registry aliases;
- area and device names;
- current media-player state.

There is intentionally no public `player_aliases` configuration key. Instance-
specific aliases remain native Home Assistant entity aliases.

## Compatibility rules

### Legacy behavior keys stored in config-entry data

An older development entry may contain either of these keys in `entry.data`:

- `default_media_player`
- `playback_targets`

Migration 1.1 → 1.2 moves them to `entry.options`. Migration to 1.3 also removes
the retired `queue_service_url` key from either data or options.

Rules:

1. Existing option values take precedence over legacy data values.
2. The legacy keys are removed from config-entry data.
3. Unknown data and option keys are preserved.
4. A scalar `playback_targets` value is accepted and converted to a list.
5. Duplicate and blank player values are removed.
6. Migration is idempotent.
7. Setup retains a read-only fallback for the legacy layout so a skipped or
   interrupted migration cannot break playback configuration.
8. The retired `queue_service_url` option is discarded during migration; queue
   state is now owned by Home Assistant storage.

### Compatibility export

`_normalize_playback_targets` remains available from the integration package as
a compatibility wrapper. The implementation now lives in the centralized
configuration module.

### Unsupported configuration sources

The native integration does not read runtime configuration from:

- `configuration.yaml` integration blocks;
- environment variables;
- helper entities;
- hardcoded household player fallbacks;
- tracked custom-sentence alias lists.

Legacy household YAML remains a behavioral reference until its orchestrator and
queue responsibilities are moved into the integration in later steps.

## Diagnostics

Diagnostics now report the stored and current config-entry schema versions.
The API key remains redacted.

## Files added or changed

- `custom_components/jellyfin_assist/configuration.py`
- `custom_components/jellyfin_assist/__init__.py`
- `custom_components/jellyfin_assist/api.py`
- `custom_components/jellyfin_assist/config_flow.py`
- `custom_components/jellyfin_assist/diagnostics.py`
- `tests/homeassistant/ha_stubs.py`
- `tests/homeassistant/test_configuration.py`
- `tests/homeassistant/test_config_flow.py`
- `tests/homeassistant/test_diagnostics.py`
- `tests/homeassistant/test_setup.py`

## Validation

```text
Configuration surface audit: PASS
465 tests passed
```

## Rollback

This step is isolated on `release/pre-beta`. Rollback options are:

1. revert the Step 41C commit; or
2. return to tag `household-stable-step-40` for the complete pre-release
   household baseline.

No live Home Assistant YAML file is replaced by this step.

## Next dependency-aware task

Step 41D should remove the remaining fixed default-player fallback from the
legacy Home Assistant reference scripts and make those scripts obtain the
configured default through the integration-owned resolver contract. The change
should retain the current fallback during a short compatibility window and be
validated against both named-player and omitted-player requests.
