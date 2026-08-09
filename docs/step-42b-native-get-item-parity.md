# Step 42B — Native `get_item` parity

## Goal

Add `jellyfin_assist.get_item` without changing any production caller. The existing
three `jellyha.get_item` calls remain untouched until live parity is demonstrated.

## Upstream contract pinned for this work

The implementation behavior was verified against JellyHA commit
`6b8b2f679f922ea3a0d9c3c4b9827ee7053308f9` (JellyHA 1.2.0), specifically:

- `custom_components/jellyha/api.py` — the `get_item` endpoint and requested field set.
- `custom_components/jellyha/services.py` — response enrichment and `{item: ...}` shape.

JellyHA is MIT licensed. Attribution and the license notice are retained in
`THIRD_PARTY_NOTICES.md` and `reference/current-working/jellyha/LICENSE`.

## Native action

`jellyfin_assist.get_item` requires an explicit Jellyfin Media Assistant config entry
and one Jellyfin `item_id`. It performs only a GET request and returns:

```yaml
item: <Jellyfin item mapping>
```

To preserve the legacy contract, the item is enriched with:

- `media_streams` from the first `MediaSources` entry when available, otherwise
  from top-level `MediaStreams`;
- `is_favorite` from `UserData.IsFavorite`, defaulting to `false`;
- `is_played` from `UserData.Played`, defaulting to `false`.

## Parity action

`jellyfin_assist.compare_get_item` sends the same item ID through both native
`jellyfin_assist` and the selected JellyHA config entry. It compares the complete
response mappings, reports exact parity, and lists JSON-style differing paths.
It is diagnostic only and never modifies playback, queues, or Jellyfin metadata.

## Rollback and switching policy

Step 42B does **not** replace any `jellyha.get_item` production calls. Therefore
rollback is simply removing the new integration files or returning to the prior
commit; household behavior continues to use JellyHA throughout parity testing.

Only after automated tests and live comparisons across representative Movie,
Episode, Audio, and MusicAlbum items agree should the three production callers be
migrated in a separate step. That migration remains independently reversible.
