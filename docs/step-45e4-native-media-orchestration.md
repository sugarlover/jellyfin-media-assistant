# Step 45E4 — Native media orchestration

Step 45E4 removes the final Jellyfin Media Assistant Home Assistant YAML scripts.
The remaining resolver/orchestrator behavior now lives in
`custom_components/jellyfin_assist/orchestration.py` and is exposed through three
high-level native actions:

- `jellyfin_assist.media_orchestrator`
- `jellyfin_assist.play_pending_media`
- `jellyfin_assist.resume_pending_media_request`

Voice intents dispatch directly to these native actions. Internal TV-episode,
episode-title, general media-resolution, queue-add, repeat-reset, and resolved-item
playback helpers remain Python implementation details instead of becoming new
user-facing Home Assistant actions.

The migration deliberately preserves the established response envelope (`success`,
`status`, `operation`, `intent`, `query`, `message`, `speak`, `display`, item and
playback-plan context), native player-resolution behavior, runtime pending-selection
state, and queue/playback boundaries proven in earlier release steps.

## Public Home Assistant YAML surface

Jellyfin Media Assistant no longer requires a project-owned `scripts.yaml`. The
sanitized reference configuration therefore does not include one. Users may keep
unrelated Home Assistant scripts and their own `script: !include scripts.yaml`
configuration; that is outside Jellyfin Media Assistant.

## Rollback

During the live cutover, keep the Step 45E3 seven-script file and the prior
integration files as a rollback checkpoint until native movie, album, TV episode,
pending-number selection, pending-player continuation, queue control, and natural
advancement tests pass.
