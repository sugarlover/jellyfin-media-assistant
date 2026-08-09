# Step 46A — Native Persistent Queue

## Outcome

Jellyfin Media Assistant no longer requires a separately deployed queue service.
Per-player queue/session state is persisted by the integration using Home
Assistant's storage helper and is loaded when the config entry starts.

The established queue response envelope and semantics are preserved so the
already-proven orchestration, queue-control, repeat, shuffle, and automatic
advancement layers do not need behavioral rewrites.

## Public-install impact

A new installation no longer needs:

- Python outside Home Assistant;
- a second Docker container;
- a Home Assistant App/add-on for the queue service;
- TCP port 8787;
- a queue-service URL option;
- queue REST commands or YAML.

Queue state follows the Jellyfin Media Assistant config entry and is stored with
Home Assistant's integration storage.

## Compatibility

Config-entry schema 1.3 retires the old `queue_service_url` option. Migration
removes that key from config-entry data/options while retaining Jellyfin
connection values and playback-target settings.

This pre-beta migration does not import `queues.json` from the former external
queue container. Existing private test deployments should keep that container
available only as rollback until native queue behavior is live-validated. A new
native queue starts empty and is populated by the next play/add request.

The internal queue store still implements remove-by-position for future work,
but no `queue_remove` Home Assistant action or Assist command is exposed in the
first beta.

## Persistence and concurrency

Queue operations are serialized by an async lock. Mutating operations save the
full JSON-serializable queue mapping through Home Assistant storage. Loading also
normalizes the older `queue + current` shape to the current `current_index`
shape so persisted native data remains tolerant of the project's earlier queue
model.

## Validation

Release tests cover:

- empty queue response parity;
- add / next / completion history;
- Repeat Item and Repeat Queue;
- shuffle while preserving the current item;
- clear semantics;
- future internal remove behavior without public exposure;
- invalid item/position handling;
- persistence across store recreation (restart simulation);
- old queue-state normalization;
- storage failure boundaries;
- retirement of the HTTP client and external queue-service artifacts.
