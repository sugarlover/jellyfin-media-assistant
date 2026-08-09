"""Conservative catalog-derived aliases for stylized media names.

These aliases are generated from the catalog record itself rather than guessed
from a user's query.  The first supported family is stylized numeric artist
names such as ``blink-182``, ``311``, and ``The 1975``.  Multiple plausible
spoken forms may be indexed, but they never collapse distinct Jellyfin IDs or
bypass the normal confidence and ambiguity rules.
"""

from __future__ import annotations

import re
import unicodedata


_NON_ALPHANUMERIC_RE = re.compile(r"[^a-z0-9]+")
_DIGIT_TOKEN_RE = re.compile(r"\b\d{1,4}\b")

_SMALL = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}


def _canonical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(_NON_ALPHANUMERIC_RE.sub(" ", without_marks).split())


def _cardinal_words(number: int) -> str:
    if not 0 <= number <= 9_999:
        raise ValueError("number must be between 0 and 9,999")
    if number < 20:
        return _SMALL[number]
    if number < 100:
        tens, remainder = divmod(number, 10)
        value = _TENS[tens * 10]
        return value if remainder == 0 else f"{value} {_SMALL[remainder]}"
    if number < 1_000:
        hundreds, remainder = divmod(number, 100)
        value = f"{_SMALL[hundreds]} hundred"
        return value if remainder == 0 else f"{value} {_cardinal_words(remainder)}"
    thousands, remainder = divmod(number, 1_000)
    value = f"{_cardinal_words(thousands)} thousand"
    return value if remainder == 0 else f"{value} {_cardinal_words(remainder)}"


def _digit_words(digits: str) -> str:
    return " ".join(_SMALL[int(character)] for character in digits)


def spoken_numeric_forms(digits: str) -> tuple[str, ...]:
    """Return bounded plausible spoken forms for one 1-4 digit token.

    Standard cardinal and digit-by-digit readings are always available.  Three-
    digit groups also receive the common ``one eighty two`` / ``three eleven``
    pattern.  Four-digit groups receive the common year/band-name pattern such
    as ``nineteen seventy five``.  These are aliases only; they do not redefine
    general number parsing.
    """

    if not digits.isdigit() or not 1 <= len(digits) <= 4:
        raise ValueError("digits must contain one to four decimal digits")

    number = int(digits)
    forms: list[str] = []

    def add(value: str) -> None:
        value = " ".join(value.split())
        if value and value not in forms:
            forms.append(value)

    add(_cardinal_words(number))
    add(_digit_words(digits))

    if len(digits) == 3 and digits[1:] != "00":
        add(f"{_SMALL[int(digits[0])]} {_cardinal_words(int(digits[1:]))}")
    elif len(digits) == 4 and digits[:2] != "00" and digits[2:] != "00":
        add(
            f"{_cardinal_words(int(digits[:2]))} "
            f"{_cardinal_words(int(digits[2:]))}"
        )

    return tuple(forms)


def stylized_numeric_aliases(
    title: str,
    media_type: str | None,
    *,
    maximum_aliases: int = 24,
) -> tuple[str, ...]:
    """Return conservative spoken-number aliases for stylized artist names.

    The initial scope is deliberately limited to ``MusicArtist`` records.  A
    future explicit alias source can extend other media types without making
    every numeric movie or song title adopt speculative pronunciations.
    """

    if not isinstance(title, str) or not title.strip():
        return ()
    normalized_type = _NON_ALPHANUMERIC_RE.sub("", (media_type or "").casefold())
    if normalized_type != "musicartist":
        return ()
    if maximum_aliases <= 0:
        raise ValueError("maximum_aliases must be positive")

    canonical = _canonical_text(title)
    matches = tuple(_DIGIT_TOKEN_RE.finditer(canonical))
    if not matches:
        return ()

    aliases = [canonical]
    offset = 0
    for match in matches:
        start, end = match.span()
        start += offset
        end += offset
        digits = match.group(0)
        next_aliases: list[str] = []
        for current in aliases:
            for spoken in spoken_numeric_forms(digits):
                value = " ".join(f"{current[:start]}{spoken}{current[end:]}".split())
                if value not in next_aliases:
                    next_aliases.append(value)
                if len(next_aliases) >= maximum_aliases:
                    break
            if len(next_aliases) >= maximum_aliases:
                break
        aliases = next_aliases
        # Later match positions were calculated against the original canonical
        # string. Multiple numeric tokens are rare; recompute through a bounded
        # cartesian expansion instead of relying on shifted offsets.
        if len(matches) > 1:
            break

    if len(matches) > 1:
        aliases = [canonical]
        for match in matches:
            digits = match.group(0)
            token = digits
            expanded: list[str] = []
            for current in aliases:
                for spoken in spoken_numeric_forms(digits):
                    value = re.sub(rf"\b{re.escape(token)}\b", spoken, current, count=1)
                    value = " ".join(value.split())
                    if value not in expanded:
                        expanded.append(value)
                    if len(expanded) >= maximum_aliases:
                        break
                if len(expanded) >= maximum_aliases:
                    break
            aliases = expanded

    return tuple(alias for alias in aliases if alias != canonical)[:maximum_aliases]
