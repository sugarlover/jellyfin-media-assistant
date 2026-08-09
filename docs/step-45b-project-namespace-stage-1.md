# Step 45B — Project namespace migration, stage 1

Status: **canonical script-callable namespace introduced with rollback-safe compatibility aliases**

Baseline: `615a68b` (`44D and 44E`), with the full automated suite green.

## Goal

Begin removing project-owned `jellyha_*` naming without changing the already-proven
native Jellyfin search, item lookup, player resolution, queue behavior, or Chromecast
playback logic.

This step intentionally uses a staged migration. Names that can be changed without
state migration are moved first. Names tied to Home Assistant helpers, Assist
registration, or queue-service deployment remain explicitly bounded compatibility
debt for the next onboarding/configuration step.

## Canonical script namespace

The active implementations now use `script.jellyfin_assist_*` IDs. The generic
`script.media_orchestrator` implementation is now
`script.jellyfin_assist_media_orchestrator` as well.

Every former project-owned script ID remains temporarily available as a small
compatibility wrapper. Each wrapper forwards to the canonical script and returns the
canonical response unchanged. New production routing does not call the wrappers.

This preserves household automations that may still reference the old entity IDs
while giving all new code one public namespace.

## Intentionally deferred names

The following are *not* renamed in Step 45B:

- `rest_command.jellyha_queue_*` — these duplicate fixed queue-service configuration if
  aliases are added in YAML. The release configuration-surface audit caught that
  duplication during development, so the guardrail was preserved rather than relaxed.
- `input_text.jellyha_*` / `input_boolean.jellyha_*` — these are stateful household
  helpers. Renaming them blindly would lose or fork pending/queue state and would
  require manual helper migration.
- `JellyHA...` Assist intent IDs and `jellyha_media.yaml` — these should move when
  intent/sentence registration is made self-contained in the integration, avoiding a
  manual rename now followed by a second migration immediately afterward.
- queue service/container name `jellyha-queue` — rename it together with the public
  deployment/onboarding surface so Docker upgrade and rollback instructions remain
  deterministic.

These are compatibility names owned by this project, not runtime dependencies on the
upstream JellyHA integration.

## Guardrails

`tests/release/test_project_namespace_migration.py` freezes the migration boundary:

- canonical scripts must contain the implementations;
- legacy script IDs must be compatibility wrappers only;
- current Home Assistant routing may not call a legacy script ID;
- remaining legacy REST commands, helpers, intents, and queue container names must stay
  within an explicit allowlist; and
- user-facing current-working text may not describe the project itself as JellyHA.

If a later step intentionally migrates one of the deferred surfaces, update this
allowlist in the same commit.

## Rollback

The rollback point remains commit `615a68b`. No search, item-resolution, playback, or
queue algorithm is changed by this step. If live validation exposes an unexpected Home
Assistant script-call issue, restore the 44D/44E scripts/configuration and reload or
restart Home Assistant.

## Live acceptance

After installing the updated current-working Home Assistant YAML:

1. verify `script.jellyfin_assist_media_orchestrator` and the canonical queue/control
   scripts are present;
2. verify at least one old `script.jellyha_*` entity is still present as a compatibility
   alias;
3. run a normal explicit-player playback request through Assist;
4. run one queue-control request through Assist; and
5. optionally invoke one legacy alias directly to confirm an old automation would still
   forward successfully.

No JellyHA integration should be installed or required for any of these checks.
