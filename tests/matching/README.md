# Matching-engine tests

These tests build the future Jellyfin Media Assistant matcher in isolated,
dependency-aware layers. None of these modules currently registers a Home
Assistant action, contacts Jellyfin, or invokes playback or queue code.

Current layers:

1. `test_normalization.py` verifies deterministic, labeled representations for
   Unicode, capitalization, diacritics, punctuation, number words, ordinals,
   and joined/separated words.
2. `test_deterministic.py` verifies deterministic full-title equivalence and
   conservative whole-token title-fragment classification, relative scoring,
   ranking, margins, and tie preservation.
3. `test_context.py` verifies that explicit media type, artist, album, series,
   and year can rank already-plausible title matches while title and context
   scores remain separate. Known media-type contradictions are rejected;
   missing catalog metadata remains neutral; equal candidates remain
   ambiguous.
4. `test_decision.py` verifies conservative automatic-selection rules. A unique
   deterministic candidate may be selected, while ties, insufficient margins,
   and explicit context contradictions prevent automatic selection. Thresholds
   remain centralized and method-specific.
5. `test_fuzzy.py` verifies a controlled lexical-error layer for insertions,
   deletions, substitutions, adjacent transpositions, repeated or missing
   characters, adjacent-key substitutions, and tightly limited multi-edit
   matches. Short titles and combined word-boundary-plus-typo changes are
   rejected; deterministic equivalence is never duplicated as fuzzy. Numeric
   signatures prevent one recognized number from being fuzzily corrected into
   another, while a misspelled ordinal may compare against a safe catalog word
   alias such as `13th` → `thirteenth`.
6. `test_phonetic.py` verifies the lowest-confidence phonetic/ASR layer. It
   uses an auditable homophone table and conservative token signatures, requires
   equal token counts, rejects very short or unrelated inputs, and reports
   lexical and phonetic scores separately.
7. `test_pipeline.py` verifies the tiered full-title equivalence, whole-token
   title-fragment, fuzzy, then phonetic pipeline. Lower-confidence candidates cannot compete with a
   surviving stronger tier. Context contradictions block automatic choice,
   fuzzy multi-edit matches require support, and phonetic matches require
   especially strong context and margins.

Later layers will add catalog query planning and retrieval, candidate
aggregation, diagnostics serialization, and the Home Assistant action adapter.

## Stylized numeric catalog aliases

Catalog-derived aliases are currently limited to `MusicArtist` names containing
1-4 digit groups. They cover standard, digit-by-digit, and common grouped spoken
forms such as `blink-182` → `blink one eighty two`, while preserving separate
Jellyfin IDs and normal ambiguity decisions. Segmented pronunciations such as
`one eighty two`, `three eleven`, and `nineteen seventy five` are deliberately
excluded from ordinary cardinal arithmetic; only catalog-derived aliases may
interpret those forms.

## Audio spoken-title collision safety

The unified decision layer treats distinct `Audio` records with the same
punctuation- and conventional-number-insensitive spoken title as ambiguous when
lexical method scoring alone would otherwise choose one. For example,
`three am` returns both `3 AM` and `3 A.M.`. Explicit artist, album, or year
context may resolve the collision only when it positively matches the winner
and contradicts every rival. This rule does not create candidates and does not
change existing equal-score tie reasons.
