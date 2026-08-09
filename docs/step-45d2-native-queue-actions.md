# Step 45D2 — Native Queue-Service Actions

> **Superseded by Step 46A:** the external queue service described in this historical migration note was later retired. Current releases persist queue state natively inside the Jellyfin Media Assistant integration.


## Outcome

The seven Home Assistant `rest_command.jellyha_queue_*` definitions are retired from the active configuration surface. Jellyfin Media Assistant now exposes native response-only actions that talk to the existing external queue service while preserving the proven `status` / `content` / `headers` response envelope used by the scripts.

Native actions used by the current beta runtime:

- `jellyfin_assist.queue_get`
- `jellyfin_assist.queue_add`
- `jellyfin_assist.queue_next`
- `jellyfin_assist.queue_clear`
- `jellyfin_assist.queue_set_repeat`
- `jellyfin_assist.queue_shuffle`

The queue service itself is not rewritten in this step. Its API, port, state format, repeat behavior, shuffle behavior, and advancement semantics remain unchanged.

## Queue-service URL

The integration derives the default endpoint as `http://<Jellyfin host>:8787`. An optional `queue_service_url` integration option allows a different host, port, or HTTPS reverse-proxy endpoint without requiring `configuration.yaml`. Existing config entries need no migration because the option is additive and the default is deterministic.

## Rollback safety

The queue-service server and data are untouched. During live deployment, the new actions can be installed first while the old REST commands remain available. Scripts are cut over only after action registration is confirmed. The REST definitions can then be removed after live queue tests pass.

## Deferred namespace cleanup

The queue server still reports the historical service/container name `jellyha-queue`. That identifier is transport metadata only and is intentionally deferred so this step does not change the proven queue-service process or persisted state.

`/queue/remove` remains an internal queue-service endpoint only. A user-facing remove-from-queue feature is intentionally deferred beyond the first public beta. The queue service also retains its historical `/queue/settings` route internally; the Home Assistant action is named `queue_set_repeat` because that route is used only to update Repeat Item / Repeat Queue state.
