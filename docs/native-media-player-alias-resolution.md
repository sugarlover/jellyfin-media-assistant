# Native media-player aliases and safe player recovery

This step makes media-player resolution generic for HACS users. The integration does not ship aliases for any specific room or device.

## Source of aliases

Jellyfin Media Assistant reads the current Home Assistant entity name and the ordered aliases stored in the entity registry. Users manage those aliases from the normal Home Assistant entity settings. An alias such as `Movie Screen` therefore remains local to that Home Assistant installation and is also available to other Assist features.

## Playback-target allowlist

The integration options screen now contains:

- **Default media player** — used only when no player was supplied.
- **Playback targets** — optional allowlist of players Jellyfin Media Assistant may select.

When playback targets are configured, the default must be included in that list. Conservative typo matching is enabled only inside this bounded list. With no allowlist, exact names, native aliases, normalized punctuation, and explicit entity IDs still work, but broad fuzzy matching is disabled.

## Matching order

1. Explicit `media_player.*` entity ID.
2. Exact normalized Home Assistant name or alias.
3. Exact compact form, which treats punctuation, spacing, `TV`, `T V`, and `T. V.` as equivalent.
4. Conservative whole-token subset inside a configured target list.
5. Conservative fuzzy alias match inside a configured target list, requiring a unique winner and a safe margin.
6. Ambiguous or missing match: ask the user instead of silently using the default.

A supplied but unrecognized player never falls back to the configured default.

## Trailing-player recovery

Home Assistant's wildcard title slot can consume the trailing player phrase. The player resolver therefore examines the media request fields for a final `on`, `to`, or `for` phrase. It checks artist, album, series, and title fields in that order.

Example:

```text
song query: Crash Into Me
artist context: Dave Matthews Band on Movie.T v
```

becomes:

```text
song query: Crash Into Me
artist context: Dave Matthews Band
media player: media_player.example_chromecast
```

The suffix is stripped only when it resolves safely or is clearly player-like and a player follow-up is required. A title such as `Room on Fire` is not shortened merely because a `Fire TV` entity exists.

## Player follow-up

An exact native Home Assistant player name or alias can be spoken alone after the prompt. Free-text and typo recovery are also available with bounded phrases such as:

```text
use secndary tv
play it on secndary tv
```

A bare phrase ending in `TV`, `television`, or `speaker` also reaches the fuzzy resolver while avoiding an unrestricted wildcard that could steal unrelated Assist commands.

## Diagnostics

Player responses and downloaded diagnostics include:

- original player text
- matched entity ID
- matched Home Assistant name and alias
- match method and confidence
- ambiguity candidates
- whether trailing recovery or the configured default was used

No user-specific aliases are included in the integration source.
