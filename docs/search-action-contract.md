# `jellyfin_assist.search` action response contract

The future Home Assistant action will return the JSON-safe mapping produced by
`serialize_search_action_response()`.

## Resolver compatibility

The top-level `items` field preserves the current resolver's cardinality
contract:

- confident match: exactly one item;
- ambiguous match: ranked choices, bounded by the response item limit;
- no acceptable match: an empty list.

A complete-word title fragment such as `planet` may therefore return up to the
configured item limit when several titles contain that token. Fragment matching
does not use arbitrary substrings, so `plan` does not qualify as `Planet`.

The top-level `item`, `selected`, and `jellyfin_id` fields are populated only
for a confident automatic match. They remain `null` for ambiguous and not-found
responses.

## Additive diagnostics

The response also contains:

- the original query and supplied media context;
- decision status, reason, thresholds, and observed margin;
- selected match family, method, lexical, phonetic, context, and total scores;
- labeled attempted query variants;
- ranked alternatives and context evidence;
- logical-entity provider IDs and every retained physical Jellyfin ID;
- catalog provenance, age, counts, health, and timing.

These fields are additive. Existing resolver, orchestrator, playback, and queue
contracts do not need to consume them during initial shadow testing.

## Home Assistant registration

Registration is a later integration-lifecycle step. The integration will call
Home Assistant's action/service registration API under the domain
`jellyfin_assist` and action name `search`, with response support enabled. After
registration, the action will appear as `jellyfin_assist.search` in Developer
Tools and can be invoked by scripts or the media resolver.

## Audio title collisions and track numbering

Distinct audio items whose titles have the same punctuation- and
conventional-number-insensitive spoken form are returned as ambiguous choices
unless explicit artist, album, or year context safely separates them. Thus a
bare `three am` request can return both `3 AM` and `3 A.M.`, while `three am by
NF` may resolve directly.

For `Audio` items, `track_number` and `disc_number` carry Jellyfin's
`IndexNumber` and `ParentIndexNumber`. `season_name`, `season_number`, and
`episode_number` remain empty or null so music metadata is not presented as TV
metadata. `index_number` is retained as the track index for compatibility.
