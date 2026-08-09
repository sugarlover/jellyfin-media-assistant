# Optional default media player

Step 35 adds an optional default playback target to the Jellyfin Media Assistant
config entry.

## Resolution order

For media play and add requests:

1. An explicitly named media player always wins.
2. If the request omits a player, the configured default is used when it still
   exists in Home Assistant.
3. If no usable default exists, the request is preserved and the response asks
   which media player should be used.
4. A player-only follow-up resumes the preserved request through the existing
   `media_orchestrator` contract.

Search, selection, queue, and playback are not started until a media player has
been resolved.

## Configuration

Open **Settings → Devices & services → Jellyfin Media Assistant → Configure**
and choose **Default media player**. Leave the field blank to require a player
when one is not spoken.

Changing the option reloads the config entry. No Home Assistant helper is
required.

## Pending request scope

One pending player request is retained in memory per Jellyfin Media Assistant
config entry. This matches the project's current single-pending-selection
conversation model. It is intentionally not persisted across an integration or
Home Assistant restart.

## Safety

- Explicit player input overrides the default.
- A configured entity that no longer exists is not used silently.
- An unavailable-but-existing media player remains a valid target; playback can
  report its own failure normally.
- The selected player is validated as a `media_player` entity before resuming.

## Current scope

This step applies the new configuration and follow-up behavior to media play and
add requests handled by `media_orchestrator`. The existing queue-management
intent defaults are unchanged in this package and can be unified in a later
intent cleanup without changing the player-resolution service contract.
