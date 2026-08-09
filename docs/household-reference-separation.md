# Step 41B — Household Reference Separation

## Outcome

Step 41B separates the exact household snapshot from the tracked public
reference without changing the runtime integration or the live Home Assistant
installation.

The exact Step 40 reference belongs under the ignored local path:

```text
reference/private-current-working/household-step-40/
```

The tracked `reference/current-working` tree is now a sanitized behavioral
reference. It uses placeholders and clearly marked example media players rather
than household addresses, user IDs, aliases, or entity IDs.

## Safety boundary

This repository is not the live Home Assistant configuration directory. Step
41B changes only development/reference files. It does not update, reload, or
restart Home Assistant.

The project automation is stored as:

```text
jellyfin_assist_automations.example.yaml
```

It is deliberately **not** named `automations.yaml`. A Home Assistant UI-created
automation is stored in the live `automations.yaml`; replacing that file would
remove unrelated automations. The example must be merged into an existing live
file, never copied over it wholesale.

## Sanitized surfaces

- Jellyfin and queue-service host: `MEDIA_SERVER_HOST`
- Jellyfin user identifier: `JELLYFIN_USER_ID`
- media-player entities: `media_player.example_*`
- sentence aliases: explicitly labeled `Example ...`
- test connection name: `Example User`
- documentation and test aliases: generic fixtures only

The runtime integration remains configuration-driven and unchanged.

## Git-history warning

Step 41B sanitizes the current tree, not existing Git history. Earlier commits,
branches, and the Step 40 rollback tag still preserve the pre-sanitization
reference. Keep the development repository private.

Before the public HACS beta, use one of these separately validated approaches:

1. create a new public repository from the sanitized release tree; or
2. perform and independently verify a full history rewrite.

Creating a clean public repository is the lower-risk option because it preserves
the private development repository and rollback tags intact.

## Validation

Run:

```bash
python -m tools.configuration_surface_audit
python -m pytest
```

The audit requires the public Home Assistant reference to contain no private
network address, inline 32-character Jellyfin user ID, non-example media-player
entity, tracked sensitive file, or local storage path.
