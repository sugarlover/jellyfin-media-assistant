"""Regression tests for conservative internal-article omission matching."""

from __future__ import annotations

from custom_components.jellyfin_assist.matching.context import (
    MediaCandidate,
    MediaSearchContext,
)
from custom_components.jellyfin_assist.matching.decision import MatchDecisionStatus
from custom_components.jellyfin_assist.matching.deterministic import (
    DeterministicMatchMethod,
    classify_article_omission_fragment_match,
    score_for_method,
)
from custom_components.jellyfin_assist.matching.pipeline import (
    LexicalMatchFamily,
    SearchDecisionReason,
    decide_search_ranking,
    rank_search_candidates,
)
from custom_components.jellyfin_assist.search.catalog_index import CatalogIndex


def _decide(
    query: str,
    candidates: list[MediaCandidate],
    context: MediaSearchContext | None = None,
):
    return decide_search_ranking(rank_search_candidates(query, candidates, context))


def _item(item_id: str, name: str, media_type: str) -> dict[str, object]:
    return {"Id": item_id, "Name": name, "Type": media_type}


def test_internal_article_omission_fragment_matches_relient_k_album() -> None:
    match = classify_article_omission_fragment_match(
        "The Anatomy of tongue in cheek",
        "The Anatomy of the Tongue In Cheek (Gold Edition)",
    )

    assert match is not None
    assert match.method is DeterministicMatchMethod.ARTICLE_OMISSION_FRAGMENT
    assert match.shared_value == "the anatomy of the tongue in cheek"
    assert match.score == score_for_method(
        DeterministicMatchMethod.ARTICLE_OMISSION_FRAGMENT
    )


def test_article_omission_is_weaker_than_normal_title_fragment() -> None:
    assert score_for_method(
        DeterministicMatchMethod.ARTICLE_OMISSION_FRAGMENT
    ) < score_for_method(DeterministicMatchMethod.TITLE_FRAGMENT)


def test_article_omission_requires_an_internal_article() -> None:
    assert (
        classify_article_omission_fragment_match(
            "Thing Returns Now",
            "The Thing Returns Now",
        )
        is None
    )
    assert (
        classify_article_omission_fragment_match(
            "The Last Man Standing",
            "The Last Man Standing The",
        )
        is None
    )


def test_article_omission_does_not_hide_missing_content_words() -> None:
    assert (
        classify_article_omission_fragment_match(
            "The Anatomy tongue in cheek",
            "The Anatomy of the Tongue In Cheek",
        )
        is None
    )


def test_internal_article_omission_is_selected_as_deterministic() -> None:
    decision = _decide(
        "The Anatomy of tongue in cheek",
        [
            MediaCandidate(
                key="album",
                title="The Anatomy of the Tongue In Cheek (Gold Edition)",
                media_type="MusicAlbum",
            )
        ],
        MediaSearchContext(media_type="MusicAlbum"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "album"
    assert decision.active_family is LexicalMatchFamily.DETERMINISTIC
    assert (
        decision.selected.title_match.method
        is DeterministicMatchMethod.ARTICLE_OMISSION_FRAGMENT
    )


def test_exact_title_still_beats_article_omission_candidate() -> None:
    decision = _decide(
        "The Anatomy of tongue in cheek",
        [
            MediaCandidate(
                key="exact",
                title="The Anatomy of tongue in cheek",
                media_type="MusicAlbum",
            ),
            MediaCandidate(
                key="omission",
                title="The Anatomy of the Tongue In Cheek",
                media_type="MusicAlbum",
            ),
        ],
        MediaSearchContext(media_type="MusicAlbum"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "exact"
    assert decision.selected.title_match.method is DeterministicMatchMethod.EXACT_ORIGINAL


def test_multiple_article_omission_candidates_remain_ambiguous() -> None:
    decision = _decide(
        "Anatomy of tongue in cheek",
        [
            MediaCandidate(
                key="standard",
                title="Anatomy of the Tongue In Cheek",
                media_type="MusicAlbum",
            ),
            MediaCandidate(
                key="deluxe",
                title="Anatomy of the Tongue In Cheek Deluxe",
                media_type="MusicAlbum",
            ),
        ],
        MediaSearchContext(media_type="MusicAlbum"),
    )

    assert decision.status is MatchDecisionStatus.AMBIGUOUS
    assert decision.reason is SearchDecisionReason.TOP_SCORE_TIED
    assert decision.selected is None


def test_catalog_index_resolves_internal_article_omission_for_album() -> None:
    index = CatalogIndex.build(
        [
            _item(
                "anatomy",
                "The Anatomy of the Tongue In Cheek (Gold Edition)",
                "MusicAlbum",
            )
        ]
    )

    outcome = index.search(
        "The Anatomy of tongue in cheek",
        context=MediaSearchContext(media_type="MusicAlbum"),
    )

    assert outcome.decision.status is MatchDecisionStatus.MATCHED
    assert outcome.selected_record is not None
    assert outcome.selected_record.item_id == "anatomy"
    assert outcome.decision.selected is not None
    assert (
        outcome.decision.selected.title_match.method
        is DeterministicMatchMethod.ARTICLE_OMISSION_FRAGMENT
    )
