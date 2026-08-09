"""Tests for unified deterministic-first and controlled-fuzzy ranking."""

from __future__ import annotations

from custom_components.jellyfin_assist.matching.context import (
    ContextField,
    ContextRelation,
    MediaCandidate,
    MediaSearchContext,
)
from custom_components.jellyfin_assist.matching.decision import MatchDecisionStatus
from custom_components.jellyfin_assist.matching.deterministic import (
    DeterministicMatchMethod,
)
from custom_components.jellyfin_assist.matching.fuzzy import FuzzyMatchMethod
from custom_components.jellyfin_assist.matching.pipeline import (
    LexicalMatchFamily,
    SearchDecisionReason,
    classify_lexical_match,
    decide_search_ranking,
    rank_search_candidates,
    threshold_for_fuzzy_method,
)


def _decide(
    query: str,
    candidates: list[MediaCandidate],
    context: MediaSearchContext | None = None,
):
    return decide_search_ranking(rank_search_candidates(query, candidates, context))


def test_unified_classifier_prefers_deterministic_equivalence() -> None:
    match = classify_lexical_match("run around", "Runaround")

    assert match is not None
    assert match.family is LexicalMatchFamily.DETERMINISTIC
    assert match.method is DeterministicMatchMethod.COMPACT_SPACING
    assert match.deterministic is not None
    assert match.fuzzy is None


def test_unified_classifier_falls_back_to_controlled_fuzzy() -> None:
    match = classify_lexical_match("jurasic park", "Jurassic Park")

    assert match is not None
    assert match.family is LexicalMatchFamily.FUZZY
    assert match.method is FuzzyMatchMethod.SINGLE_EDIT
    assert match.deterministic is None
    assert match.fuzzy is not None


def test_deterministic_tier_blocks_fuzzy_competition() -> None:
    ranking = rank_search_candidates(
        "Spider Man",
        [
            MediaCandidate(key="fuzzy", title="Spider Mann", year=2002),
            MediaCandidate(key="deterministic", title="Spider-Man"),
        ],
        MediaSearchContext(year=2002),
    )

    assert ranking.active_family is LexicalMatchFamily.DETERMINISTIC
    assert [item.candidate.key for item in ranking.matches] == ["deterministic"]


def test_media_type_rejection_does_not_block_fuzzy_fallback() -> None:
    ranking = rank_search_candidates(
        "Matirx",
        [
            MediaCandidate(key="wrong-type-exact", title="Matirx", media_type="Audio"),
            MediaCandidate(key="movie", title="Matrix", media_type="Movie"),
        ],
        MediaSearchContext(media_type="Movie"),
    )

    assert ranking.active_family is LexicalMatchFamily.FUZZY
    assert [item.candidate.key for item in ranking.matches] == ["movie"]
    assert [item.candidate.key for item in ranking.rejected] == ["wrong-type-exact"]


def test_context_ranks_equal_fuzzy_titles_without_changing_lexical_score() -> None:
    ranking = rank_search_candidates(
        "Alonee",
        [
            MediaCandidate(key="u2", title="Alone", media_type="Audio", artist="U2"),
            MediaCandidate(
                key="metallica",
                title="Alone",
                media_type="Audio",
                artist="Metallica",
            ),
        ],
        MediaSearchContext(media_type="Audio", artist="Metallica"),
    )

    assert ranking.active_family is LexicalMatchFamily.FUZZY
    assert [item.candidate.key for item in ranking.matches] == ["metallica", "u2"]
    assert ranking.matches[0].title_match.lexical_score == ranking.matches[1].title_match.lexical_score
    assert ranking.matches[0].context_score > ranking.matches[1].context_score


