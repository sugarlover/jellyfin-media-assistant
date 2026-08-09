# Play starts a fresh repeat session

A new `play` operation now resets both queue repeat modes before replacing the
queue:

- Repeat Item: off
- Repeat Queue: off

This prevents repeat state from a previous listening session from unexpectedly
carrying into a later song, album, artist, movie, series, or episode request.

## Semantics

- `play`: reset both repeat modes, clear/replace the queue, and start playback.
- `add`: preserve the existing repeat modes and append media.
- manual or automatic queue advancement: preserve the existing repeat modes.
- low-level playback: does not change repeat settings, so queue advancement and
  intentional repeat behavior remain functional.

Both direct play requests and numbered pending-selection play requests use the
same idempotent `jellyfin_assist_prepare_play_session` helper. If the queue
service cannot confirm that both repeat modes are off, the play request stops
with `repeat_reset_failed` rather than silently starting with stale repeat
state.
