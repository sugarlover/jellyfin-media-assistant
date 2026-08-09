# Step 46B — Managed Assist sentence provisioning

Step 46B removes the final manual voice-file installation step from the supported
Jellyfin Media Assistant onboarding path.

## Normal installation and upgrades

The canonical English Assist sentence file remains packaged at:

`custom_components/jellyfin_assist/custom_sentences/en/jellyfin_assist_media.yaml`

During config-entry setup, Jellyfin Media Assistant manages the Home Assistant
runtime copy at:

`<config>/custom_sentences/en/jellyfin_assist_media.yaml`

The integration creates the directory when necessary. If the installed file is
missing, it installs the packaged version. If the installed file is byte-for-byte
identical to the packaged file, it adopts the file as managed. When a later
integration update ships a new packaged version, Jellyfin Media Assistant updates
the installed file only when the installed copy still matches the checksum of the
last version written by the integration.

When Home Assistant's `conversation.reload` action is available, a changed sentence
file is reloaded immediately. If Conversation is not loaded, sentence provisioning
still succeeds and the file is available the next time Conversation/Home Assistant
loads it.

## User modifications are preserved

The integration stores only management metadata and a checksum in Home Assistant
storage. If the installed managed sentence file no longer matches the checksum of
the version last written by Jellyfin Media Assistant, it is treated as
user-modified. Setup continues, the user's file is left untouched, and a Home
Assistant Repair issue explains the condition.

The `jellyfin_assist.repair_voice_sentences` action is recovery tooling rather than
a normal onboarding step. By default it also preserves a user-modified file. The
user must explicitly enable `overwrite_user_modified` to restore the packaged
version.

## Diagnostics

The voice diagnostics now report whether the sentence file is packaged, installed,
current, managed, or user-modified, plus the result of the most recent automatic
provisioning/reload attempt.

## Public-install impact

A normal Jellyfin Media Assistant user no longer needs to copy a sentence YAML file
into Home Assistant manually. The intended beta/production flow is integration
installation, config-entry setup, player configuration, and Assist use.
