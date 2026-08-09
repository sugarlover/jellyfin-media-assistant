# Step 44A — Retire JellyHA get_item fallback

Status: **native-only item lookup; JellyHA fallback and compare_get_item diagnostic retired**

## Why this step exists

`jellyfin_assist.get_item` has already been the production-first item lookup path,
but Step 42C intentionally kept `jellyha.get_item` as a temporary failure fallback
while native behavior was proven. Native search and Chromecast playback are now in
production, and live Chromecast parity has passed for Movie, Episode, Audio, and
Series → Next Up. Keeping the fallback would create an unnecessary second-integration
runtime dependency for public users.

## Runtime change

`jellyfin_assist.get_item` now has exactly one lookup implementation:

1. resolve the Jellyfin Media Assistant config/runtime;
2. validate `item_id`;
3. call the native Jellyfin client;
4. preserve the established `{item: ...}` response contract;
5. surface `item_lookup_failed` if the native API cannot retrieve the item.

It no longer checks for, calls, or falls back to `jellyha.get_item`.

The migration-only `jellyfin_assist.compare_get_item` action is also removed. Its
purpose was to prove exact native/JellyHA response parity before the production
migration. Retaining it after fallback retirement would preserve an otherwise dead
`jellyha.get_item` runtime call surface.

## Regression guard

The Home Assistant service tests now register a fake `jellyha.get_item`, force the
native client to fail, and assert both that `item_lookup_failed` is surfaced and that
Home Assistant records **no JellyHA service call**. The dependency audit also fails if
`LEGACY_JELLYHA_GET_ITEM_SERVICE`, `SERVICE_COMPARE_GET_ITEM`,
`async_handle_compare_get_item`, or a `jellyha.get_item` string reappears in the
runtime service/constants implementation.

## Dependency result

Normal Jellyfin Media Assistant operation no longer requires JellyHA for:

- search;
- item metadata lookup;
- Chromecast playback.

`jellyha.search` remains reachable only through the optional `compare_search`
development diagnostic. `jellyha.play_on_chromecast` and `jellyha.get_item` remain
only in historical/provenance/reference material and previous commits used for
rollback.

Therefore **JellyHA is not a required integration for public installation**.

## Rollback

Rollback is repository-based, not runtime fallback-based. If native item lookup shows
an unexpected live regression, return to the previous green Step 43C commit. Do not
reintroduce a hidden JellyHA fallback into the release path.

## Live smoke test

After installing Step 44A and restarting Home Assistant, call
`jellyfin_assist.get_item` for a known item (for example the already-verified Jurassic
World ID) and then run a normal Assist playback command. A successful result proves
that the standalone native item lookup remains healthy in the live environment.
