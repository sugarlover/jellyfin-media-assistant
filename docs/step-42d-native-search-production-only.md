# Step 42D — Native search becomes the sole production search backend

Status: **implementation complete; live smoke test required after CI**.

## Change

Canonical production resolver scripts no longer call `jellyha.search` and no
longer inspect `input_boolean.jellyfin_assist_robust_search`.

`script.jellyha_search_adapter` remains temporarily under its legacy
project-owned name to avoid unnecessary namespace churn, but it now routes every
supported production request directly to `jellyfin_assist.search`.

The resolver also removes two branches that existed only to support the legacy
JellyHA search path:

- the JellyHA-only episode-title shortcut; and
- substring-only artist/series/year post-filtering of legacy results.

## What did not change

- The robust catalog/matching algorithm is unchanged.
- Resolver, selection, orchestrator, queue, and playback response contracts are
  unchanged.
- `jellyfin_assist.compare_search` remains a read-only optional diagnostic and
  may call JellyHA when JellyHA is installed.
- `jellyha.get_item` remains a temporary failure fallback behind native
  `jellyfin_assist.get_item`.
- `jellyha.play_on_chromecast` remains the production Chromecast backend.

## Rollback

The prior green Git commit remains the rollback point. The retired robust-search
helper no longer provides runtime rollback and does not need to be deleted from
existing Home Assistant installations during this step.

## Live validation

After CI passes, update only the canonical project scripts in the live Home
Assistant instance and run a small set of known searches/playbacks, including an
exact title and at least one robust normalization case. No integration Python
files are required for this step because the native search action is unchanged.
