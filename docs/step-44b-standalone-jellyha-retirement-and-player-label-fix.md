# Step 44B — Standalone JellyHA retirement and player response-name fix

Status: **implemented and automated tests required before live uninstall**

## Preconditions proven live

The household installation successfully executed the normal Assist production path with the JellyHA integration disabled for both:

- `Play Jurassic World on Attic TV`
- `Play the song The Sound Of Silence by Disturbed on Attic TV`

Both requests started playback on the requested Chromecast. This proves native search, native `get_item`, native player resolution, the queue/orchestrator contract, and native Chromecast playback can operate without JellyHA loaded.

## Runtime retirement

Step 44B removes the last callable upstream JellyHA service path from `custom_components/jellyfin_assist`:

- removes the `jellyfin_assist.compare_search` action;
- removes its `jellyha.search` call and shadow runtime module;
- removes legacy JellyHA service constants and comparison-only public metadata;
- strengthens the release dependency audit so `jellyha.get_item`, `jellyha.search`, `jellyha.play_on_chromecast`, `compare_search`, or `LEGACY_JELLYHA_*` cannot reappear in the integration runtime unnoticed.

The vendored JellyHA snapshot, historical reference tests, provenance JSON, and MIT attribution remain because they document the source and contracts used during the migration. They are not runtime dependencies.

## Player response-name fix

The live standalone smoke test also exposed a response-only bug: the request targeted `media_player.attic_tv`, playback correctly occurred there, but Assist said `Main TV` because Home Assistant's current friendly name was used after the intent layer had already converted the spoken alias to an entity ID.

For explicit entity-ID resolution, the integration now chooses names in this order:

1. a distinct native Home Assistant entity alias, when configured;
2. a stable humanized entity-ID name (for example `media_player.attic_tv` → `Attic TV`);
3. the current Home Assistant friendly name when it does not conflict with the entity-derived household name.

Configured defaults continue to prefer the Home Assistant friendly name, and direct spoken aliases continue to echo the matched alias. The target entity itself is unchanged.

## Rollback

Rollback no longer requires JellyHA to remain installed. The previous green Step 44A/43C repository state is the rollback point. If a regression is discovered, restore that commit/release artifact while diagnosing it.

## Release implication

After automated tests and one post-update household smoke test pass, JellyHA may be uninstalled from the household Home Assistant instance. The public Jellyfin Media Assistant installation must not instruct users to install JellyHA.
