"""Tests for the read-only in-memory Jellyfin catalog index."""

from __future__ import annotations

import pytest

from custom_components.jellyfin_assist.matching.context import MediaSearchContext
from custom_components.jellyfin_assist.matching.decision import MatchDecisionStatus
from custom_components.jellyfin_assist.matching.deterministic import (
    DeterministicMatchMethod,
)
from custom_components.jellyfin_assist.matching.fuzzy import FuzzyMatchMethod
from custom_components.jellyfin_assist.search.catalog_index import (
    CatalogIndex,
    CatalogIndexIssueReason,
    CatalogShortlistMethod,
)


def _item(
    item_id: str,
    name: str,
    media_type: str,
    *,
    artist: str | None = None,
    album: str | None = None,
    year: int | None = None,
    provider_ids: dict[str, str] | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "Id": item_id,
        "Name": name,
        "Type": media_type,
    }
    if artist is not None:
        item["Artists"] = [artist]
    if album is not None:
        item["Album"] = album
    if year is not None:
        item["ProductionYear"] = year
    if provider_ids is not None:
        item["ProviderIds"] = provider_ids
    return item


def test_build_accepts_raw_and_transformed_item_shapes() -> None:
    index = CatalogIndex.build(
        [
            _item("movie-1", "Bubba Ho-tep", "Movie", year=2002),
            {
                "id": "song-1",
                "name": "3 AM",
                "type": "Audio",
                "artist_name": "Matchbox Twenty",
                "album": "Yourself Or Someone Like You",
                "year": 1996,
            },
        ]
    )

    assert index.raw_item_count == 2
    assert len(index.records) == 2
    assert index.issues == ()
    assert index.get("song-1").candidate.artist == "Matchbox Twenty"


def test_build_reports_invalid_missing_and_duplicate_items() -> None:
    index = CatalogIndex.build(
        [
            "not-a-mapping",  # type: ignore[list-item]
            {"Name": "No ID", "Type": "Movie"},
            {"Id": "missing-title", "Type": "Movie"},
            _item("kept", "First Copy", "Movie"),
            _item("kept", "Second Copy", "Movie"),
        ]
    )

    assert [issue.reason for issue in index.issues] == [
        CatalogIndexIssueReason.INVALID_ITEM,
        CatalogIndexIssueReason.MISSING_ID,
        CatalogIndexIssueReason.MISSING_TITLE,
        CatalogIndexIssueReason.DUPLICATE_ID,
    ]
    assert index.get("kept").candidate.title == "First Copy"


