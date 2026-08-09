# Common queue Audio normalization

The queue adapter treats Jellyfin `IndexNumber` as an episode number only for
`Episode` items. `Audio` items always send empty `season` and `episode` values
to the queue while preserving disc and track metadata on the playback item.

This common boundary protects direct song, pending song, album, and artist
playback plans without requiring each resolver path to duplicate the same fix.
