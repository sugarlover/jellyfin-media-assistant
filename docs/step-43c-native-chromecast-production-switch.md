# Step 43C — Native Chromecast production switch

Status: **production routing switched after live parity proof; JellyHA rollback preserved**

## Gate satisfied

Step 43B intentionally left production on `jellyha.play_on_chromecast` until the
native action proved parity on the live supported platform. On 2026-08-07 the
household Chromecast smoke tests passed all four required paths:

1. Movie — `Jurassic World` (2015), direct play
2. Direct Episode — `The Twilight Zone` S1E1, `Where Is Everybody?`, direct play
3. Audio — `The Sound Of Silence` by Disturbed, MPEG audio direct play
4. Series — `The Twilight Zone` Series ID resolved natively through Jellyfin
   Next Up to S1E1 and played successfully

The Series test also verified the response contract preserved
`requested_item_id` as the Series ID while returning the resolved Episode ID and
`resolved_from_type: Series`.

## Production routing change

The canonical low-level playback script keeps its stable project-owned name:

```text
script.jellyha_play_media
```

but its playback backend changes from:

```text
jellyha.play_on_chromecast
```

to:

```text
jellyfin_assist.play_on_chromecast
```

No resolver, queue, orchestrator, repeat-mode, player-wakeup, wait, or response
contract changes are included in this step.

## Dependency state after 43C

Canonical Home Assistant production scripts now contain **zero direct upstream
JellyHA actions**. Remaining JellyHA relationships are transitional or
diagnostic:

- `jellyha.get_item`: temporary failure fallback behind native get-item plus a
  parity diagnostic;
- `jellyha.search`: optional read-only comparison diagnostic;
- `jellyha.play_on_chromecast`: retired production backend retained only in
  vendored reference/history for rollback/provenance.

This does **not** yet mean JellyHA can be uninstalled, because the get-item
fallback remains intentionally active.

## Rollback

The prior green Step 43B commit is the code-level rollback point. For an
immediate live Home Assistant rollback without reverting the entire repository,
change the single action inside `script.jellyha_play_media` back to:

```yaml
- action: jellyha.play_on_chromecast
  data:
    entity_id: '{{ media_player }}'
    item_id: '{{ item_id }}'
```

The input and behavior contract is unchanged, so no caller changes are required
for that rollback.

## Live production validation after applying 43C

After updating the canonical scripts in Home Assistant, run the normal user-facing
path rather than the developer action directly. A known command such as
`Play Jurassic World` on the configured Chromecast is sufficient for the first
production smoke test. If it succeeds, native Chromecast playback is production
proven through the full resolver/orchestrator/script path.
