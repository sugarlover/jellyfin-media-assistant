# Voice & Assist Command Guide

Jellyfin Media Assistant adds English Home Assistant Assist sentences for Jellyfin search, playback, selection, and queue management.

The examples below use arbitrary media titles and room/player names. Replace them with titles that exist in your Jellyfin library and the friendly names or aliases of your own Home Assistant media players.

## Recommended phrasing

Explicit media-type wording is the most predictable when different library items share similar names.

### Movies

```text
Play the movie The Martian on the living room TV
Watch the film Arrival on the den TV
Add the movie Moon to the living room TV
```

### Songs

```text
Play the song Dreams by Fleetwood Mac on the bedroom speaker
Play the song Take On Me by a-ha
Queue the song Fast Car by Tracy Chapman on the kitchen speaker
```

The `by <artist>` suffix is optional, but it is useful when multiple songs share a title.

### Albums

```text
Play the album Discovery by Daft Punk on the office speaker
Play the album Blue by Joni Mitchell
Add the album Kind of Blue by Miles Davis to the living room speaker
```

Playing an album expands its Jellyfin tracks into the player queue.

### Artists

```text
Play music by Norah Jones on the kitchen speaker
Play the artist Radiohead on the living room speaker
Queue songs by The Killers on the den speaker
```

Artist requests expand the available Jellyfin tracks for the matched artist into the queue.

### TV shows and seasons

```text
Play the show Parks and Recreation on the living room TV
Play season 3 of the show Parks and Recreation on the living room TV
Queue season 2 of the series Frasier on the bedroom TV
```

When a show is requested without a season, the current beta queues **Season 1**. Use an explicit season when you want another season.

### Season and episode number

These forms are supported:

```text
Play season 2 episode 5 of the show Frasier on the bedroom TV
Play episode 5 of season 2 of the show Frasier on the bedroom TV
Play the show Frasier season 2 episode 5 on the bedroom TV
```

A reliable general form is:

```text
Play season <season> episode <episode> of the show <series> on <player>
```

### Episode title

```text
Play the episode Dinner Party from The Office on the living room TV
Play the episode The Constant from Lost on the den TV
Queue the episode Pine Barrens from The Sopranos on the bedroom TV
```

Including `from <series>` helps disambiguate episode titles.

## Generic media requests

Jellyfin Media Assistant also supports generic forms such as:

```text
Play Apollo 13 on the living room TV
Start Casablanca
Queue The Bear on the den TV
```

When a title could describe several media types, explicit wording such as `movie`, `song`, `album`, `artist`, `show`, or `episode` is safer.

## Adding instead of replacing

`Play`, `watch`, `put on`, and `start` begin a new playback session. A new Play request resets the old queue's repeat modes.

`Add` and `queue` append to the existing queue:

```text
Queue the movie Gravity on the living room TV
Add the album Aja by Steely Dan to the office speaker
Queue season 1 of the show Severance on the den TV
```

## Multiple search matches

If Jellyfin Media Assistant finds several plausible matches, Assist lists numbered choices.

Supported follow-ups include:

```text
2
Number 2
Play number 2
Select number 2
The 2 one
```

Selections are temporary runtime state. If Home Assistant or the integration restarts before you answer, make the original request again.

## Missing-player follow-up

If no player was spoken and no usable default is configured, Jellyfin Media Assistant preserves the media request and asks for a player.

Use an explicit continuation phrase such as:

```text
Use the living room TV
Choose the bedroom speaker
Play it on the den TV
Continue on the kitchen speaker
```

Bare player phrases are intentionally not registered because they can interfere with Home Assistant's native media-player commands.

## Queue commands

Most queue commands can use the configured default player when a player is omitted.

### Next

```text
Next on the living room TV
Next song on the office speaker
Skip to the next item on the den TV
Advance the queue
```

### What's playing

```text
What's playing on the living room TV
What is currently playing
```

### What just played

```text
What just played on the office speaker
What played last
```

### Queue status

```text
Queue status on the living room TV
What's in the queue on the den TV
How many items are in the queue
```

### Shuffle

```text
Shuffle the queue on the office speaker
Randomize the upcoming items
```

### Clear queue

Clearing is intentionally stricter because it is destructive. A player must be named:

```text
Clear the queue on the living room TV
Empty the den TV queue
```

### Repeat current item

```text
Repeat this song on the office speaker
Repeat the current episode on the living room TV
Turn on repeat item
```

### Repeat whole queue

```text
Repeat the queue on the office speaker
Loop the queue on the living room TV
Turn on queue repeat
```

### Turn repeat off

```text
Turn repeat off on the office speaker
Disable repeat
Stop repeating
```

Toggle forms such as `toggle repeat item` and `toggle repeat queue` are also registered, although the explicit enable/off forms are usually clearer in voice use.

## Native Home Assistant player controls

Jellyfin Media Assistant does **not** replace Home Assistant's normal media-player intents. Use Home Assistant's native controls for actions such as pause, resume, stop, volume, mute, and power.

## Current grammar limitations

The custom sentence grammar is deliberately conservative. A phrase that seems natural may not yet match every equivalent word order.

In particular, if a season/episode request is not recognized, use the canonical form:

```text
Play season <season> episode <episode> of the show <series> on <player>
```

See [Known Limitations](known-limitations.md) for other current beta boundaries.
