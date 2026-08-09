# Step 45E1 — Native Queue Advancement

## Goal

Remove the manually installed Home Assistant queue-advancement automation from
the first-beta onboarding surface without changing queue semantics or low-level
playback behavior.

## Runtime ownership

`custom_components/jellyfin_assist/advancement.py` now owns automatic queue
advancement for every configured playback target. The integration registers
state-change listeners during config-entry setup and removes those listeners
when the entry unloads.

The listener preserves the proven automation contract:

- react only to `playing` -> `idle` transitions;
- estimate final playback position using the reported position, position update
  timestamp, and continuous playing time;
- require at least 95 percent completion;
- extract the Jellyfin item ID from the media content URL;
- require that ID to match the queue service's current item;
- advance the external queue service only after those checks pass;
- start the new current queue item through
  `script.jellyfin_assist_play_media`;
- keep normal completion and safely rejected transitions silent; and
- create persistent notifications only for queue read, queue advance, or next
  playback failures.

The external queue service remains unchanged.

## Rollback

During live deployment, leave the existing automation available but disable it
before restarting with native queue advancement. If validation fails, restore
the previous integration files and re-enable the automation. Do not run both
advancement paths simultaneously because one completed item could be advanced
twice.

## Diagnostics

Config-entry diagnostics include `queue_advancement` with:

- `mode: native`;
- the registered playback targets;
- the 95 percent completion threshold; and
- the last advancement result.

## Public onboarding effect

The sanitized Home Assistant reference no longer ships an automation example.
A first-beta user no longer needs to merge a queue-advancement automation into
`automations.yaml`.
