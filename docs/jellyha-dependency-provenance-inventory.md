# Step 42A — JellyHA dependency and provenance inventory

Status: **audit only; no runtime behavior changes**

Observed upstream: `zupancicmarko/JellyHA`, branch `main`, 2026-08-07.
The upstream manifest and the vendored reference both report version `1.2.0`.

## Executive result

The current implementation tracks **three upstream JellyHA capability
relationships**, but **none remains as a direct production script action**:

1. `jellyha.get_item` — retired runtime dependency; retained only in historical provenance/reference material
2. `jellyha.search` — retired runtime dependency; retained only in historical provenance/reference material
3. `jellyha.play_on_chromecast` — retired runtime dependency; retained only in historical provenance/reference material

Most other names beginning with `jellyha_` are our own historical names and are
**not** calls into the JellyHA integration. In particular, the queue service,
queue REST commands, orchestration scripts, and helper names are project-owned
legacy namespace debt rather than external dependencies.

The public `custom_components/jellyfin_assist/manifest.json` does not declare
JellyHA as a Home Assistant dependency. After Step 44B, canonical production scripts and the `jellyfin_assist` runtime contain no callable upstream JellyHA service path. Native item lookup, search, player resolution, and Chromecast playback are standalone. Household playback was proven with the JellyHA integration disabled. Rollback now means returning to a previous green repository commit, not keeping JellyHA installed as a runtime fallback.

## Dependency map

| Capability | Current callers | Current role | Contract we must preserve | Replacement order |
| --- | --- | --- | --- | ---: |
| `jellyha.get_item` | 0 runtime callers; historical provenance/reference only | Retired after native production proof | Input `item_id`; response mapping containing `item` with raw Jellyfin metadata | 1 (complete) |
| `jellyha.search` | 0 runtime callers; historical provenance/reference only | Retired after native search production and standalone proof | Optional query/type/filter fields; response `{items: [...]}` | 2 (complete) |
| `jellyha.play_on_chromecast` | 0 runtime callers; historical provenance/reference only | Retired after native playback parity and standalone proof | `entity_id` + `item_id`; successful call starts HA media playback | 3 (complete) |

The duplicate file under `tools/reference/current-working/...` mirrors the
canonical scripts and is not counted as a second production dependency surface.

## `get_item` provenance and contract

Upstream registration and transformation live primarily in:

- `custom_components/jellyha/services.py`
- `custom_components/jellyha/api.py`

The service requires `item_id`, resolves the JellyHA coordinator/user, retrieves
`/Users/{user_id}/Items/{item_id}`, enriches media-stream and user-data fields,
and returns `{"item": item}`.

Our current callers rely on fields including `Id`, `Name`, `Type`, `SeriesName`,
`SeriesId`, `ParentIndexNumber`, `IndexNumber`, `ProductionYear`, `Overview`,
ratings, and media metadata. The replacement must preserve the **response
contract**, not necessarily JellyHA's internal implementation.

This is the safest first extraction target because Jellyfin Media Assistant
already has a read-only native Jellyfin API client and this capability is a
single-item GET.

## `search` provenance and contract

Upstream registration is in `custom_components/jellyha/services.py`, with
Jellyfin requests in `api.py` and result transformation through the coordinator.
The current upstream service supports Movie, Series, Episode, Audio,
MusicAlbum, MusicArtist, MusicVideo, Video, Playlist, and BoxSet plus filtering
fields.

As of Step 42D, the household resolver uses `jellyfin_assist.search` for every
production request supported by the public resolver contract. The legacy
`input_boolean.jellyfin_assist_robust_search` branch, direct `jellyha.search`
actions, substring-only legacy result filtering, and JellyHA-only episode-title
shortcut are retired.

Step 44B retires the read-only `jellyfin_assist.compare_search` migration diagnostic and removes its shadow runtime adapter. `jellyha.search` is no longer reachable from the integration runtime.

## `play_on_chromecast` provenance and contract

Upstream implementation spans:

- `custom_components/jellyha/services.py`
- `custom_components/jellyha/api.py`
- `custom_components/jellyha/media_strategy.py`

The service fetches the Jellyfin item, resolves Series/Season to an episode when
needed, analyzes codec/container metadata, detects Chromecast model information,
builds a direct-play or transcoding URL, and ultimately calls Home Assistant's
`media_player.play_media` action with metadata.

