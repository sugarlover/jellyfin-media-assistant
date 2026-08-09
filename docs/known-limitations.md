# Known Limitations

This document describes intentional first-beta boundaries rather than an exhaustive bug list.

## Playback platform support

Chromecast is the tested and supported playback target for the first beta.

Other Home Assistant `media_player` platforms are experimental. They may be selectable, but the native playback strategy and live validation have focused on Chromecast. Platform-specific contributions should preserve the existing Chromecast path.

## English Assist sentences only

The integration currently packages and manages an English custom sentence file. Other languages are not yet included.

## Conservative voice grammar

The sentence grammar favors predictable routing over accepting every possible word order. If a TV season/episode phrase is not recognized, prefer:

```text
Play season <season> episode <episode> of the show <series> on <player>
```

See [Voice & Assist Command Guide](voice-commands.md) for canonical forms.

## Ambiguous search choices are capped

The voice selection response currently presents at most five plausible matches even if the search catalog contains more candidates. Candidates with identical match scores retain stable catalog/index ordering rather than being automatically sorted by recency or popularity.

A future improvement may add refinement or `show more`/pagination instead of silently preferring newer titles.

## `St.` is not globally expanded

The matcher intentionally does not treat every `St.` as equivalent to both `Saint` and `Street`.

A future contextual alias feature can use catalog evidence and surrounding text to distinguish names such as `Rebecca St. James` from titles where `St.` means `Street`. Global replacement would create avoidable false matches.

## No public queue-remove command

The native queue store has internal position-removal capability, but the first beta does not expose a `queue_remove` Home Assistant action or Assist command.

## Temporary conversational state is not persistent

Pending numbered search selections and pending-player follow-ups are in-memory conversation state. They are cleared by an integration or Home Assistant restart.

Persistent playback queues are separate and do survive restarts.

## Queue status and "what's playing next"

Queue status reports the current queue state, but a dedicated conversational `What's playing next on <player>?` response is not part of the first beta.

## Continue-where-I-left-off

Per-user resume/recent-history commands are not part of the first beta. A future implementation should prefer Jellyfin's native per-user playback state where practical.

## Native Home Assistant media controls remain separate

Pause, resume, stop, power, volume, and mute are intentionally left to Home Assistant's native media-player intents. Jellyfin Media Assistant does not register broad wildcard phrases that would intercept those commands.
