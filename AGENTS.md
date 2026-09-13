# Jellyfin Media Assistant engineering instructions

Canonical repository:

`/srv/ai-workspaces/jma-dev`

## Authority and scope

Follow the current task prompt plus repository documentation.

Files under `docs/development/` are user-authored engineering control-plane
contracts. Treat them as immutable unless the user explicitly authorizes a
control-plane change.

For the current series-playback feature, the authoritative frozen contracts are:

- `docs/development/series-playback-fallback-requirements.md`
- `docs/development/series-playback-fallback-kanban.md`

Do not reinterpret, weaken, or silently expand those requirements.

## Architecture

Preserve the existing JMA ownership boundaries:

- orchestration decides what to play;
- service/API code retrieves Jellyfin data;
- media actions own queue/session behavior;
- playback prepares a concrete playable item;
- playback strategies decide how an item is delivered.

Prefer the smallest architecture-consistent change. Reuse existing Jellyfin API
and service/query machinery rather than duplicating HTTP logic.

## Validation

The canonical repository validator is:

`./scripts/validate-candidate.sh`

A candidate is not complete until that validator passes.

Behavior changes should add focused regression coverage at the narrowest useful
layer and higher-level coverage when an integration contract changes.

## Repository hygiene

Run repository operations as the `hermes` user.

Do not configure global `safe.directory`.

Do not use recursive destructive cleanup such as `rm -rf`.

Only remove mechanically identified, allowlisted ephemeral artifacts.

Do not deploy to Home Assistant, restart Home Assistant, modify the live
integration, or change production services as part of a development card unless
the user explicitly requests a deployment task.

Keep the repository clean at accepted task boundaries.
