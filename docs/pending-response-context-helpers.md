# Pending response context state

> Superseded by Step 45E2.

Earlier pre-beta builds stored pending multi-match response context in Home
Assistant `input_text` and `input_boolean` helpers. Step 45E2 moves that state
into the Jellyfin Media Assistant config-entry runtime.

New installations do **not** create the former pending-selection helpers.
Existing private installations may leave them in place temporarily while
validating Step 45E2; the current scripts no longer read or write them.

See `docs/step-45e2-native-pending-selection-state.md` for the current design.
