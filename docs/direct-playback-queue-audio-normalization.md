# Direct playback queue Audio normalization

The media orchestrator has two queue insertion paths:

- `operation: add` calls the native `jellyfin_assist.queue_add_item` action.
- `operation: play` clears the queue and writes each playback-plan item through the native `jellyfin_assist.queue_add` action.

The direct playback path must normalize shared Jellyfin numbering fields independently. For every `Audio` playback-plan item it sends empty `season` and `episode` values to the queue, while the item itself retains `disc_number`, `track_number`, and `index_number` for ordering and diagnostics.

For `Episode` and other supported media types, the existing season/episode behavior is unchanged.

This prevents artist, album, and multi-track playback plans from storing audio track numbers as television episode numbers.
