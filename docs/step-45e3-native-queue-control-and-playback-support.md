# Step 45E3: Native Queue Control and Playback Support

Step 45E3 moves the queue-control and playback-support layer out of Home
Assistant scripts and into the Jellyfin Media Assistant integration. The goal is
installation-surface reduction, not a resolver or playback redesign.

## Native behavior in this step

The integration now owns the high-level behavior previously implemented by the
following script families:

- queue status / what's playing / what just played;
- manual next;
- queue clear and shuffle;
- repeat item, repeat queue, and repeat-off behavior;
- play-session repeat reset;
- queue item insertion and metadata normalization; and
- playback of a resolved Jellyfin item.

The low-level queue transport actions from Step 45D2 remain available as stable
building blocks. Chromecast playback still uses the proven native
`jellyfin_assist.play_on_chromecast` implementation.

## Remaining Home Assistant scripts

The public behavioral reference is reduced to seven resolver/orchestrator
scripts:

- `jellyfin_assist_play_pending_media`
- `jellyfin_assist_tv_episode_resolver`
- `jellyfin_assist_episode_title_resolver`
- `jellyfin_assist_search_adapter`
- `jellyfin_assist_resolve_media_intent`
- `jellyfin_assist_resume_pending_media_request`
- `jellyfin_assist_media_orchestrator`

These scripts are intentionally left for a later stage so this migration does
not combine queue/playback-support changes with the media resolver rewrite.

## Native bridge actions

The remaining resolver/orchestrator scripts call native integration actions for
operations that Step 45E3 moved into Python:

- `jellyfin_assist.play_item`
- `jellyfin_assist.queue_add_item`
- `jellyfin_assist.prepare_play_session`
- `jellyfin_assist.queue_command`

Queue-control Assist intents dispatch directly to
`jellyfin_assist.queue_command`; they no longer depend on a queue-command YAML
script.

## Compatibility cleanup

Legacy project-owned `jellyha_*` script aliases and the old
`script.media_orchestrator` alias are retired from the public script reference.
They are not JellyHA integration dependencies and are no longer required by the
current native intent/runtime path.

## Response and behavior contracts

Step 45E3 preserves the user-visible queue-control response patterns and the
existing playback path. Audio queue insertion continues to keep Jellyfin track
numbering separate from TV season/episode fields. Automatic queue advancement
now calls the same native play-item implementation used by manual queue
advancement.

## Rollback/live validation

For an existing private deployment, keep a backup of the Step 45E2 script file
and integration directory until live validation is complete. After deploying
Step 45E3, validate at least:

1. album playback (session reset, queue population, first-item playback);
2. what's playing;
3. shuffle;
4. manual next;
5. natural automatic advancement; and
6. pending multi-match selection followed by a numeric choice.

If those paths pass, the removed queue/playback-support scripts are no longer
part of the supported installation surface.