The upstream media strategy currently imports `pychromecast` for model
discovery. JellyHA's manifest lists `pychromecast` as a requirement. This makes
Chromecast playback the highest-risk extraction and it should remain last.
Because Chromecast is our officially supported playback platform, replacement
parity must be demonstrated with automated contract tests and live Chromecast
smoke tests before the external dependency is removed.

Step 43B registered a parallel `jellyfin_assist.play_on_chromecast` action that performs item lookup, Next Up resolution, strategy selection, and the `media_player.play_media` handoff without calling JellyHA. Live household parity then passed for a Movie, a direct Episode, Audio, and Series → Next Up → Episode on the supported Chromecast path. Step 43C switched production. Step 44B records the additional full Assist movie/audio tests performed with JellyHA disabled; playback rollback is now repository history rather than a live JellyHA service path.

## Provenance status

The repository contains a vendored JellyHA integration snapshot at:

`reference/current-working/jellyha/`

Its manifest reports version `1.2.0`, matching the upstream version observed on
2026-08-07. The original copy, however, did **not record the exact upstream
commit SHA**. Version equality is not enough to prove byte-for-byte provenance.
Therefore:

- the vendored snapshot remains reference-only;
- Step 42A did not move any JellyHA implementation into `jellyfin_assist`;
- Step 42B separately pins the get-item adaptation source to JellyHA commit
  `6b8b2f679f922ea3a0d9c3c4b9827ee7053308f9`;
- the missing historical SHA for the older vendored snapshot remains documented
  rather than guessed;
- new code should preferably implement our required contract against Jellyfin's
  API, reusing upstream implementation only where that is materially safer or
  more correct.

## License and attribution

JellyHA is MIT licensed and the upstream license states:

`Copyright (c) 2026 zupancicmarko`

MIT permits use, modification, merging, publication, distribution,
sublicensing, and sale, provided the copyright and permission notice are
included in copies or substantial portions of the software.

The repository previously carried a substantial vendored JellyHA source tree
without the upstream root license beside it. Step 42A adds the upstream MIT
license to the vendored reference and adds `THIRD_PARTY_NOTICES.md` so the
reference source is properly attributed before public release work continues.

This is project engineering guidance, not legal advice.

## What is *not* a JellyHA dependency

The following are ours despite their legacy names:

- the former `jellyha-queue` queue microservice/container (project-owned and retired in Step 46A);
- `rest_command.jellyha_queue_*` calls;
- custom `script.jellyha_*` scripts;
- project helpers using `jellyha_` prefixes;
- robust search and `jellyfin_assist.search`;
- native Home Assistant pause/resume/media-player control.

These are project-owned namespace debt, not upstream dependencies. Step 45B begins
the staged cleanup by moving active script implementations and all current script
routing to `jellyfin_assist_*` IDs while retaining the former script IDs as temporary
compatibility wrappers. Those compatibility surfaces were subsequently retired during the native
onboarding migration; Step 46A also removes the external queue container entirely.

## Safe extraction sequence

1. **Native `get_item` parity, production switch, and fallback retirement** — completed through Step
   44A. `jellyfin_assist.get_item` is the sole runtime item lookup path; the temporary
   JellyHA fallback and `compare_get_item` migration diagnostic are retired.
2. **Retire residual `jellyha.search` dependence** — completed through Step 44B. Production routing was native-only in Step 42D; Step 44B removes the optional shadow comparator and its JellyHA service path.
3. **Native Chromecast playback** — completed through Step 43C and standalone-verified before Step 44B.
4. All three upstream JellyHA capabilities are now runtime-retired and rollback-tested. JellyHA is not a public installation requirement and may be uninstalled after the standalone smoke test. Legacy `jellyha_*` names owned by this project remain separate namespace-cleanup debt and can continue temporarily through compatibility aliases.

## Step 42A completion criteria

- Every real JellyHA service call is classified.
- Project-owned `jellyha_*` names are explicitly separated from upstream calls.
- Upstream source files and contracts are recorded.
- MIT provenance is recorded and the vendored reference carries the license.
- The missing historical commit SHA is documented rather than guessed.
- Automated release tests fail if a new untracked `jellyha.*` production action
  appears.
- No runtime behavior changes.
