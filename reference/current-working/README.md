# Sanitized Current-Working Baseline

Snapshot lineage: stable household implementation through Step 40.

This directory preserves the project's behavioral contracts for development and
testing. It is a **sanitized public reference**, not an exact Home Assistant
backup and not a deployment package.

## Contract boundary

The following behavior is treated as stable unless testing identifies a genuine
bug:

- media intent resolver response structure
- orchestrator operation and result structure
- playback item structure and Jellyfin item IDs
- pending-selection helper behavior
- queue-service request and response structures
- queue advancement, history, repeat, shuffle, and completion behavior

## Sanitization

- the media-server and queue-service address is `MEDIA_SERVER_HOST`
- the Jellyfin user identifier is `JELLYFIN_USER_ID`
- media-player entities use `media_player.example_*`
- player aliases are explicitly labeled examples
- unrelated household automations are not included
- NAS-specific queue-service paths are portable relative paths
- credentials, live queue data, databases, logs, and `.storage` data are excluded

The exact household reference must remain in the ignored local path
`reference/private-current-working/household-step-40/` and must never be
committed.

The copied JellyHA source remains a provenance reference for Step 42 and retains
its upstream license and attribution.
