# Pending-selection media normalization

When an ambiguous result is selected, the existing playback flow still calls
`jellyha.get_item` to retrieve rich Jellyfin metadata. Jellyfin uses
`ParentIndexNumber` and `IndexNumber` for both television and music, so the
selected item must be normalized according to its media type before it enters
the queue.

## Audio

- `ParentIndexNumber` becomes `disc_number`.
- `IndexNumber` remains `index_number` for compatibility and also becomes
  `track_number`.
- `season_name`, `season_number`, and `episode_number` stay empty.

## Episode

- `ParentIndexNumber` becomes `season_number` and supplies `season_name`.
- `IndexNumber` becomes `episode_number`.
- `disc_number` and `track_number` stay empty.

## Ambiguous audio prompts

Numbered Audio choices include artist names, for example:

```text
1. 3 AM by Matchbox Twenty (1996)
2. 3 A.M. by NF (2017)
```

The search and playback architectures remain unchanged. This is only a
media-aware normalization and presentation layer around the selected result.
