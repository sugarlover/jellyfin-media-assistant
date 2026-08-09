# Step 42C — Native-first `get_item` production migration

Status: **production callers switched; JellyHA retained as temporary fallback**

Step 42B demonstrated exact live response parity for Movie, Episode, Audio, and
MusicAlbum items. Step 42C moves the three production metadata lookups from
`jellyha.get_item` to `jellyfin_assist.get_item` while preserving a reversible
compatibility path.

## Production routing

The canonical Home Assistant scripts now call:

```text
jellyfin_assist.get_item
```

The action performs native Jellyfin lookup first. If the native client raises an
expected API/validation lookup failure and `jellyha.get_item` is available, the
action logs a warning and retries through JellyHA. Successful native responses
do not call JellyHA.

The returned contract remains:

```text
{item: <Jellyfin item mapping>}
```

No queue, playback, resolver, or selection contract changes in this step.

## Config-entry targeting

Public reference scripts no longer contain a deployment-specific Home Assistant
config-entry ID. Jellyfin Media Assistant actions now behave as follows:

- if `config_entry_id` is supplied, that exact loaded entry is used;
- if it is omitted and exactly one Jellyfin Media Assistant entry is loaded,
  that entry is selected automatically;
- if more than one entry is loaded, the action requires an explicit selection.

This is backwards compatible with callers that already provide an entry ID and
removes the temporary household-specific ID from the public reference.

## Reversible fallback boundary

Step 42C deliberately does **not** remove JellyHA's `get_item` compatibility
path. The remaining use is dynamic inside `jellyfin_assist.get_item` and in the
read-only `compare_get_item` diagnostic. This means an installation with JellyHA
still has an automatic fallback while we validate production use.

The fallback is temporary. A later checkpoint may remove it after native-first
production use has remained stable. Until then, JellyHA remains a runtime
compatibility dependency even though no production script directly calls
`jellyha.get_item`.

## Validation

Automated validation requires:

- all three canonical production lookups call `jellyfin_assist.get_item`;
- zero canonical production actions call `jellyha.get_item`;
- native success never invokes JellyHA;
- expected native lookup failure invokes JellyHA when available;
- native failure remains a clear action error when JellyHA is unavailable;
- one loaded Jellyfin Assist entry can be inferred safely;
- multiple loaded entries still require explicit selection;
- the public reference contains no fixed Home Assistant config-entry ID.

Live validation should exercise the same three paths previously using
`jellyha.get_item`: pending selection hydration, direct add/play metadata, and
episode playback-plan enrichment. A single normal Chromecast play plus an
Episode path is sufficient for this migration checkpoint because Step 42B
already established cross-media response parity.

## Rollback

The code-level rollback is the previous green Step 42B commit. Before the
fallback is retired, runtime rollback can also be achieved by restoring the
three reference script action names to `jellyha.get_item`; the response contract
is unchanged.
