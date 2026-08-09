# Player options and queue-notification polish

This patch makes three user-facing refinements:

1. The options flow uses `Default Media Player` and `Playback Targets` labels from both `strings.json` and `translations/en.json`.
2. The configured default is automatically included in the effective playback-target allowlist. The multi-select stores only additional targets.
3. Player responses use a matched native alias when possible. When Home Assistant pre-resolves an entity slot to an entity ID, the first distinct native entity alias is treated as the preferred spoken response name. Defaults and fuzzy corrections continue to use the canonical friendly name.

The companion Chromecast queue-advancement automation is renamed to `Jellyfin Assist Queue Advancement - Chromecast`. Normal completion, completion-candidate rejection, and successful advancement are silent. Persistent notifications are created only when queue state cannot be read, queue advancement fails, or the next item cannot be started.

The automation remains a companion Home Assistant reference configuration in this development version; it is not yet registered by the custom integration runtime.
