# Step 45C Stage 2 — Native Assist cutover

Stage 2 retires the legacy Home Assistant `intent_script:` plumbing after the
native `jellyfin_assist` intent platform was validated live.

## Runtime cutover

The working Home Assistant instance was changed in two rollback-safe moves:

1. copy the packaged `jellyfin_assist_media.yaml` sentence file into
   `<config>/custom_sentences/en/` and move the legacy `jellyha_media.yaml`
   outside that directory;
2. after native Assist playback succeeded, remove the 27 legacy `JellyHA...`
   entries from `configuration.yaml`.

The integration-owned packaged sentence file remains in
`custom_components/jellyfin_assist/custom_sentences/en/` so diagnostics can
verify that the installed Home Assistant copy is current.

## Live acceptance

After the legacy `intent_script:` block was removed, both of these commands
succeeded through the native intent handlers:

- `Play Jurassic World on the basement TV.`
- `What's playing on the basement TV?`

This proves both a media-play intent and a queue/status intent operate through
the canonical `JellyfinAssist...` sentence and native-handler path.

## Rollback boundary

No search, resolver, queue algorithm, or Chromecast playback implementation was
changed. The Step 45B legacy script wrappers remain available temporarily as a
rollback/compatibility boundary. The old sentence file may also be retained
outside Home Assistant's active `custom_sentences` directory as a local backup,
but it is no longer part of the public current-working reference.
