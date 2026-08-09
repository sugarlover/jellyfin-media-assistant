# Queue command player resolution

Queue-management intents now use the same native Home Assistant media-player
resolver as play and add requests.

## Behavior

- Native Home Assistant names and aliases are accepted, including normalized
  punctuation and `TV` / `T V` variants.
- The configured default player is used when the player is omitted.
- A supplied but unrecognized player never falls back silently to the default.
- Missing-player requests are retained so a player-only follow-up can resume the
  original queue operation.
- User-facing queue responses preserve the matched explicit alias while queue
  storage continues to use the canonical entity ID.

## Supported queue operations

- next
- what's playing
- what just played
- queue status
- clear queue
- shuffle queue
- repeat item
- repeat queue
- repeat off
- repeat-item toggle
- repeat-queue toggle

The implementation contains no instance-specific player aliases. Those remain in
Home Assistant's entity registry.
