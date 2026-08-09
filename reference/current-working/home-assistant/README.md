# Sanitized Home Assistant Compatibility Fixture

The files in this directory preserve a minimal sanitized Home Assistant configuration boundary used by regression tests.

They are **not** a complete Home Assistant configuration and should not be copied over a live `/config` directory.

The supported integration owns Jellyfin connection settings, player options, native queue persistence, pending selection/request state, automatic queue advancement, and Assist sentence provisioning. The fixture therefore contains no Jellyfin REST commands, queue REST commands, project-owned scripts, project helper entities, or queue-advancement automation.

Real instance-specific player names and aliases belong in Home Assistant. Public examples use `media_player.example_*` identifiers.
