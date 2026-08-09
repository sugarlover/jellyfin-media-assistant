# Step 45C — Native Assist onboarding, Stage 1

## Goal

Move Jellyfin Media Assistant's voice intent handlers out of the household
`configuration.yaml` `intent_script:` block and into the integration without
changing the proven media resolver, queue, search, or Chromecast playback
behavior.

Stage 1 is intentionally additive. The current household `intent_script:` block
and `jellyha_media.yaml` custom-sentence file remain untouched until the native
path has been installed and is ready for a controlled cutover.

## Architecture

Home Assistant supports integration-provided intent platforms. Jellyfin Media
Assistant now provides `custom_components/jellyfin_assist/intent.py`, which
registers 27 canonical `JellyfinAssist...` intent handlers when Home Assistant's
Intent integration is active.

The handlers are thin adapters. They normalize the same slots previously
normalized by `intent_script:` and call the existing canonical scripts with
`blocking=True` and response data enabled. Script responses continue to use the
established `speak`/`message`/`display` response contract.

No resolver, queue algorithm, native Jellyfin search, item lookup, or Chromecast
playback implementation is duplicated in the intent layer.

## Custom sentence constraint

The Home Assistant default conversation agent currently loads user custom
sentences from `<config>/custom_sentences/<language>/`. It does not discover a
custom integration's bundled sentence directory automatically.

For public beta, the integration therefore packages the canonical English
sentence file at:

`custom_components/jellyfin_assist/custom_sentences/en/jellyfin_assist_media.yaml`

During the Stage 2 cutover, that one file is copied to:

`<config>/custom_sentences/en/jellyfin_assist_media.yaml`

This removes the large manual `intent_script:` merge while keeping one small,
explicit Home Assistant custom-sentence installation artifact.

## Namespace

The packaged file uses only canonical `JellyfinAssist...` intent IDs. The old
`JellyHA...` intent IDs remain live only in the unchanged household rollback
configuration during Stage 1.

Loading both the old and canonical sentence files at the same time is not part
of the rollout because they intentionally contain overlapping phrases. Stage 2
will switch sentence files atomically with removal of the old `intent_script:`
block.

## Diagnostics

Config-entry diagnostics now report:

- expected native intent handler count;
- currently registered native intent handler count;
- whether all native handlers are registered;
- whether the canonical custom sentence file is packaged;
- whether it is installed in Home Assistant's custom-sentence directory; and
- whether the installed copy matches the packaged copy.

The file comparison runs in Home Assistant's executor so diagnostics do not do
filesystem I/O directly on the event loop.

## Rollback safety

Stage 1 does not alter the working household voice path. If the integration
update itself causes a problem, restore the prior `custom_components/jellyfin_assist`
directory and restart Home Assistant.

Stage 2 will be tested before the current household `intent_script:` and legacy
sentence file are removed from the repository reference snapshot.
