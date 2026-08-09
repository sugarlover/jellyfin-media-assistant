# Step 41A — Configuration Surface Inventory

## Outcome

Step 41A records the configuration and privacy surface of the stable Step 40
repository. It adds an audit guard and documentation only. It does **not** alter
Home Assistant setup, service registration, search, playback, queue behavior,
player resolution, or the household reference configuration.

Baseline validation before this step: **443 tests passed**.

## Executive finding

The native `custom_components/jellyfin_assist` integration is already largely
configuration-driven:

- Jellyfin server URL, API key, user ID, and TLS verification are stored in the
  Home Assistant config entry.
- The default media player and additional playback targets are stored in the
  integration options.
- Media-player names and aliases are discovered from Home Assistant's entity
  registry rather than embedded in the integration.
- The integration's runtime package contains no known household player entity,
  household address, household user ID, phone entity, or NAS library path.

The remaining public-release blockers are concentrated in the preserved
`reference/current-working` household package, duplicated reference scripts,
test fixtures, and a small number of documentation examples.

## Inventory

| Surface | Current owner/location | Current state | Public-beta disposition |
|---|---|---|---|
| Jellyfin server URL | Integration config entry | Configurable | Keep |
| Jellyfin API key | Integration config entry; local `.env` for tools | Configurable and redacted by diagnostics | Keep; never track `.env` |
| Jellyfin user ID | Integration config entry | Configurable in integration; one household ID remains in reference YAML | Remove from tracked reference YAML |
| TLS verification | Integration config entry | Configurable; defaults to enabled | Keep |
| Default media player | Integration options | Configurable in integration | Keep; remove legacy YAML fallback |
| Allowed playback targets | Integration options | Configurable in integration | Keep; reuse for queue advancement |
| Player aliases | Home Assistant entity registry | Native and instance-local | Keep; do not publish household aliases |
| Queue-service base URL | Household `rest_command` YAML | Fixed household address and port | Add a temporary compatibility setting or replace the external dependency |
| Queue-service listen host/port/data directory | Queue-service Python and Compose files | Fixed deployment defaults | Make environment-configurable before publishing |
| Queue advancement targets | Household automation | Two fixed player entities | Derive from configured playback targets or integration-managed listeners |
| Default-player fallbacks in scripts | Household and duplicated reference scripts | Fixed household player | Replace with integration option lookup while preserving fallback compatibility during migration |
| Custom Assist player list | Household sentence YAML | Fixed aliases and entity IDs | Remove from public package; rely on native HA aliases or local-only configuration |
| Robust-search feature toggle | Household helper entity | Local migration switch | Move to an integration option or retire after migration is final |
| Pending-selection helpers | Household helper entities and scripts | Legacy YAML state | Preserve until their integration replacement is ready; rename in stages |
| Jellyfin REST helper commands | Household `configuration.yaml` | Fixed address/user and secret reference | Replace with integration API calls before public beta |
| Library filesystem paths | Tracked repository | None found | Continue prohibiting them |
| Local `.env` | Ignored but present in the uploaded full-folder ZIP | Not tracked by Git | Exclude from future shared ZIPs |
| Upstream JellyHA reference source | `reference/current-working/jellyha` | Vendored reference with upstream examples | Handle in Step 42 provenance/dependency work |

## Known Step 40 debt baseline

The audit intentionally treats the current counts as a **ceiling**, not as
public-release approval. A future commit fails the audit if a known local value
appears in a new location or if its count increases.

| Rule | Baseline occurrences | Files | Meaning |
|---|---:|---:|---|
| Household player entity IDs | 131 | 13 | Reference YAML, tests, and two documentation examples |
| Household player aliases | 41 | 6 | Reference sentences, tests, and one behavior document |
| Household network address | 12 | 1 | Household Home Assistant REST commands |
| Household Jellyfin user ID | 5 | 1 | Household Home Assistant REST commands |
| Personal-name test fixture | 4 | 3 | Test-only connection metadata |
| Household phone entity | 0 | 0 | Prohibited from being introduced |
| Household NAS storage path | 0 | 0 | Prohibited from being introduced |
| Fixed household default fallback | 7 | 3 | Runtime reference script, duplicate reference, and contract test |
| Fixed queue-service port | 10 | 3 | REST commands, server default, and Compose mapping |

