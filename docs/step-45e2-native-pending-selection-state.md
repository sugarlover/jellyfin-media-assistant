# Step 45E2 — Native pending-selection state

## Goal

Remove the remaining Home Assistant helper-entity requirement without changing
search, resolver, queue, or playback algorithms.

## Runtime change

Pending multi-match choices are now stored inside the loaded Jellyfin Media
Assistant config entry instead of Home Assistant `input_text` and
`input_boolean` helpers.

The YAML resolver scripts still own the proven matching and response behavior.
Only persistence changes:

- `jellyfin_assist.pending_selection_set` stores the resolved choices, player,
  operation, original query, and intent.
- `jellyfin_assist.pending_selection_get` restores that state for a spoken
  numbered selection.
- `jellyfin_assist.pending_selection_clear` clears it only after a successful
  play/add/container continuation.

Diagnostics report whether pending selection state is active and how many
choices are stored, without requiring helper entities.

## Retired helper entities

New installs no longer require any of these project-owned helpers:

- `input_text.jellyha_pending_media_results`
- `input_text.jellyha_pending_media_player`
- `input_text.jellyha_pending_media_operation`
- `input_text.jellyfin_assist_pending_query`
- `input_text.jellyfin_assist_pending_intent`
- `input_boolean.jellyha_media_selection_pending`
- `input_text.jellyha_media_queue`
- `input_boolean.jellyha_media_queue_active`

The final two belonged only to an obsolete local-YAML queue implementation.
The corresponding unused queue set-player/get/remove scripts and their legacy
aliases are removed from the public reference. Queue removal remains deferred
and is not exposed as a native beta action.

## Rollback

Existing helper entities may remain in a private Home Assistant installation
until this step is live-tested. They are simply no longer referenced by the new
script set. Keeping them temporarily therefore provides filesystem/configuration
rollback safety without creating two active state owners.
