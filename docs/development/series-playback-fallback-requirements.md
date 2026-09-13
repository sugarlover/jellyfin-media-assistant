# Generic Series Playback Fallback Requirements

Status: FROZEN for implementation
Feature: Generic TV-series playback selection
Base commit: e43d808a9c82f2bc9ff5b47961c7e76cf72e1400

## Purpose

Define deterministic episode selection when Jellyfin Media Assistant receives a
request to play or queue a TV series.

This feature changes episode selection only. Existing title matching,
confirmation, player resolution, Play/Add queue semantics, playback,
advancement, and watched-state behavior remain unchanged unless explicitly
stated below.

## Definitions

### Generic series request

A request that resolves to a Series but does not explicitly request a season or
episode.

Examples:

- Play the series Supernatural
- Play Supernatural
- Queue Supernatural

### Explicit season request

A request that explicitly identifies a season.

Example:

- Play season 3 of Supernatural

### Regular episode

An available Jellyfin Episode whose season number is greater than zero.

Season 0 / Specials are excluded from generic-series selection.

### Available episode

An episode actually returned by Jellyfin for the configured user and library.
JMA does not attempt to infer whether a season is objectively complete.

## Generic series selection

For a generic series request:

1. Retrieve available regular episodes for the resolved series.
2. Order them by season number ascending, then episode number ascending.
3. Exclude Season 0 / Specials.
4. Determine the available Season 1 episodes.

### Season 1 has 15 or more available episodes

Queue all available Season 1 episodes.

Do not append episodes from later seasons.

Examples:

- Season 1 has 15 episodes -> queue 15.
- Season 1 has 16 episodes -> queue all 16.
- Season 1 has 22 episodes -> queue all 22.

### Season 1 has between 1 and 14 available episodes

Queue every available Season 1 episode.

Then append the earliest available regular episodes from later seasons in
chronological order until:

- the queue contains 15 episodes; or
- the series has no additional regular episodes.

Missing episode numbers do not cause failure. Queue the available episodes in
order and skip unavailable numbers.

### No Season 1 episodes are available

Queue the first 15 available regular episodes for the series in chronological
order.

If fewer than 15 regular episodes exist, queue all available regular episodes.

Season 0 / Specials do not count toward the 15-episode target.

### No regular episodes exist

Return a truthful no-playable-episodes failure.

Do not create a misleading queue and do not start playback.

## Explicit season selection

An explicit season request remains strictly season-bounded.

Queue all available episodes from the explicitly requested season and no
episodes from another season.

There is no 15-episode minimum or top-up behavior for explicit season requests.

Examples:

- Requested season contains 22 episodes -> queue all 22.
- Requested season contains 6 episodes -> queue all 6.
- Requested season contains 1 episode -> queue that one episode only.

Existing behavior for an unavailable explicitly requested season remains
unchanged.

This feature does not add or redefine explicit Season 0 request support.

## Ordering and uniqueness

Selection MUST be deterministic.

Regular episodes are ordered by:

1. season number ascending;
2. episode number ascending.

Unavailable episode numbers are skipped.

An episode MUST NOT appear more than once in the resulting playback plan.

## Existing behavior that must remain unchanged

This feature MUST NOT change:

- Series/title matching or ambiguity handling.
- Phonetic/fuzzy confirmation behavior.
- Player resolution.
- Play semantics: start a fresh playback session using the resulting plan.
- Add / Queue semantics: append the resulting plan according to existing behavior.
- Queue persistence.
- Repeat behavior.
- Automatic advancement.
- Low-level Chromecast playback.
- Watched/unwatched handling.

Watched state is explicitly out of scope. A future feature may add commands such
as "Resume Supernatural" using watched/progress information.

## User-facing responses

Responses must accurately describe the resulting selection.

A generic-series request MUST NOT claim that Season 1 was selected when
playback actually begins in a later season.

Exact prose is not part of this contract; correctness and clarity are.

## Required behavioral regression scenarios

Automated tests must mechanically prove at minimum:

1. Generic series, Season 1 has more than 15 episodes:
   all Season 1 episodes and no Season 2 episodes.
2. Generic series, short/partial Season 1:
   all Season 1 episodes plus enough later episodes to reach 15.
3. Generic series, short Season 1 and fewer than 15 episodes in the entire
   series: all available regular episodes.
4. Generic series, no Season 1:
   first 15 regular episodes in chronological order.
5. Generic series, no Season 1 and fewer than 15 total:
   all available regular episodes.
6. Season 0 / Specials are excluded from generic selection.
7. Missing episode numbers are safely skipped while preserving order.
8. Explicit season remains bounded to that season even when it contains fewer
   than 15 episodes.
9. Explicit season containing one episode produces a one-item playback plan.
10. No regular episodes produces a clean failure rather than an invalid
    playback plan.

Higher-level tests must also prove existing Play/Add behavior still consumes
the selected playback plan correctly.

## Architecture constraints

Follow the existing JMA ownership boundaries:

- orchestration decides what to play;
- service/API code retrieves Jellyfin data;
- media_actions coordinates queue/session behavior;
- playback remains responsible for a concrete playable item;
- do not reintroduce YAML-script orchestration, external queue services, or
  JellyHA runtime dependencies.

Prefer existing JellyfinApiClient and service/query machinery over duplicated
HTTP code.
