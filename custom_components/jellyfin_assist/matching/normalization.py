"""Deterministic title normalization and variant generation.

This module deliberately performs no fuzzy matching, phonetic matching,
candidate ranking, or automatic-selection decision.  It creates labeled text
representations that later ranking stages can score according to their risk.
Keeping each transformation labeled prevents a broad normalization rule from
silently becoming an unconditional match.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALPHANUMERIC_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_NUMERIC_ORDINAL_SPACING_RE = re.compile(r"\b(\d+)\s+(st|nd|rd|th)\b")
_NUMERIC_ORDINAL_RE = re.compile(r"\b(\d{1,4})(st|nd|rd|th)\b", flags=re.IGNORECASE)
_NUMERIC_TOKEN_RE = re.compile(r"\b\d+(?:st|nd|rd|th)?\b", flags=re.IGNORECASE)


class VariantMethod(StrEnum):
    """Transformation labels retained for scoring and diagnostics."""

    ORIGINAL = "original"
    UNICODE_CASEFOLD = "unicode_casefold"
    DIACRITIC_FOLD = "diacritic_fold"
    PUNCTUATION_SPACING = "punctuation_spacing"
    NUMBER_WORDS_TO_DIGITS = "number_words_to_digits"
    NUMERIC_ORDINAL_SPACING = "numeric_ordinal_spacing"
    NUMERIC_ORDINAL_TO_WORDS = "numeric_ordinal_to_words"
    COMPACT_SPACING = "compact_spacing"


_METHOD_ORDER = {method: index for index, method in enumerate(VariantMethod)}


@dataclass(frozen=True, slots=True)
class TextVariant:
    """One normalized representation and every method that produced it."""

    value: str
    methods: tuple[VariantMethod, ...]


@dataclass(frozen=True, slots=True)
class TextProfile:
    """The original text and its deterministic labeled variants."""

    original: str
    variants: tuple[TextVariant, ...]

    @property
    def values(self) -> frozenset[str]:
        """Return all unique variant values."""

        return frozenset(variant.value for variant in self.variants)

    def get(self, value: str) -> TextVariant | None:
        """Return a generated variant by exact normalized value."""

        return next((variant for variant in self.variants if variant.value == value), None)


@dataclass(frozen=True, slots=True)
class SharedVariant:
    """A representation shared by two independently generated profiles."""

    value: str
    left_methods: tuple[VariantMethod, ...]
    right_methods: tuple[VariantMethod, ...]


_CARDINAL_SMALL = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

_CARDINAL_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

_ORDINAL_SMALL = {
    "zeroth": 0,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
}

_ORDINAL_TENS = {
    "twentieth": 20,
    "thirtieth": 30,
    "fortieth": 40,
    "fiftieth": 50,
    "sixtieth": 60,
    "seventieth": 70,
    "eightieth": 80,
    "ninetieth": 90,
}



_CARDINAL_SMALL_BY_VALUE = {value: word for word, value in _CARDINAL_SMALL.items()}
_CARDINAL_TENS_BY_VALUE = {value: word for word, value in _CARDINAL_TENS.items()}
_ORDINAL_SMALL_BY_VALUE = {value: word for word, value in _ORDINAL_SMALL.items()}
_ORDINAL_TENS_BY_VALUE = {value: word for word, value in _ORDINAL_TENS.items()}

_NUMBER_WORDS = (
    set(_CARDINAL_SMALL)
    | set(_CARDINAL_TENS)
    | set(_ORDINAL_SMALL)
    | set(_ORDINAL_TENS)
    | {"hundred", "hundredth", "thousand", "thousandth"}
)


def _collapse_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _casefold_unicode(value: str) -> str:
    return _collapse_whitespace(unicodedata.normalize("NFKC", value).casefold())


def _fold_diacritics(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _collapse_whitespace(unicodedata.normalize("NFKC", without_marks))


def _space_punctuation(value: str) -> str:
    # Underscore is a word character in Python regular expressions, but for
    # media titles it behaves like a separator rather than a meaningful letter.
    value = value.replace("_", " ")
    return _collapse_whitespace(_NON_ALPHANUMERIC_RE.sub(" ", value))


def _ordinal_suffix(number: int) -> str:
    remainder_100 = number % 100
    if 11 <= remainder_100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _number_phrase_end(tokens: list[str], start: int) -> int:
    """Return the end of the contiguous number-word phrase at ``start``.

    ``and`` is included only when it connects two recognized number words.
    This lets the validator reject segmented or additive speech patterns as a
    whole instead of partially converting them into unrelated numbers.
    """

    index = start
    while index < len(tokens):
        token = tokens[index]
        if token in _NUMBER_WORDS:
            index += 1
            continue
        if (
            token == "and"
            and index > start
            and index + 1 < len(tokens)
            and tokens[index + 1] in _NUMBER_WORDS
        ):
            index += 1
            continue
        break
    return index


def _is_conservative_number_phrase(tokens: list[str]) -> bool:
    """Return whether ``tokens`` form one conventional English number.

    The ordinary cardinal parser must not reinterpret segmented artist-name
    pronunciations such as ``one eighty two``, ``three eleven``, or
    ``nineteen seventy five`` as arithmetic sums. Those forms are handled by
    catalog-derived stylized aliases instead.
    """

    if not tokens:
        return False

    semantic = [token for token in tokens if token != "and"]
    if not semantic:
        return False

    for index, token in enumerate(tokens):
        if token != "and":
            continue
        if index == 0 or index == len(tokens) - 1:
            return False
        if tokens[index - 1] not in {"hundred", "thousand"}:
            return False
        if tokens[index + 1] not in _NUMBER_WORDS:
            return False

    ordinal_tokens = (
        set(_ORDINAL_SMALL)
        | set(_ORDINAL_TENS)
        | {"hundredth", "thousandth"}
    )
    ordinal_positions = [
        index for index, token in enumerate(semantic) if token in ordinal_tokens
    ]
    if len(ordinal_positions) > 1:
        return False
    if ordinal_positions and ordinal_positions[0] != len(semantic) - 1:
        return False

    for previous, current in zip(semantic, semantic[1:], strict=False):
        if previous in _CARDINAL_SMALL:
            if current in _CARDINAL_TENS:
                return False
            if current in _CARDINAL_SMALL:
                return False
            if current in _ORDINAL_SMALL or current in _ORDINAL_TENS:
                return False

        if previous in _CARDINAL_TENS:
            if current in _CARDINAL_TENS:
                return False
            if current in _CARDINAL_SMALL and _CARDINAL_SMALL[current] > 9:
                return False
            if current in _ORDINAL_TENS:
                return False
            if current in _ORDINAL_SMALL and _ORDINAL_SMALL[current] > 9:
                return False

        if previous in ordinal_tokens:
            return False

    return True


def _consume_number_phrase(tokens: list[str], start: int) -> tuple[str, int] | None:
    """Consume a conservative English number phrase starting at ``start``.

    The parser supports common cardinals and ordinals through the thousands.
    It stops at the first non-number token and returns ``None`` when the token
    at ``start`` is not a recognized number word.
    """

    if tokens[start] not in _NUMBER_WORDS:
        return None

    phrase_end = _number_phrase_end(tokens, start)
    if not _is_conservative_number_phrase(tokens[start:phrase_end]):
        return None

    index = start
    current = 0
    total = 0
    saw_number = False
    ordinal_value: int | None = None

    while index < len(tokens):
        token = tokens[index]

        if token in _CARDINAL_SMALL:
            current += _CARDINAL_SMALL[token]
            saw_number = True
        elif token in _CARDINAL_TENS:
            current += _CARDINAL_TENS[token]
            saw_number = True
        elif token == "hundred":
            current = max(current, 1) * 100
            saw_number = True
        elif token == "thousand":
            total += max(current, 1) * 1000
            current = 0
            saw_number = True
        elif token in _ORDINAL_SMALL:
            ordinal_value = total + current + _ORDINAL_SMALL[token]
            index += 1
            break
        elif token in _ORDINAL_TENS:
            ordinal_value = total + current + _ORDINAL_TENS[token]
            index += 1
            break
        elif token == "hundredth":
            ordinal_value = total + max(current, 1) * 100
            index += 1
            break
        elif token == "thousandth":
            ordinal_value = total + max(current, 1) * 1000
            index += 1
            break
        else:
            break

        index += 1

        # Permit the optional English connector only inside a number phrase,
        # such as "one hundred and one".  It is never consumed by itself.
        if (
            index < len(tokens) - 1
            and tokens[index] == "and"
            and tokens[index + 1] in _NUMBER_WORDS
        ):
            index += 1

    if not saw_number and ordinal_value is None:
        return None

    if ordinal_value is not None:
        return _ordinal_suffix(ordinal_value), index

    return str(total + current), index


def _replace_number_words(value: str) -> str:
    tokens = value.split()
    output: list[str] = []
    index = 0

    while index < len(tokens):
        if tokens[index] in _NUMBER_WORDS:
            phrase_end = _number_phrase_end(tokens, index)
            phrase_tokens = tokens[index:phrase_end]
            if not _is_conservative_number_phrase(phrase_tokens):
                output.extend(phrase_tokens)
                index = phrase_end
                continue

        consumed = _consume_number_phrase(tokens, index)
        if consumed is None:
            output.append(tokens[index])
            index += 1
            continue

        replacement, index = consumed
        output.append(replacement)

    return " ".join(output)


def _normalize_numeric_ordinal_spacing(value: str) -> str:
    return _NUMERIC_ORDINAL_SPACING_RE.sub(r"\1\2", value)


def _cardinal_words(number: int) -> str | None:
    """Return conservative English cardinal words for 0 through 9,999."""

    if not 0 <= number <= 9_999:
        return None
    if number < 20:
        return _CARDINAL_SMALL_BY_VALUE[number]
    if number < 100:
        tens, remainder = divmod(number, 10)
        words = _CARDINAL_TENS_BY_VALUE[tens * 10]
        if remainder:
            words = f"{words} {_CARDINAL_SMALL_BY_VALUE[remainder]}"
        return words
    if number < 1_000:
        hundreds, remainder = divmod(number, 100)
        words = f"{_CARDINAL_SMALL_BY_VALUE[hundreds]} hundred"
        if remainder:
            remainder_words = _cardinal_words(remainder)
            assert remainder_words is not None
            words = f"{words} {remainder_words}"
        return words

    thousands, remainder = divmod(number, 1_000)
    thousands_words = _cardinal_words(thousands)
    assert thousands_words is not None
    words = f"{thousands_words} thousand"
    if remainder:
        remainder_words = _cardinal_words(remainder)
        assert remainder_words is not None
        words = f"{words} {remainder_words}"
    return words


def _ordinal_words(number: int) -> str | None:
    """Return conservative English ordinal words for 0 through 9,999."""

    if not 0 <= number <= 9_999:
        return None
    if number < 20:
        return _ORDINAL_SMALL_BY_VALUE[number]
    if number < 100:
        tens, remainder = divmod(number, 10)
        if remainder == 0:
            return _ORDINAL_TENS_BY_VALUE[number]
        return f"{_CARDINAL_TENS_BY_VALUE[tens * 10]} {_ORDINAL_SMALL_BY_VALUE[remainder]}"
    if number < 1_000:
        hundreds, remainder = divmod(number, 100)
        prefix = f"{_CARDINAL_SMALL_BY_VALUE[hundreds]} hundred"
        if remainder == 0:
            return f"{_CARDINAL_SMALL_BY_VALUE[hundreds]} hundredth"
        remainder_words = _ordinal_words(remainder)
        assert remainder_words is not None
        return f"{prefix} {remainder_words}"

    thousands, remainder = divmod(number, 1_000)
    thousands_words = _cardinal_words(thousands)
    assert thousands_words is not None
    prefix = f"{thousands_words} thousand"
    if remainder == 0:
        return f"{thousands_words} thousandth"
    remainder_words = _ordinal_words(remainder)
    assert remainder_words is not None
    return f"{prefix} {remainder_words}"


def _replace_numeric_ordinals_with_words(value: str) -> str:
    """Expand valid numeric ordinals without touching ordinary title digits."""

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        suffix = match.group(2).casefold()
        if _ordinal_suffix(number) != f"{number}{suffix}":
            return match.group(0)
        words = _ordinal_words(number)
        return words if words is not None else match.group(0)

    return _NUMERIC_ORDINAL_RE.sub(replace, value)


def numeric_token_signature(text: str) -> tuple[str, ...]:
    """Return recognized numeric tokens in a stable digit/ordinal form.

    This is used as a fuzzy-matching safety check. A typo may be compared with
    a numeric word alias when the typo itself has no recognized number, but two
    explicit or correctly spelled numbers must agree. This prevents titles such
    as ``Apollo 13`` and ``Apollo 14`` or ``thirtieth`` and ``thirteenth`` from
    becoming fuzzy equivalents merely because their letters are close.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized = _space_punctuation(_fold_diacritics(_casefold_unicode(text)))
    if not normalized:
        return ()
    normalized = _replace_number_words(normalized)
    normalized = _normalize_numeric_ordinal_spacing(normalized)
    return tuple(match.casefold() for match in _NUMERIC_TOKEN_RE.findall(normalized))


