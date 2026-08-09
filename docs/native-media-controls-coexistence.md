# Native media controls coexistence

Jellyfin Media Assistant previously registered broad, player-only wildcard
sentences for pending media-player follow-ups. Those patterns could capture
ordinary Home Assistant commands such as `pause Movie Screen`, `resume Example Chromecast`,
or `turn off Example Secondary Chromecast` before Home Assistant's native media-player intents
were evaluated.

Pending-player follow-ups now require an explicit continuation phrase:

- `use Movie Screen`
- `choose Example Secondary Chromecast`
- `play it on Movie Screen`
- `add it to Example Secondary Chromecast`
- `continue on Movie Screen`

Bare player phrases are intentionally no longer registered by Jellyfin Media
Assistant. This keeps the integration from claiming unrelated native commands.
Home Assistant remains responsible for pause, resume, stop, mute, volume, and
power controls, including native entity aliases.
