# Developer tools

## Read-only live Jellyfin search

`python -m tools.live_search` runs the isolated search engine directly against a
real Jellyfin catalog. The included HTTP client blocks every method except GET.
It cannot start playback, modify metadata, change watched state, or touch the
queue.

Create an ignored `.env` from `.env.example`.

### Literal Jellyfin SearchTerm validation

The original mode exercises Jellyfin's server-side title search and the local
ranking pipeline:

```powershell
python -m tools.live_search "three am" --media-type Audio
```

### Local catalog-index validation

Use `--catalog` to download only metadata in paginated GET requests, build the
in-memory index, and match locally without relying on Jellyfin `SearchTerm`:

```powershell
python -m tools.live_search "Bubba ho tep" --media-type Movie --catalog
```

When `--media-type` is supplied, only that Jellyfin type is loaded. Without a
media type, the tool loads Movie, Series, Episode, Audio, MusicAlbum, and
MusicArtist metadata. The default page size is 500 and can be changed with
`--catalog-page-size`. `--catalog-max-items` provides an optional safety cap;
zero means no cap.

Optional context:

```powershell
python -m tools.live_search "one" --media-type Audio --artist Metallica --catalog
python -m tools.live_search "the thirteenth warrior" --media-type Movie --year 1999 --catalog
```


For grouped duplicate artists, the report displays the trusted provider ID and
every physical Jellyfin artist ID retained by the logical result. Grouping is
currently limited to MusicArtist records sharing a MusicBrainz artist ID; names
alone are never enough.

Use `--json` for machine-readable diagnostics. Never commit `.env`.

### Catalog cache and refresh behavior

Local catalog mode now uses an ignored metadata cache under
`.cache/jellyfin-assist`. The first search for a media-type set downloads and
indexes metadata, writes the cache atomically, and reports `source=refresh`.
Later command invocations restore the cache and report `source=cache` without
contacting Jellyfin for catalog pages.

Force an explicit refresh after library changes:

```powershell
python -m tools.live_search "runaround" --media-type Audio --catalog --refresh-catalog
```

Disable caching for one diagnostic run:

```powershell
python -m tools.live_search "runaround" --media-type Audio --catalog --no-catalog-cache
```

Capped diagnostic snapshots created with `--catalog-max-items` are never written
to the normal cache, preventing a partial catalog from masquerading as a full
one.

The command-line process still rebuilds the in-memory index from the disk cache
on each invocation. The Home Assistant integration will keep one manager and
index alive, so repeated searches will use only the fast local search path.
