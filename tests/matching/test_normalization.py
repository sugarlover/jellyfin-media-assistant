"""Regression tests for deterministic media-title normalization."""

from __future__ import annotations

import pytest

from custom_components.jellyfin_assist.matching.normalization import (
    VariantMethod,
    build_text_profile,
    find_shared_variants,
)


def _shared_values(left: str, right: str) -> set[str]:
    return {
        match.value
        for match in find_shared_variants(
            build_text_profile(left),
            build_text_profile(right),
        )
    }


def test_three_am_variants_share_compact_numeric_form() -> None:
    assert "3am" in _shared_values("three am", "3AM")
    assert "3am" in _shared_values("3 am", "3AM")
    assert "3am" in _shared_values("three am", "3 am")


def test_thirteenth_warrior_shares_ordinal_digit_form() -> None:
    assert "the 13th warrior" in _shared_values(
        "the thirteenth warrior",
        "The 13th Warrior",
    )


def test_numeric_ordinal_title_exposes_word_alias() -> None:
    profile = build_text_profile("The 13th Warrior")
    alias = profile.get("the thirteenth warrior")

    assert alias is not None
    assert VariantMethod.NUMERIC_ORDINAL_TO_WORDS in alias.methods


def test_reverse_ordinal_alias_is_conservative() -> None:
    assert "blink one hundred eighty second" not in build_text_profile("blink-182").values
    assert "the thirteenth warrior" not in build_text_profile("The 13st Warrior").values


def test_runaround_spacing_and_dash_variants_converge() -> None:
    expected = "runaround"
    assert expected in _shared_values("runaround", "run-around")
    assert expected in _shared_values("runaround", "run around")
    assert expected in _shared_values("run-around", "run around")


def test_compact_spacing_remains_explicitly_labeled() -> None:
    spaced = build_text_profile("run around").get("runaround")
    assert spaced is not None
    assert VariantMethod.COMPACT_SPACING in spaced.methods


def test_unicode_compatibility_and_casefolding() -> None:
    assert "3am" in _shared_values("３ＡＭ", "3am")


def test_diacritics_are_available_as_a_labeled_variant() -> None:
    assert "beyonce" in _shared_values("Beyoncé", "Beyonce")
    folded = build_text_profile("Beyoncé").get("beyonce")
    assert folded is not None
    assert VariantMethod.DIACRITIC_FOLD in folded.methods


def test_apostrophes_quotes_periods_and_dashes_become_separators() -> None:
    assert "guns n roses" in _shared_values("Guns N’ Roses", "Guns N' Roses")
    assert "3am" in _shared_values("3.A.M.", "3 AM")
    assert "love story" in _shared_values("Love—Story", '"Love Story"')


def test_compound_cardinal_and_ordinal_words_are_supported() -> None:
    assert "21 pilots" in _shared_values("twenty one pilots", "21 Pilots")
    assert "21st century" in _shared_values("twenty first century", "21st Century")
    assert "101 dalmatians" in _shared_values("one hundred one dalmatians", "101 Dalmatians")
    assert "182" in build_text_profile("one hundred eighty two").values
    assert "82" in build_text_profile("eighty two").values


def test_segmented_spoken_numbers_are_not_added_as_cardinal_sums() -> None:
    blink = build_text_profile("blink one eighty two")
    assert "blink 83" not in blink.values
    assert "blink83" not in blink.values

    assert "14" not in build_text_profile("three eleven").values
    assert "94" not in build_text_profile("nineteen seventy five").values


def test_invalid_number_phrase_is_preserved_instead_of_partially_converted() -> None:
    profile = build_text_profile("blink one eighty two")

    assert "blink one eighty two" in profile.values
    assert "blink 1 82" not in profile.values


def test_variants_are_deduplicated_and_methods_are_merged() -> None:
    profile = build_text_profile("3AM")
    values = [variant.value for variant in profile.variants]
    assert len(values) == len(set(values))

    normalized = profile.get("3am")
    assert normalized is not None
    assert VariantMethod.UNICODE_CASEFOLD in normalized.methods


def test_unrelated_titles_do_not_gain_a_shared_variant() -> None:
    assert not _shared_values("Runaway", "Run Around")
    assert not _shared_values("13", "30")


def test_articles_and_subtitles_are_not_removed_in_this_layer() -> None:
    assert not _shared_values("The Thing", "Thing")
    assert not _shared_values("Blade Runner: The Final Cut", "Blade Runner")


def test_roman_numerals_are_not_inferred_from_letters_inside_words() -> None:
    profile = build_text_profile("Civil")
    assert "c4l" not in profile.values
    assert "civ4" not in profile.values


def test_empty_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        build_text_profile("   ")


def test_non_string_text_is_rejected() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        build_text_profile(3)  # type: ignore[arg-type]


def test_spoken_title_signature_folds_punctuation_and_number_words() -> None:
    from custom_components.jellyfin_assist.matching.normalization import (
        spoken_title_signature,
    )

    assert spoken_title_signature("three am") == "3am"
    assert spoken_title_signature("3 AM") == "3am"
    assert spoken_title_signature("3 A.M.") == "3am"


def test_spoken_title_signature_keeps_segmented_numbers_non_arithmetic() -> None:
    from custom_components.jellyfin_assist.matching.normalization import (
        spoken_title_signature,
    )

    assert spoken_title_signature("one eighty two") == "oneeightytwo"
