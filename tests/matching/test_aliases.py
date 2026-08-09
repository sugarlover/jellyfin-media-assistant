"""Tests for conservative catalog-derived stylized-name aliases."""

from custom_components.jellyfin_assist.matching.aliases import (
    spoken_numeric_forms,
    stylized_numeric_aliases,
)


def test_three_digit_forms_include_band_style_reading() -> None:
    assert spoken_numeric_forms("182") == (
        "one hundred eighty two",
        "one eight two",
        "one eighty two",
    )


def test_four_digit_forms_include_year_style_reading() -> None:
    assert "nineteen seventy five" in spoken_numeric_forms("1975")


def test_artist_aliases_cover_blink_182() -> None:
    aliases = stylized_numeric_aliases("blink-182", "MusicArtist")

    assert "blink one eighty two" in aliases
    assert "blink one eight two" in aliases


def test_artist_aliases_cover_311() -> None:
    assert "three eleven" in stylized_numeric_aliases("311", "MusicArtist")


def test_non_artist_titles_do_not_receive_speculative_aliases() -> None:
    assert stylized_numeric_aliases("Apollo 13", "Movie") == ()


def test_invalid_alias_limit_is_rejected() -> None:
    try:
        stylized_numeric_aliases("blink-182", "MusicArtist", maximum_aliases=0)
    except ValueError as error:
        assert str(error) == "maximum_aliases must be positive"
    else:
        raise AssertionError("expected ValueError")
