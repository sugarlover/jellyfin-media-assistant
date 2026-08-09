# Response Contract Context Preservation

This step preserves the original request context across failed and ambiguous media
resolution without changing matching, queue, or playback behavior.

## Resolver outcomes

`jellyha_resolve_media_intent` now returns the resolved/requested media intent for
both `not_found` and `multiple_matches` outcomes instead of returning a null
`intent`.

Examples:

- An unsuccessful Audio request returns `intent: Audio`.
- An ambiguous Movie request returns `intent: Movie`.
- An inferred untyped request uses the resolver's existing fallback media type.

## Pending selection context

The existing `input_text.jellyha_pending_media_operation` helper now stores a
compact JSON object containing:

- `o`: operation (`play` or `add`)
- `q`: original query
- `i`: original intent/media type

No additional Home Assistant helper is required. The pending-selection script
continues to accept the old plain `play` and `add` values for backward
compatibility.

After a numbered selection, responses preserve the user's original query rather
than returning `query: null`. Container selections (Series, MusicAlbum, and
MusicArtist) also restore the original query and intent after their second-stage
resolution.

## Non-goals

This step does not change:

- search normalization or scoring;
- ambiguity thresholds;
- queue contents or queue state;
- JellyHA playback calls;
- Assist sentence parsing;
- script/entity namespaces.