def test_unique_single_edit_can_be_selected() -> None:
    decision = _decide(
        "jurasic park",
        [MediaCandidate(key="movie", title="Jurassic Park")],
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.reason is SearchDecisionReason.UNIQUE_CONFIDENT_MATCH
    assert decision.selected is not None
    assert decision.selected.candidate.key == "movie"
    assert decision.active_family is LexicalMatchFamily.FUZZY


def test_unique_adjacent_transposition_short_title_can_be_selected() -> None:
    decision = _decide(
        "matirx",
        [MediaCandidate(key="movie", title="Matrix")],
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.title_match.method is FuzzyMatchMethod.ADJACENT_TRANSPOSITION


def test_equal_fuzzy_candidates_require_selection() -> None:
    decision = _decide(
        "jurasic park",
        [
            MediaCandidate(key="copy-a", title="Jurassic Park"),
            MediaCandidate(key="copy-b", title="Jurassic Park"),
        ],
    )

    assert decision.status is MatchDecisionStatus.AMBIGUOUS
    assert decision.reason is SearchDecisionReason.TOP_SCORE_TIED
    assert decision.selected is None
    assert [item.candidate.key for item in decision.alternatives] == ["copy-a", "copy-b"]


def test_fuzzy_context_contradiction_prevents_auto_selection() -> None:
    decision = _decide(
        "jurasic park",
        [MediaCandidate(key="movie", title="Jurassic Park", year=1993)],
        MediaSearchContext(year=2001),
    )

    assert decision.status is MatchDecisionStatus.NOT_FOUND
    assert decision.reason is SearchDecisionReason.TOP_CONTEXT_CONTRADICTION
    assert decision.selected is None


def test_multi_edit_singleton_requires_supporting_context() -> None:
    decision = _decide(
        "jurasic prak",
        [MediaCandidate(key="movie", title="Jurassic Park")],
    )

    assert decision.status is MatchDecisionStatus.NOT_FOUND
    assert decision.reason is SearchDecisionReason.SCORE_BELOW_THRESHOLD
    assert decision.selected is None


def test_multi_edit_singleton_can_pass_with_exact_year_context() -> None:
    decision = _decide(
        "jurasic prak",
        [MediaCandidate(key="movie", title="Jurassic Park", year=1993)],
        MediaSearchContext(year=1993),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.title_match.method is FuzzyMatchMethod.LIMITED_MULTI_EDIT
    assert decision.selected.context_score >= 7


def test_unrelated_title_remains_not_found() -> None:
    decision = _decide(
        "Run Around",
        [MediaCandidate(key="wrong", title="Runaway")],
    )

    assert decision.status is MatchDecisionStatus.NOT_FOUND
    assert decision.reason is SearchDecisionReason.NO_MATCHING_CANDIDATES


def test_known_number_regression_remains_deterministic() -> None:
    decision = _decide(
        "the thirteenth warrior",
        [MediaCandidate(key="movie", title="The 13th Warrior")],
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.title_match.family is LexicalMatchFamily.DETERMINISTIC
    assert decision.selected.title_match.method is DeterministicMatchMethod.NUMBER_EQUIVALENT


def test_misspelled_ordinal_uses_fuzzy_match_against_safe_word_alias() -> None:
    decision = _decide(
        "the thirteeth warrior",
        [MediaCandidate(key="movie", title="The 13th Warrior", media_type="Movie")],
        MediaSearchContext(media_type="Movie"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "movie"
    assert decision.selected.title_match.family is LexicalMatchFamily.FUZZY
    assert decision.selected.title_match.method is FuzzyMatchMethod.SINGLE_EDIT
    assert decision.selected.title_match.fuzzy is not None
    assert decision.selected.title_match.fuzzy.candidate_value == "the thirteenth warrior"


def test_diagnostics_keep_lexical_context_and_evidence_separate() -> None:
    ranking = rank_search_candidates(
        "jurasic park",
        [MediaCandidate(key="movie", title="Jurassic Park", media_type="Movie", year=1993)],
        MediaSearchContext(media_type="Movie", year=1993),
    )

    result = ranking.matches[0]
    assert result.total_score == result.title_match.lexical_score + result.context_score
    assert result.title_match.fuzzy is not None
    assert result.title_match.fuzzy.edit_distance == 1
    assert any(
        item.field is ContextField.YEAR and item.relation is ContextRelation.MATCH
        for item in result.evidence
    )


def test_fuzzy_thresholds_are_stricter_for_multi_edit() -> None:
    single = threshold_for_fuzzy_method(FuzzyMatchMethod.SINGLE_EDIT)
    multi = threshold_for_fuzzy_method(FuzzyMatchMethod.LIMITED_MULTI_EDIT)

    assert multi.minimum_total_score > single.minimum_total_score
    assert multi.minimum_margin > single.minimum_margin
    assert multi.minimum_single_context_score > single.minimum_single_context_score


def test_unified_classifier_falls_through_to_phonetic() -> None:
    from custom_components.jellyfin_assist.matching.phonetic import PhoneticMatchMethod

    match = classify_lexical_match("Right Here", "Write Here")

    assert match is not None
    assert match.family is LexicalMatchFamily.PHONETIC
    assert match.method is PhoneticMatchMethod.COMMON_HOMOPHONE
    assert match.phonetic is not None
    assert match.fuzzy is None


def test_fuzzy_tier_blocks_phonetic_competition() -> None:
    ranking = rank_search_candidates(
        "Right Here",
        [
            MediaCandidate(key="fuzzy", title="Right Hear"),
            MediaCandidate(key="phonetic", title="Write Here"),
        ],
    )

    assert ranking.active_family is LexicalMatchFamily.FUZZY
    assert [item.candidate.key for item in ranking.matches] == ["fuzzy"]


def test_phonetic_singleton_without_context_is_not_auto_selected() -> None:
    decision = _decide(
        "Right Here",
        [MediaCandidate(key="song", title="Write Here")],
    )

    assert decision.status is MatchDecisionStatus.NOT_FOUND
    assert decision.reason is SearchDecisionReason.SCORE_BELOW_THRESHOLD
    assert decision.active_family is LexicalMatchFamily.PHONETIC


def test_phonetic_singleton_with_only_media_type_still_needs_context() -> None:
    decision = _decide(
        "Right Here",
        [MediaCandidate(key="song", title="Write Here", media_type="Audio")],
        MediaSearchContext(media_type="Audio"),
    )

    assert decision.status is MatchDecisionStatus.NOT_FOUND
    assert decision.reason is SearchDecisionReason.PHONETIC_SINGLETON_NEEDS_CONTEXT


def test_phonetic_song_can_match_with_artist_and_media_type_context() -> None:
    decision = _decide(
        "Right Here",
        [
            MediaCandidate(
                key="song",
                title="Write Here",
                media_type="Audio",
                artist="Example Artist",
            )
        ],
        MediaSearchContext(media_type="Audio", artist="Example Artist"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "song"
    assert decision.selected.title_match.family is LexicalMatchFamily.PHONETIC


def test_phonetic_movie_can_match_with_year_and_media_type_context() -> None:
    decision = _decide(
        "Sean",
        [MediaCandidate(key="movie", title="Shawn", media_type="Movie", year=2005)],
        MediaSearchContext(media_type="Movie", year=2005),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "movie"


def test_equal_phonetic_candidates_remain_ambiguous() -> None:
    decision = _decide(
        "Right Here",
        [
            MediaCandidate(
                key="copy-a",
                title="Write Here",
                media_type="Audio",
                artist="Example Artist",
            ),
            MediaCandidate(
                key="copy-b",
                title="Write Here",
                media_type="Audio",
                artist="Example Artist",
            ),
        ],
        MediaSearchContext(media_type="Audio", artist="Example Artist"),
    )

    assert decision.status is MatchDecisionStatus.AMBIGUOUS
    assert decision.reason is SearchDecisionReason.TOP_SCORE_TIED
    assert decision.selected is None


def test_context_can_disambiguate_equal_phonetic_titles() -> None:
    decision = _decide(
        "Right Here",
        [
            MediaCandidate(
                key="correct",
                title="Write Here",
                media_type="Audio",
                artist="Example Artist",
            ),
            MediaCandidate(
                key="other",
                title="Write Here",
                media_type="Audio",
                artist="Other Artist",
            ),
        ],
        MediaSearchContext(media_type="Audio", artist="Example Artist"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "correct"


def test_phonetic_diagnostics_keep_scores_separate() -> None:
    ranking = rank_search_candidates(
        "Right Here",
        [
            MediaCandidate(
                key="song",
                title="Write Here",
                media_type="Audio",
                artist="Example Artist",
            )
        ],
        MediaSearchContext(media_type="Audio", artist="Example Artist"),
    )

    result = ranking.matches[0]
    assert result.title_match.phonetic is not None
    assert result.title_match.lexical_score == 60
    assert result.title_match.phonetic_score == 74
    assert result.total_score == result.title_match.phonetic_score + result.context_score


def test_phonetic_thresholds_require_strong_context_and_margin() -> None:
    from custom_components.jellyfin_assist.matching.phonetic import PhoneticMatchMethod
    from custom_components.jellyfin_assist.matching.pipeline import threshold_for_phonetic_method

    threshold = threshold_for_phonetic_method(
        PhoneticMatchMethod.COMMON_HOMOPHONE
    )

    assert threshold.minimum_single_context_score >= 15
    assert threshold.minimum_margin >= 14


def test_title_fragment_tier_precedes_fuzzy_matching() -> None:
    ranking = rank_search_candidates(
        "planet",
        [
            MediaCandidate(key="fragment", title="Planet Terror", media_type="Movie"),
            MediaCandidate(key="fuzzy", title="Planer", media_type="Movie"),
        ],
        MediaSearchContext(media_type="Movie"),
    )

    assert ranking.active_family is LexicalMatchFamily.DETERMINISTIC
    assert [item.candidate.key for item in ranking.matches] == ["fragment"]
    assert ranking.matches[0].title_match.method is DeterministicMatchMethod.TITLE_FRAGMENT


def test_multiple_title_fragments_require_selection() -> None:
    decision = _decide(
        "planet",
        [
            MediaCandidate(key="terror", title="Planet Terror", media_type="Movie"),
            MediaCandidate(key="forbidden", title="Forbidden Planet", media_type="Movie"),
            MediaCandidate(key="red", title="Red Planet", media_type="Movie"),
        ],
        MediaSearchContext(media_type="Movie"),
    )

    assert decision.status is MatchDecisionStatus.AMBIGUOUS
    assert decision.reason is SearchDecisionReason.TOP_SCORE_TIED
    assert decision.selection_required is True
    assert [item.candidate.key for item in decision.alternatives] == [
        "terror",
        "forbidden",
        "red",
    ]


def test_exact_full_title_suppresses_fragment_candidates() -> None:
    decision = _decide(
        "Planet",
        [
            MediaCandidate(key="exact", title="Planet", media_type="Movie"),
            MediaCandidate(key="terror", title="Planet Terror", media_type="Movie"),
        ],
        MediaSearchContext(media_type="Movie"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "exact"
    assert decision.selected.title_match.method is DeterministicMatchMethod.EXACT_ORIGINAL


def test_unique_title_fragment_can_be_selected_with_explicit_type() -> None:
    decision = _decide(
        "forbidden",
        [MediaCandidate(key="movie", title="Forbidden Planet", media_type="Movie")],
        MediaSearchContext(media_type="Movie"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "movie"
    assert decision.selected.title_match.method is DeterministicMatchMethod.TITLE_FRAGMENT


def test_audio_spoken_title_collision_requires_selection() -> None:
    decision = _decide(
        "three am",
        [
            MediaCandidate(
                key="matchbox",
                title="3 AM",
                media_type="Audio",
                artist="Matchbox Twenty",
                album="Yourself Or Someone Like You",
                year=1996,
            ),
            MediaCandidate(
                key="nf",
                title="3 A.M.",
                media_type="Audio",
                artist="NF",
                album="Perception",
                year=2017,
            ),
        ],
        MediaSearchContext(media_type="Audio"),
    )

    assert decision.status is MatchDecisionStatus.AMBIGUOUS
    assert decision.reason is SearchDecisionReason.AUDIO_SPOKEN_TITLE_COLLISION
    assert decision.selected is None
    assert [item.candidate.key for item in decision.alternatives] == [
        "matchbox",
        "nf",
    ]
    assert decision.observed_margin == 5


def test_exactly_typed_audio_title_still_respects_spoken_collision() -> None:
    decision = _decide(
        "3 AM",
        [
            MediaCandidate(
                key="matchbox",
                title="3 AM",
                media_type="Audio",
                artist="Matchbox Twenty",
            ),
            MediaCandidate(
                key="nf",
                title="3 A.M.",
                media_type="Audio",
                artist="NF",
            ),
        ],
        MediaSearchContext(media_type="Audio"),
    )

    assert decision.status is MatchDecisionStatus.AMBIGUOUS
    assert decision.reason is SearchDecisionReason.AUDIO_SPOKEN_TITLE_COLLISION


def test_artist_context_resolves_audio_spoken_title_collision() -> None:
    decision = _decide(
        "three am",
        [
            MediaCandidate(
                key="matchbox",
                title="3 AM",
                media_type="Audio",
                artist="Matchbox Twenty",
            ),
            MediaCandidate(
                key="nf",
                title="3 A.M.",
                media_type="Audio",
                artist="NF",
            ),
        ],
        MediaSearchContext(media_type="Audio", artist="Matchbox Twenty"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "matchbox"


def test_album_context_resolves_audio_spoken_title_collision() -> None:
    decision = _decide(
        "three am",
        [
            MediaCandidate(
                key="matchbox",
                title="3 AM",
                media_type="Audio",
                album="Yourself Or Someone Like You",
            ),
            MediaCandidate(
                key="nf",
                title="3 A.M.",
                media_type="Audio",
                album="Perception",
            ),
        ],
        MediaSearchContext(media_type="Audio", album="Perception"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "nf"


def test_year_context_resolves_audio_spoken_title_collision() -> None:
    decision = _decide(
        "three am",
        [
            MediaCandidate(
                key="matchbox",
                title="3 AM",
                media_type="Audio",
                year=1996,
            ),
            MediaCandidate(
                key="nf",
                title="3 A.M.",
                media_type="Audio",
                year=2017,
            ),
        ],
        MediaSearchContext(media_type="Audio", year=2017),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "nf"


def test_exact_song_title_with_incomplete_artist_is_selected() -> None:
    decision = _decide(
        "Crash Into Me",
        [
            MediaCandidate(
                key="crash",
                title="Crash Into Me",
                media_type="Audio",
                artist="Dave Matthews Band",
            )
        ],
        MediaSearchContext(media_type="Audio", artist="Dave Matthews"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "crash"


def test_partial_song_title_and_incomplete_artist_reinforce_each_other() -> None:
    decision = _decide(
        "Crash",
        [
            MediaCandidate(
                key="crash",
                title="Crash Into Me",
                media_type="Audio",
                artist="Dave Matthews Band",
            )
        ],
        MediaSearchContext(media_type="Audio", artist="Dave Matthews"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "crash"
    assert decision.selected.title_match.method is DeterministicMatchMethod.TITLE_FRAGMENT


def test_song_title_and_incomplete_artist_may_both_contain_errors() -> None:
    decision = _decide(
        "Crsh Into Me",
        [
            MediaCandidate(
                key="crash",
                title="Crash Into Me",
                media_type="Audio",
                artist="Dave Matthews Band",
            )
        ],
        MediaSearchContext(media_type="Audio", artist="Dave Mathews"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "crash"
    artist_evidence = next(
        evidence
        for evidence in decision.selected.evidence
        if evidence.field is ContextField.ARTIST
    )
    assert artist_evidence.method is FuzzyMatchMethod.SINGLE_EDIT


def test_partial_song_title_with_conflicting_artist_is_not_selected() -> None:
    decision = _decide(
        "Crash",
        [
            MediaCandidate(
                key="crash",
                title="Crash Into Me",
                media_type="Audio",
                artist="Dave Matthews Band",
            )
        ],
        MediaSearchContext(media_type="Audio", artist="Coldplay"),
    )

    assert decision.status is MatchDecisionStatus.NOT_FOUND
    assert decision.reason is SearchDecisionReason.TOP_CONTEXT_CONTRADICTION


def test_partial_episode_title_and_incomplete_series_are_selected() -> None:
    decision = _decide(
        "Everybody",
        [
            MediaCandidate(
                key="episode",
                title="Where Is Everybody?",
                media_type="Episode",
                series="The Twilight Zone",
            )
        ],
        MediaSearchContext(media_type="Episode", series="Twilight Zone"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "episode"


def test_episode_title_and_series_may_both_contain_errors() -> None:
    decision = _decide(
        "Where Is Everybdy?",
        [
            MediaCandidate(
                key="episode",
                title="Where Is Everybody?",
                media_type="Episode",
                series="The Twilight Zone",
            )
        ],
        MediaSearchContext(media_type="Episode", series="The Twlight Zone"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "episode"


def test_incomplete_series_title_uses_existing_title_fragment_matching() -> None:
    decision = _decide(
        "Twilight Zone",
        [
            MediaCandidate(
                key="series",
                title="The Twilight Zone",
                media_type="Series",
            )
        ],
        MediaSearchContext(media_type="Series"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "series"
    assert decision.selected.title_match.method is DeterministicMatchMethod.TITLE_FRAGMENT


def test_misspelled_series_title_uses_existing_controlled_fuzzy_matching() -> None:
    decision = _decide(
        "The Twlight Zone",
        [
            MediaCandidate(
                key="series",
                title="The Twilight Zone",
                media_type="Series",
            )
        ],
        MediaSearchContext(media_type="Series"),
    )

    assert decision.status is MatchDecisionStatus.MATCHED
    assert decision.selected is not None
    assert decision.selected.candidate.key == "series"
    assert decision.active_family is LexicalMatchFamily.FUZZY
