# Home Assistant search-only integration shell

Step 23 introduces the first loadable Home Assistant custom integration under
`custom_components/jellyfin_assist`.

## Scope

The integration is intentionally search-only. It does not replace or modify
JellyHA playback, item retrieval, the resolver, the orchestrator, or the queue
service.

At Home Assistant startup it:

1. registers the response-only `jellyfin_assist.search` action;
2. loads one config entry created through the UI;
3. restores the private metadata cache when available;
4. validates the Jellyfin server, API key, and selected user;
5. downloads an initial read-only catalog when no cache exists; and
6. refreshes an existing cache in an entry-owned background task.

If Jellyfin is temporarily unavailable during startup, a valid existing cache
may still be used. Authentication failures never silently fall back to cache.

## Search action

The action accepts a required `query` plus optional media type, artist, album,
series, and year context. `config_entry_id` is required so an action remains
predictable if another Jellyfin server is configured later.

The action uses `SupportsResponse.ONLY`, so it is called from Developer Tools or
a script with response data enabled. Its response is the frozen contract in
`docs/search-action-contract.md`.

## Security boundary

The runtime client permits only HTTP GET. API keys are stored in the Home
Assistant config entry, are excluded from cache files and search responses, and
are redacted from downloaded diagnostics.
