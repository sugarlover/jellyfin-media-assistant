# Catalog search tests

These tests cover the pure retrieval boundary. They do not register a Home
Assistant action, contact the user's Jellyfin server, or alter the stable
resolver/playback/queue pipeline.

## Query planning

`test_planning.py` verifies that planning:

- keeps the user's original query first;
- emits only a small ordered set of deterministic normalization variants;
- adds a bounded hyphenated form for plain two-word queries only as a zero-result fallback;
- adds bounded joined-word split attempts only as zero-result fallbacks;
- pairs spaced and hyphenated split forms because Jellyfin may treat title
  hyphens as significant during retrieval;
- never sends fuzzy or phonetic guesses to Jellyfin;
- deduplicates case-only search terms while preserving meaningful Unicode
  compatibility attempts;
- bounds both per-attempt retrieval and the final unique candidate pool;
- deduplicates returned items by Jellyfin ID;
- records which attempted terms produced each candidate; and
- exposes invalid, duplicate, and truncated-item diagnostics.

## Retrieval orchestration

`test_retrieval.py` executes planned attempts through an injected asynchronous
catalog client. It verifies request order and limits, explicit server filters,
fail-fast and partial-error behavior, local response caps, ID deduplication,
query provenance, spaced-to-hyphenated and joined-word zero-result fallback stopping, raw/transformed Jellyfin item
conversion, and the complete
plan → retrieve → rank → confidence-decision path.

## Concrete Jellyfin client

`test_jellyfin_client.py` verifies the first concrete catalog client against the
API and coordinator contract used by the installed JellyHA integration. It
covers:

- direct construction and coordinator-based construction;
- current `entry.data['user_id']` and `config_entry` fallback shapes;
- exact translation to `get_library_items`;
- the special `/Artists/AlbumArtists` request used for `MusicArtist`;
- propagation of all current library-search filters;
- response validation and API error propagation;
- raw-item preservation without Home Assistant transformation; and
- a complete `three am` → `3AM` retrieval/ranking decision using a fake API.

The concrete client has no Home Assistant import. A later action-registration
layer will obtain the coordinator, construct this client, execute the already
tested retrieval pipeline, and transform only the final returned items.

## In-memory catalog index

`test_catalog_index.py` freezes the first catalog-backed search boundary. It
builds a metadata-only local index from raw or JellyHA-transformed items,
deduplicates IDs, precomputes deterministic variants/tokens/n-grams, and feeds a
bounded shortlist into the existing ranking and confidence engine.

The tests prove that `Bubba ho tep`, `runaround`, `three am`, controlled
typos, and complete-word partial queries such as `planet` can be resolved
without relying on Jellyfin `SearchTerm`. Partial title matches respect token
boundaries and return bounded ambiguous choices when several catalog titles
contain the query. Numeric ordinal
titles now expose safe word aliases, allowing `the thirteeth warrior` to match
`The 13th Warrior` as a one-edit fuzzy correction. A numeric-signature guard
prevents correctly spelled or explicit unequal numbers such as `30th` and
`13th` from becoming fuzzy equivalents.

## Paginated catalog loader

`test_catalog_loader.py` freezes the metadata-only snapshot boundary. It verifies
stable media-type groups, pagination, item caps, ID deduplication, missing-ID
diagnostics, regular-library and dedicated artist pages, and construction of a
local index that resolves `Bubba ho tep` without sending punctuation guesses to
Jellyfin.

The catalog index also indexes conservative catalog-derived artist aliases.
Same-name artist records are **not** merged by display name alone.  MusicArtist
records sharing the same trusted MusicBrainz artist ID are grouped as one
logical entity while retaining every physical Jellyfin ID; conflicting or
missing provider IDs remain separate and therefore ambiguous.

`test_items.py` verifies raw/transformed provider-ID normalization and freezes
the deliberately narrow MusicBrainz-artist grouping rule.

## Catalog manager and disk cache

`test_catalog_cache.py` and `test_catalog_manager.py` freeze the long-lived
catalog lifecycle needed by Home Assistant. They verify:

- a versioned metadata-only JSON cache that excludes credentials, media paths,
  overviews, and other unnecessary payload fields;
- atomic temporary-file plus `os.replace` writes;
- server/user identity and media-type validation;
- cache restoration without contacting Jellyfin;
- a reusable immutable in-memory index for repeated searches;
- coalesced concurrent refreshes;
- rejection of truncated snapshots;
- safe preservation of the previous index when Jellyfin or disk writes fail;
- provider-group and index diagnostics; and
- cache-load, refresh, index-build, cache-write, and search timing.

## Stable action response

`test_response.py` freezes the future `jellyfin_assist.search` action boundary.
The top-level `items` field preserves the current resolver cardinality contract:
one item for a confident match, ranked choices for ambiguity, and an empty list
for no match. Rich decision, score, context, catalog, variant, logical-entity,
and timing diagnostics are additive and JSON-safe.

## Audio response semantics

Action-response tests verify that spoken-equivalent audio titles remain
selection choices unless artist, album, or year context separates them. Audio
`ParentIndexNumber` and `IndexNumber` values are serialized as `disc_number`
and `track_number`; they no longer populate television `season_number`,
`season_name`, or `episode_number`. The legacy `index_number` field remains the
track index for compatibility.
