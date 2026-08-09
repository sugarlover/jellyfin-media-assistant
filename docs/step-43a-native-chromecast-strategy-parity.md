# Step 43A — Native Chromecast strategy parity

## Goal

Start replacing the final major JellyHA production dependency without moving the live household playback path yet.

The production call remains:

```yaml
- action: jellyha.play_on_chromecast
```

No production YAML routing or Home Assistant service registration changes in this slice.

## What was added

`custom_components/jellyfin_assist/playback_strategy.py` contains the media analysis, Chromecast model discovery helper, and direct-play/transcode URL strategy used by the installed JellyHA 1.2.0 reference.

The derived portions retain the JellyHA MIT provenance notice. The complete frozen upstream reference and license remain in `reference/current-working/jellyha/`.

## Parity protection

`tests/homeassistant/test_playback_strategy.py` loads the frozen JellyHA 1.2.0 strategy and compares native output against it across:

- modern H.264 direct play;
- modern video transcode;
- legacy 720p direct play;
- legacy 1080p transcode;
- 10-bit video transcode;
- modern FLAC audio direct play;
- legacy FLAC audio transcode;
- legacy MP3 direct play;
- M4A/AAC direct play;
- audio stream-index selection behavior.

`tests/reference/test_jellyha_chromecast_contract.py` freezes the rest of the live action boundary:

1. fetch the requested Jellyfin item;
2. resolve Series/Season to the next-up episode;
3. discover the Chromecast model in an executor;
4. analyze codecs and choose a playback URL;
5. call Home Assistant `media_player.play_media` with Jellyfin metadata;
6. preserve episode metadata fields.

## Rollback boundary

There is nothing to roll back in the household configuration because Step 43A does not register or route a native playback action.

Deleting the additive strategy/tests/doc restores the previous repository behavior.

## Next dependency-aware slice

Step 43B should register a parallel response-capable `jellyfin_assist.play_on_chromecast` action using the native config entry/client and the Step 43A strategy. Production YAML must continue to call JellyHA.

That parallel action can then be invoked manually in Home Assistant Developer Tools against the same known items/player used by the production path. Only after live movie, episode, and audio parity succeeds should the production `script.jellyha_play_media` call be switched.