No actual API key was found in Git-tracked files. The tracked YAML uses a Home
Assistant secret reference. The uploaded archive did include an untracked local
`.env`, which is why future review archives should be created without local
ignored files.

## Configuration ownership model

Public configuration should have one clear owner:

### Home Assistant config-entry data

Required connection and identity values:

- `server_url`
- `api_key`
- `user_id`
- `verify_ssl`

### Home Assistant integration options

User-selectable behavior:

- `default_media_player`
- `playback_targets`
- temporary queue-backend compatibility settings, only if the external queue
  service still exists in the beta
- migration feature switches only while they are genuinely needed

### Derived Home Assistant state

Values that should not be duplicated in Jellyfin Media Assistant configuration:

- entity friendly names
- entity-registry aliases
- device and area names
- current media-player state

### Deployment environment

Only for a separately deployed queue service, if retained:

- listen host
- listen port
- persistent data directory
- time zone

### Internal constants

Safe implementation defaults, not instance configuration:

- request timeout
- catalog page size
- cache filename and integration-owned storage directory
- supported media-type constants

## Guard added by Step 41A

Run:

```bash
python -m tools.configuration_surface_audit
```

The command scans Git-tracked files only. It fails when:

- a sensitive local file such as `.env` or `secrets.yaml` is tracked;
- a known household value moves outside its inventoried debt area; or
- the number of known household/configuration-debt occurrences increases.

The test suite also verifies that the runtime integration remains free of known
household identifiers.

## Recommended next task

**Step 41B should separate the tracked public reference from the exact household
snapshot without changing the live Home Assistant installation.**

The safe sequence is:

1. Copy the exact household reference snapshot to an ignored local-only path.
2. Verify that the copy matches the Step 40 tag.
3. Replace tracked household addresses, user IDs, player entities, and aliases
   with generic placeholders/examples.
4. Keep the live Home Assistant files untouched.
5. Run the complete suite and the configuration audit.
6. Commit only the sanitized public reference and audit updates.

This removes the highest-risk publication exposure while preserving immediate
rollback to the Step 40 tag and leaving runtime behavior unchanged.


## Step 41B completion

Step 41B completed the reference separation described above:

- the exact household snapshot is preserved only in the ignored local path
  `reference/private-current-working/household-step-40/`;
- the tracked Home Assistant reference uses host, user-ID, player, alias, and
  user-name placeholders/examples;
- the public audit no longer contains knowledge of any specific household;
- the project automation was renamed to
  `jellyfin_assist_automations.example.yaml` to prevent accidental replacement
  of a live Home Assistant `automations.yaml`; and
- runtime integration behavior remains unchanged.

The current tree is sanitized, but earlier Git history is not. The development
repository must remain private until a clean public history is created or a
separately audited history rewrite is completed.

The next configuration-abstraction task is to replace the temporary hardcoded
example/default-player fallbacks and fixed queue-service deployment settings
with integration-owned configuration, one dependency at a time.

## Step 41C completion

Step 41C formalized the integration-owned public configuration schema as config-
entry version **1.2**:

- Jellyfin connection and identity values remain in config-entry data;
- default and allowed playback targets remain in config-entry options;
- normalization is centralized in `configuration.py`;
- legacy player settings accidentally stored in config-entry data are migrated
  into options with option values taking precedence;
- scalar playback-target values remain supported as a compatibility input;
- native Home Assistant entity aliases remain derived and instance-local; and
- setup retains a read-only legacy fallback so interrupted migration cannot
  remove a configured player.

Step 41D subsequently validated this schema live without changing playback,
search, queue, or alias behavior. Step 42C also removes the temporary hardcoded
Home Assistant config-entry ID from the public reference by allowing safe
single-entry inference; explicit entry targeting remains supported for
multi-entry installations.