def test_local_catalog_resolves_bubba_without_hyphenated_server_guess() -> None:
    index = CatalogIndex.build([_item("bubba", "Bubba Ho-tep", "Movie", year=2002)])

    outcome = index.search(
        "Bubba ho tep",
        context=MediaSearchContext(media_type="Movie"),
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_record.item_id == "bubba"
    assert outcome.decision.selected.title_match.method is DeterministicMatchMethod.PUNCTUATION_SPACING
    assert outcome.shortlist[0].methods == (
        CatalogShortlistMethod.DETERMINISTIC_VARIANT,
    )


def test_local_catalog_resolves_joined_word_without_server_fallback() -> None:
    index = CatalogIndex.build([_item("run", "Run-Around", "Audio")])

    outcome = index.search(
        "runaround",
        context=MediaSearchContext(media_type="Audio"),
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_record.item_id == "run"
    assert outcome.decision.selected.title_match.method is DeterministicMatchMethod.COMPACT_SPACING


def test_local_catalog_resolves_number_words_without_server_fallback() -> None:
    index = CatalogIndex.build([_item("3am", "3 AM", "Audio")])

    outcome = index.search(
        "three am",
        context=MediaSearchContext(media_type="Audio"),
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_record.item_id == "3am"
    assert outcome.decision.selected.title_match.method is DeterministicMatchMethod.NUMBER_EQUIVALENT


def test_token_anchor_shortlists_and_fuzzy_matches_buba_typo() -> None:
    index = CatalogIndex.build(
        [
            _item("bubba", "Bubba Ho-tep", "Movie"),
            _item("other", "Babe", "Movie"),
        ]
    )

    outcome = index.search(
        "Buba ho tep",
        context=MediaSearchContext(media_type="Movie"),
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_record.item_id == "bubba"
    assert outcome.decision.selected.title_match.method is FuzzyMatchMethod.SINGLE_EDIT
    assert CatalogShortlistMethod.TOKEN_ANCHOR in outcome.shortlist[0].methods


def test_character_ngrams_find_single_token_transposition() -> None:
    index = CatalogIndex.build(
        [
            _item("matrix", "Matrix", "Movie"),
            _item("heat", "Heat", "Movie"),
            _item("arrival", "Arrival", "Movie"),
        ]
    )

    outcome = index.search(
        "matirx",
        context=MediaSearchContext(media_type="Movie"),
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_record.item_id == "matrix"
    assert outcome.decision.selected.title_match.method is FuzzyMatchMethod.ADJACENT_TRANSPOSITION
    assert CatalogShortlistMethod.CHARACTER_NGRAM in outcome.shortlist[0].methods


def test_media_type_limits_shortlisting_before_ranking() -> None:
    index = CatalogIndex.build(
        [
            _item("movie", "One", "Movie"),
            _item("song", "One", "Audio", artist="Metallica"),
        ]
    )

    outcome = index.search(
        "One",
        context=MediaSearchContext(media_type="Audio"),
    )

    assert outcome.eligible_record_count == 1
    assert [entry.record.item_id for entry in outcome.shortlist] == ["song"]
    assert outcome.selected_record.item_id == "song"


def test_context_disambiguates_duplicate_song_titles() -> None:
    index = CatalogIndex.build(
        [
            _item("metallica", "One", "Audio", artist="Metallica"),
            _item("u2", "One", "Audio", artist="U2"),
        ]
    )

    ambiguous = index.search(
        "One",
        context=MediaSearchContext(media_type="Audio"),
    )
    resolved = index.search(
        "One",
        context=MediaSearchContext(media_type="Audio", artist="Metallica"),
    )

    assert ambiguous.decision.status is MatchDecisionStatus.AMBIGUOUS
    assert resolved.decision.status is MatchDecisionStatus.MATCHED
    assert resolved.selected_record.item_id == "metallica"


def test_unrelated_titles_are_not_promoted_by_shortlisting() -> None:
    index = CatalogIndex.build(
        [
            _item("runaway", "Runaway", "Audio"),
            _item("arrival", "Arrival", "Movie"),
        ]
    )

    outcome = index.search(
        "run around",
        context=MediaSearchContext(media_type="Audio"),
    )

    assert outcome.decision.status is MatchDecisionStatus.NOT_FOUND
    assert outcome.selected_record is None


def test_misspelled_ordinal_is_shortlisted_and_safely_selected() -> None:
    index = CatalogIndex.build([_item("warrior", "The 13th Warrior", "Movie")])

    outcome = index.search(
        "the thirteeth warrior",
        context=MediaSearchContext(media_type="Movie"),
    )

    assert [entry.record.item_id for entry in outcome.shortlist] == ["warrior"]
    assert CatalogShortlistMethod.TOKEN_ANCHOR in outcome.shortlist[0].methods
    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_record is not None
    assert outcome.selected_record.item_id == "warrior"
    assert outcome.decision.selected is not None
    assert outcome.decision.selected.title_match.method is FuzzyMatchMethod.SINGLE_EDIT
    assert outcome.decision.selected.title_match.fuzzy is not None
    assert outcome.decision.selected.title_match.fuzzy.candidate_value == "the thirteenth warrior"


def test_small_type_scan_is_bounded_and_cannot_create_a_match() -> None:
    index = CatalogIndex.build([_item("sea", "Sea", "Movie")])

    outcome = index.search(
        "pluto",
        context=MediaSearchContext(media_type="Movie"),
        small_type_scan_limit=1,
    )

    assert outcome.shortlist[0].methods == (CatalogShortlistMethod.SMALL_TYPE_SCAN,)
    assert outcome.decision.status is MatchDecisionStatus.NOT_FOUND


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("max_shortlist", 0),
        ("small_type_scan_limit", -1),
    ],
)
def test_search_rejects_invalid_limits(keyword: str, value: int) -> None:
    index = CatalogIndex.build([_item("one", "One", "Movie")])

    with pytest.raises(ValueError):
        index.search("One", **{keyword: value})


def test_stylized_artist_spoken_number_alias_matches_locally() -> None:
    index = CatalogIndex.build(
        [_item("blink", "blink-182", "MusicArtist")]
    )

    outcome = index.search(
        "blink one eighty two",
        context=MediaSearchContext(media_type="MusicArtist"),
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_record is not None
    assert outcome.selected_record.item_id == "blink"
    assert outcome.decision.selected is not None
    assert (
        outcome.decision.selected.title_match.method
        is DeterministicMatchMethod.STYLIZED_NUMBER_ALIAS
    )
    assert outcome.decision.selected.title_match.matched_alias == "blink one eighty two"


def test_duplicate_stylized_artist_records_remain_ambiguous() -> None:
    index = CatalogIndex.build(
        [
            _item("blink-lower", "blink-182", "MusicArtist"),
            _item("blink-upper", "Blink-182", "MusicArtist"),
        ]
    )

    outcome = index.search(
        "blink one eighty two",
        context=MediaSearchContext(media_type="MusicArtist"),
    )

    assert outcome.decision.status is MatchDecisionStatus.AMBIGUOUS
    assert outcome.decision.automatic_selection_allowed is False
    assert [match.candidate.key for match in outcome.ranking.matches] == [
        "blink-lower",
        "blink-upper",
    ]


def test_wrong_stylized_number_does_not_match() -> None:
    index = CatalogIndex.build(
        [_item("blink", "blink-182", "MusicArtist")]
    )

    outcome = index.search(
        "blink one eighty three",
        context=MediaSearchContext(media_type="MusicArtist"),
    )

    assert outcome.decision.status is MatchDecisionStatus.NOT_FOUND



def test_music_artists_with_same_musicbrainz_id_form_one_logical_record() -> None:
    musicbrainz_id = "0743b15a-3c32-48c8-ad58-cb325350befa"
    index = CatalogIndex.build(
        [
            _item(
                "blink-lower",
                "blink-182",
                "MusicArtist",
                provider_ids={"MusicBrainzArtist": musicbrainz_id},
            ),
            _item(
                "blink-upper",
                "Blink-182",
                "MusicArtist",
                provider_ids={"MusicBrainzArtist": musicbrainz_id.upper()},
            ),
        ]
    )

    assert index.raw_item_count == 2
    assert len(index.records) == 1
    assert index.logical_group_count == 1
    assert index.grouped_physical_item_count == 1
    record = index.records[0]
    assert record.is_logical_group is True
    assert record.physical_item_ids == ("blink-lower", "blink-upper")
    assert record.provider_ids == (("musicbrainzartist", musicbrainz_id),)
    assert record.candidate.physical_keys == record.physical_item_ids
    assert index.get("blink-lower") is record
    assert index.get("blink-upper") is record


def test_grouped_musicbrainz_artist_spoken_alias_is_one_confident_match() -> None:
    musicbrainz_id = "0743b15a-3c32-48c8-ad58-cb325350befa"
    index = CatalogIndex.build(
        [
            _item(
                "blink-lower",
                "blink-182",
                "MusicArtist",
                provider_ids={"MusicBrainzArtist": musicbrainz_id},
            ),
            _item(
                "blink-upper",
                "Blink-182",
                "MusicArtist",
                provider_ids={"MusicBrainzArtist": musicbrainz_id},
            ),
        ]
    )

    outcome = index.search(
        "blink one eighty two",
        context=MediaSearchContext(media_type="MusicArtist"),
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.decision.automatic_selection_allowed is True
    assert len(outcome.ranking.matches) == 1
    assert outcome.selected_record is not None
    assert outcome.selected_record.physical_item_ids == (
        "blink-lower",
        "blink-upper",
    )


def test_conflicting_musicbrainz_artist_ids_remain_ambiguous() -> None:
    index = CatalogIndex.build(
        [
            _item(
                "blink-a",
                "blink-182",
                "MusicArtist",
                provider_ids={"MusicBrainzArtist": "provider-a"},
            ),
            _item(
                "blink-b",
                "Blink-182",
                "MusicArtist",
                provider_ids={"MusicBrainzArtist": "provider-b"},
            ),
        ]
    )

    outcome = index.search(
        "blink one eighty two",
        context=MediaSearchContext(media_type="MusicArtist"),
    )

    assert len(index.records) == 2
    assert index.logical_group_count == 0
    assert outcome.decision.status is MatchDecisionStatus.AMBIGUOUS


def test_non_artist_records_are_not_grouped_by_provider_id() -> None:
    index = CatalogIndex.build(
        [
            _item(
                "movie-a",
                "The Matrix",
                "Movie",
                provider_ids={"Tmdb": "603"},
            ),
            _item(
                "movie-b",
                "The Matrix",
                "Movie",
                provider_ids={"Tmdb": "603"},
            ),
        ]
    )

    assert len(index.records) == 2
    assert index.logical_group_count == 0
