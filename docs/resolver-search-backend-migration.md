# Resolver search-backend migration

Status: **production migration complete in Step 42D**.

The resolver originally used `input_boolean.jellyfin_assist_robust_search` as a
live rollback switch between `jellyha.search` and `jellyfin_assist.search`.
After the robust-search implementation passed automated regression coverage and
extended household production testing, Step 42D retires that runtime branch.

## Current production path

```text
jellyfin_assist_resolve_media_intent
        ↓
script.jellyfin_assist_search_adapter   (legacy project-owned script name)
        ↓
jellyfin_assist.search
        ↓
existing zero / one / many selection logic
        ↓
existing orchestrator, queue, get_item, and playback actions
```

The adapter name remains `jellyfin_assist_search_adapter` temporarily for compatibility;
it is a project-owned legacy name and no longer calls the upstream JellyHA
search service.

Artist, series, and year context are passed directly to the native matcher. The
old substring-only post-filter and the JellyHA-only episode-title shortcut have
been removed from production routing.

## Retired helper

`input_boolean.jellyfin_assist_robust_search` is no longer read by the canonical
production scripts. Existing household installations may leave the helper in
place harmlessly until the later namespace/helper cleanup. New public installs
do not need it.

## Rollback

Rollback is now source-controlled rather than a live Home Assistant toggle. If
a regression is found during pre-beta validation, restore the prior green Git
commit and the corresponding `scripts.yaml`/integration files.

The read-only `jellyfin_assist.compare_search` action remains available as an
optional development diagnostic while JellyHA is installed. It is not used by
production search routing and is not required for normal operation.
