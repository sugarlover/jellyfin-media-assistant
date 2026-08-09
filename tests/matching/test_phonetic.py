"""Tests for the conservative phonetic/ASR matching tier."""

from __future__ import annotations

from custom_components.jellyfin_assist.matching.deterministic import TitleCandidate
from custom_components.jellyfin_assist.matching.phonetic import (
    PhoneticMatchMethod,
    build_phonetic_profiles,
    classify_phonetic_match,
    rank_phonetic_candidates,
    score_for_phonetic_method,
)


def test_profiles_apply_case_diacritic_and_punctuation_normalization() -> None:
    profiles = build_phonetic_profiles("  RÍGHT—HERE  ")

    assert any(profile.source_value == "right here" for profile in profiles)
    assert any(profile.signature == ("H05", "H600") for profile in profiles)


def test_common_homophone_is_classified_explicitly() -> None:
    match = classify_phonetic_match("Right Here", "Write Here")

    assert match is not None
    assert match.method is PhoneticMatchMethod.COMMON_HOMOPHONE
    assert match.query_signature == match.candidate_signature


def test_short_common_homophone_can_be_classified() -> None:
    match = classify_phonetic_match("Sea", "See")

    assert match is not None
    assert match.method is PhoneticMatchMethod.COMMON_HOMOPHONE


def test_soundex_style_signature_handles_different_spellings() -> None:
    match = classify_phonetic_match("Sean", "Shawn")

    assert match is not None
    assert match.method is PhoneticMatchMethod.TOKEN_SIGNATURE
    assert match.query_signature == ("S500",)


def test_phonetic_spelling_rules_handle_stephen_and_steven() -> None:
    match = classify_phonetic_match("Stephen", "Steven")

    assert match is not None
    assert match.method is PhoneticMatchMethod.TOKEN_SIGNATURE


def test_deterministic_equivalence_is_not_reclassified_as_phonetic() -> None:
    assert classify_phonetic_match("The 13th Warrior", "the 13th warrior") is None


def test_unrelated_titles_do_not_match_phonetically() -> None:
    assert classify_phonetic_match("Metallica", "Madonna") is None


def test_token_count_must_match() -> None:
    assert classify_phonetic_match("Right Here", "Write") is None


def test_very_short_single_token_is_rejected() -> None:
    assert classify_phonetic_match("No", "Know") is None


def test_lexical_and_phonetic_scores_are_separate() -> None:
    match = classify_phonetic_match("Right Here", "Write Here")

    assert match is not None
    assert match.lexical_score == 60
    assert match.phonetic_score == 74
    assert match.score == match.phonetic_score


def test_common_homophone_scores_above_generic_signature() -> None:
    assert score_for_phonetic_method(
        PhoneticMatchMethod.COMMON_HOMOPHONE
    ) > score_for_phonetic_method(PhoneticMatchMethod.TOKEN_SIGNATURE)


def test_phonetic_ranking_preserves_catalog_order_on_a_tie() -> None:
    ranking = rank_phonetic_candidates(
        "Sean",
        [
            TitleCandidate(key="first", title="Shawn"),
            TitleCandidate(key="second", title="Shon"),
        ],
    )

    assert [item.candidate.key for item in ranking.matches] == ["first", "second"]
    assert ranking.top_score_is_unique is False
    assert ranking.top_margin == 0
