# Flexible title + context matching

This step changes artist and series inputs from brittle exact filters into
independent, scored matching signals.

## Supported combinations

The catalog-backed matcher now supports:

- exact or normalized title + incomplete artist/series;
- partial whole-token title + incomplete artist/series;
- controlled title typo + controlled artist/series typo;
- incomplete context that also contains a controlled typo, such as
  `Dave Mathews` for `Dave Matthews Band`;
- episode-title matching with incomplete or misspelled parent-series context.

Examples expected to resolve when the catalog has a clear winner:

- `Crash Into Me` by `Dave Matthews`;
- `Crash` by `Dave Matthews Band`;
- `Crash` by `Dave Matthews`;
- `Crsh Into Me` by `Dave Mathews`;
- `Everybody` from `Twilight Zone`;
- `Where Is Everybdy?` from `The Twlight Zone`.

## Safety rules

Context cannot create a candidate. The title matcher must first find the song or
episode through deterministic equivalence, safe whole-token fragments,
controlled fuzzy matching, or the existing conservative phonetic tier.

Artist, album, and series matching then uses this order:

1. deterministic equivalence;
2. contiguous whole-token fragment matching in either direction;
3. controlled full-field fuzzy matching;
4. controlled fuzzy matching against same-width contiguous token windows.

Unrelated context remains a contradiction. For example, `Crash` by `Coldplay`
does not silently select `Crash Into Me` by Dave Matthews Band. Multiple
plausible candidates still require the existing ambiguity margin and selection
flow.

## Home Assistant routing

As of Step 42D, production resolver searches always use the catalog-backed
`jellyfin_assist.search` action:

- resolver results are trusted as the output of the scored matcher and are not
  re-filtered by the old substring-only Jinja filter;
- Episode title + series requests use the catalog-backed Episode matcher; and
- the old `jellyha.search` rollback branch and episode-title shortcut are no
  longer part of production routing.

The former `input_boolean.jellyfin_assist_robust_search` helper is retired and
may remain harmlessly on existing household systems until later helper cleanup.
