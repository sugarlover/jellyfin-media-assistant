"""Deterministic >=10,000-item synthetic search fixture (D9).

Read-only scope grounding: the REAL catalog (``/workspace/_JMA_CATALOG.json``)
is used to ground the *scope* of what a deployed index must handle (media-type
set, item shapes), never as a test fixture.  This module independently extends
the tiny existing fixtures into a large, deterministic catalog that exercises
the phonetic-shortlisting branches the small fixtures cannot:

* D6 overflow  -- a phonetic-eligible pool larger than the 200-cap;
* D4 displacement -- deterministic/token-anchor/ngram evidence must never be
  displaced by a phonetic-only record;
* D5 dedup -- one record = one entry with unioned methods;
* exact matches, competing titles, and unrelated phonetic collisions spanning
  every media type present in the real catalog (Audio, Episode, Movie,
  MusicAlbum, MusicArtist, Series).

Determinism: every item is generated from a fixed seed and a fixed word list,
so the fixture is byte-stable across runs and environments.  No real catalog
title is copied in; every title here is synthetic.
"""

from __future__ import annotations

from typing import Any

# The real catalog's supported media type set (grounded from
# /workspace/_JMA_CATALOG.json): "Audio", "Episode", "Movie", "MusicAlbum",
# "MusicArtist", "Series".
MEDIA_TYPES = ("Audio", "Episode", "Movie", "MusicAlbum", "MusicArtist", "Series")

# The headline target under test (a real-world ASR homophone that the plan
# exists to recover).  Synthetic, matching the deployed title shape.
TARGET_TITLE = "Your Idol"

# A pool of homophone titles of the target (idle/idol share the /aɪdl/ sound;
# "Your Idle" is a true COMMON_HOMOPHONE, 74) used to drive D6 overflow.
OVERFLOW_TITLE = "Your Idle"
OVERFLOW_COUNT = 250  # strictly above the production 200 shortlist cap

# A Soundex-only (TOKEN_SIGNATURE, 70) sound-alike of the target that is NOT a
# homophone, used to exercise the 74-before-70 precedence clause (D6).
SEVEN_SCORE_TITLE = "Yure Idel"

# Competing titles: lexical near-misses of the target that must NOT be
# auto-selected over the genuine phonetic match and that must not displace the
# deterministic target.  They carry real anchor tokens so they occupy the
# token-anchor pool.
COMPETING_TITLES = (
    "Your Idols",
    "Your Idol Live",
    "Your Idol (Live)",
    "Idol",
    "Idols",
)

_FILLER_STEMS = (
    "Bright",
    "Covena",
    "Delora",
    "Everis",
    "Falconet",
    "Galoria",
    "Hallmark",
    "Inverton",
    "Junivale",
    "Kepler",
    "Luminar",
    "Montreal",
    "Norhaven",
    "Ostmark",
    "Pelorian",
    "Quistral",
    "Ravelton",
    "Solenne",
    "Tarnish",
    "Umbrella",
    "Vantura",
    "Wexford",
    "Xanthe",
    "Yarrow",
    "Zenith",
)

_FILLER_SUFFIXES = (
    "Album",
    "Mix",
    "Remix",
    "Session",
    "Tour",
    "EP",
    "Single",
    "Version",
    "Demo",
    "Live",
)


def _synthetic_id(index: int) -> str:
    return f"syn-{index:06d}"


def _filler_items(offset: int) -> list[dict[str, Any]]:
    """Generate the bulk filler catalog spanning every media type.

    Titles are stem + suffix combinations that produce distinct Soundex
    signatures, so no filler title is a homophone of the target or its
    overflow pool.  Deterministic: ``offset`` is a fixed stride so the same
    list is produced on every run.
    """

    items: list[dict[str, Any]] = []
    for block in range(len(MEDIA_TYPES)):
        media_type = MEDIA_TYPES[block]
        stem = _FILLER_STEMS[block % len(_FILLER_STEMS)]
        for suffix_index, suffix in enumerate(_FILLER_SUFFIXES):
            index = offset + block * len(_FILLER_SUFFIXES)
            name = f"{stem} {suffix} {suffix_index + 1}"
            items.append(
                {
                    "Id": _synthetic_id(index),
                    "Name": name,
                    "Type": media_type,
                    "Artists": [stem],
                    "ProductionYear": 2000 + (index % 20),
                }
            )
    return items


def build_synthetic_catalog(total: int = 10_000) -> list[dict[str, Any]]:
    """Build a deterministic synthetic catalog of at least ``total`` items.

    Layout:

    * item 0 -- the headline target ``Your Idol`` (Audio);
    * items 1..OVERFLOW_COUNT -- the homophone overflow pool ``Your Idle``;
    * one ``SEVEN_SCORE_TITLE`` (Soundex 70) sound-alike;
    * one of each competing title;
    * the remainder -- filler items spanning every supported media type.

    Returns a plain list of raw Jellyfin-shaped item mappings, suitable for
    ``CatalogIndex.build``.  The list is >= ``total`` items and covers all six
    supported media types.
    """

    items: list[dict[str, Any]] = []
    items.append({"Id": "syn-target", "Name": TARGET_TITLE, "Type": "Audio"})
    for position in range(OVERFLOW_COUNT):
        items.append(
            {
                "Id": f"syn-overflow-{position:04d}",
                "Name": OVERFLOW_TITLE,
                "Type": "Audio",
                "Artists": [f"Overflow Artist {position}"],
            }
        )
    items.append({"Id": "syn-70", "Name": SEVEN_SCORE_TITLE, "Type": "Audio"})
    for position, title in enumerate(COMPETING_TITLES):
        items.append({"Id": f"syn-compete-{position}", "Name": title, "Type": "Audio"})

    filler_start = len(items)
    filler_needed = max(total - len(items), len(MEDIA_TYPES))
    for block in range((filler_needed + len(MEDIA_TYPES) - 1) // len(MEDIA_TYPES)):
        for suffix_index, suffix in enumerate(_FILLER_SUFFIXES):
            index = filler_start + block * len(_FILLER_SUFFIXES) + suffix_index
            # stop once we reach the requested total
            if index >= filler_start + filler_needed:
                break
            media_type = MEDIA_TYPES[block % len(MEDIA_TYPES)]
            stem = _FILLER_STEMS[block % len(_FILLER_STEMS)]
            items.append(
                {
                    "Id": _synthetic_id(index),
                    "Name": f"{stem} {suffix} {block}",
                    "Type": media_type,
                    "Artists": [stem],
                    "ProductionYear": 2000 + (index % 20),
                }
            )
    return items


__all__ = [
    "COMPETING_TITLES",
    "MEDIA_TYPES",
    "OVERFLOW_COUNT",
    "OVERFLOW_TITLE",
    "SEVEN_SCORE_TITLE",
    "TARGET_TITLE",
    "build_synthetic_catalog",
]