def spoken_title_signature(text: str) -> str:
    """Return a conservative speech-equivalence signature for a title.

    The signature folds Unicode case, diacritics, punctuation, conventional
    English number words, ordinal spacing, and whitespace.  It is intended
    only for detecting collisions between already plausible catalog matches;
    it does not create a match by itself.  Segmented artist-name pronunciations
    such as ``one eighty two`` remain unparsed by the ordinary number grammar.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized = _space_punctuation(_fold_diacritics(_casefold_unicode(text)))
    if not normalized:
        raise ValueError("text must not be empty")
    normalized = _replace_number_words(normalized)
    normalized = _normalize_numeric_ordinal_spacing(normalized)
    return normalized.replace(" ", "")


def build_text_profile(text: str) -> TextProfile:
    """Build a deterministic, deduplicated profile for a media title/query.

    Raises:
        TypeError: If ``text`` is not a string.
        ValueError: If ``text`` is empty after whitespace normalization.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    original = _collapse_whitespace(text)
    if not original:
        raise ValueError("text must not be empty")

    methods_by_value: dict[str, set[VariantMethod]] = {}

    def add(value: str, method: VariantMethod) -> None:
        value = _collapse_whitespace(value)
        if value:
            methods_by_value.setdefault(value, set()).add(method)

    add(original, VariantMethod.ORIGINAL)

    casefolded = _casefold_unicode(original)
    add(casefolded, VariantMethod.UNICODE_CASEFOLD)

    diacritic_folded = _fold_diacritics(casefolded)
    add(diacritic_folded, VariantMethod.DIACRITIC_FOLD)

    normalized_seeds = tuple(methods_by_value)
    for seed in normalized_seeds:
        if seed == original and seed != casefolded:
            continue
        add(_space_punctuation(seed), VariantMethod.PUNCTUATION_SPACING)

    punctuation_values = tuple(methods_by_value)
    for seed in punctuation_values:
        number_variant = _replace_number_words(seed)
        if number_variant != seed:
            add(number_variant, VariantMethod.NUMBER_WORDS_TO_DIGITS)

        ordinal_variant = _normalize_numeric_ordinal_spacing(seed)
        if ordinal_variant != seed:
            add(ordinal_variant, VariantMethod.NUMERIC_ORDINAL_SPACING)

    # Re-run numeric ordinal spacing after number-word conversion so a future
    # parser extension that emits spaced suffixes remains deterministic.
    number_values = tuple(methods_by_value)
    for seed in number_values:
        ordinal_variant = _normalize_numeric_ordinal_spacing(seed)
        if ordinal_variant != seed:
            add(ordinal_variant, VariantMethod.NUMERIC_ORDINAL_SPACING)

    # Numeric ordinal titles also receive a word alias. This reverse alias is
    # intentionally limited to explicit ordinal suffixes (for example 13th),
    # so ordinary stylized digits such as blink-182 are not rewritten. It lets
    # the fuzzy layer compare a transcription typo such as "thirteeth" with
    # the safe catalog alias "thirteenth".
    ordinal_values = tuple(methods_by_value)
    for seed in ordinal_values:
        word_variant = _replace_numeric_ordinals_with_words(seed)
        if word_variant != seed:
            add(word_variant, VariantMethod.NUMERIC_ORDINAL_TO_WORDS)

    # Compact forms are intentionally labeled.  They are useful for titles
    # such as "Run-Around" and "3 AM", but later scoring must treat them more
    # cautiously than case or punctuation equivalence.
    compact_seeds = tuple(methods_by_value)
    for seed in compact_seeds:
        compact = seed.replace(" ", "")
        if compact != seed:
            add(compact, VariantMethod.COMPACT_SPACING)

    variants = tuple(
        TextVariant(
            value=value,
            methods=tuple(sorted(methods, key=_METHOD_ORDER.__getitem__)),
        )
        for value, methods in methods_by_value.items()
    )
    return TextProfile(original=original, variants=variants)


def find_shared_variants(left: TextProfile, right: TextProfile) -> tuple[SharedVariant, ...]:
    """Return every exact representation shared by two text profiles."""

    right_by_value = {variant.value: variant for variant in right.variants}
    shared: list[SharedVariant] = []

    for left_variant in left.variants:
        right_variant = right_by_value.get(left_variant.value)
        if right_variant is None:
            continue
        shared.append(
            SharedVariant(
                value=left_variant.value,
                left_methods=left_variant.methods,
                right_methods=right_variant.methods,
            )
        )

    return tuple(shared)
