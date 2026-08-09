# Step 43B — Parallel native Chromecast action

## Goal

Expose the Step 43A Chromecast strategy through a fully native Jellyfin Media
Assistant action **without changing the household production route**.

Production remains:

```yaml
- action: jellyha.play_on_chromecast
```

The new test path is:

```yaml
- action: jellyfin_assist.play_on_chromecast
```

## Native action contract

`jellyfin_assist.play_on_chromecast` accepts the same two production-facing
fields used by the current JellyHA call:

- `entity_id` — target `media_player` entity;
- `item_id` — Jellyfin item ID.

It also accepts optional `config_entry_id` when more than one Jellyfin Media
Assistant configuration is loaded.

The action supports an optional response for live diagnostics while remaining
callable without a `response_variable`, so a later production switch can remain
a one-line service-domain change.

The successful response intentionally excludes the Jellyfin stream URL/API key.
It reports only non-secret diagnostics such as resolved item ID/type, Chromecast
model, legacy-device flag, direct-play/transcode mode, and content type.

## Native playback flow

The new path performs these steps without invoking a JellyHA service:

1. resolve the loaded `jellyfin_assist` config entry;
2. fetch the requested item with the native Jellyfin client;
3. for Series/Season, query Jellyfin `/Shows/NextUp` using the frozen JellyHA
   field contract and resolve to one Episode;
4. discover the Chromecast model in Home Assistant's executor;
5. apply the Step 43A direct-play/transcode strategy;
6. build JellyHA-compatible movie/audio/episode metadata;
7. call Home Assistant `media_player.play_media` with `blocking: true`.

The integration now declares Home Assistant's built-in `cast` integration as a
manifest dependency. This lets Home Assistant own the compatible PyChromecast
package version instead of Jellyfin Media Assistant pinning a potentially
conflicting copy.

## Automated protection

Step 43B adds coverage for:

- native `/Shows/NextUp` request parameters;
- no-next-up behavior;
- image URL parity;
- Movie playback without any JellyHA service call;
- Series -> Next Up Episode resolution;
- episode metadata (`seriesTitle`, season, episode);
- response privacy (no API key in the returned action response);
- optional-response registration;
- service metadata/selectors;
- the complete Step 43A strategy parity matrix.

The existing release dependency audit still requires exactly one direct
`jellyha.play_on_chromecast` call in canonical production scripts, preventing an
accidental production cutover during this step.

## Rollback boundary

There is still no household routing change. If the native test path fails, the
existing scripts continue to use JellyHA unchanged.

Removing the Step 43B integration/service additions returns the repository to
Step 43A behavior.

## Live parity gate before production switch

Test the native action directly in Home Assistant against the same known player
and library items already proven through JellyHA:

1. Movie;
2. explicit Episode;
3. Audio track;
4. Series/Season Next Up behavior.

For each test, verify playback actually begins on the Chromecast and capture the
native action response. Production must remain on JellyHA until those live tests
pass.

After live parity succeeds, Step 43C can switch only the canonical playback
adapter from `jellyha.play_on_chromecast` to
`jellyfin_assist.play_on_chromecast`, while retaining an immediate rollback
commit/path.
