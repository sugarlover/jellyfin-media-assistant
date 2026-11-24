"""Pipeline regression tests for the one-token contractive-split gate (T1).

These drive the REAL search pipeline (``CatalogIndex.search`` -> ranking ->
``decide_search_ranking``) and assert the FULL outcome for the contractive
split case: a spoken "you're idle" transcript that STT renders as the
space-split "you re idle" (3 tokens) must line up against the catalog title
"Your Idol" (2 tokens) through the widened phonetic tier, land on the
COMMON_HOMOPONE score (74), and resolve to CONFIRMATION_REQUIRED (not
auto-selected).  A genuine Soundex-collision merge (not a contractive split)
must stay NOT_FOUND.  No floor/threshold/auto-select behavior is changed.
"""

from __future__ import annotations

from custom_components.jellyfin_assist.matching.decision import MatchDecisionStatus
from custom_components.jellyfin_assist.matching.pipeline import LexicalMatchFamily
from custom_components.jellyfin_assist.search.catalog_index import CatalogIndex


def _item(item_id: str, name: str, media_type: str) -> dict[str, object]:
    return {"Id": item_id, "Name": name, "Type": media_type}


def _build_index() -> CatalogIndex:
    # Synthetic fixture: the single catalog title under test.  No titles from
    # Fred's real catalog are added.
    return CatalogIndex.build([_item("your-idol-audio", "Your Idol", "Audio")])


def _build_idle_index() -> CatalogIndex:
    # Synthetic fixture for the second-splice-position test: the same spoken
    # word rendered as "idle" so the position-1 merge ("i"+"dol" -> "idol")
    # lines up against the homophone "idle" as a genuine sound-confusion
    # rather than an exact value match.  No titles from Fred's real catalog.
    return CatalogIndex.build([_item("your-idle-audio", "Your Idle", "Audio")])


def _decide(
    query: str,
    index: CatalogIndex | None = None,
) -> tuple[MatchDecisionStatus, LexicalMatchFamily | None, int | None]:
    """Drive the real pipeline and return (status, active_family, top score)."""

    outcome = (index if index is not None else _build_index()).search(
        query, context=None
    )
    decision = outcome.decision
    top_score = (
        decision.alternatives[0].total_score
        if decision.alternatives
        else None
    )
    return decision.status, decision.active_family, top_score


def test_space_split_contractive_split_reaches_confirmation_required() -> None:
    # The live failure: STT splits "you're" into three tokens ("you re idle").
    # The widened phonetic gate now merges the adjacent pair (you + re ==
    # youre == your) and lines "idle" up against the homophone "idol", so the
    # full pipeline resolves to CONFIRMATION_REQUIRED at score 74.
    status, family, score = _decide("you re idle")

    assert status is MatchDecisionStatus.CONFIRMATION_REQUIRED
    assert family is LexicalMatchFamily.PHONETIC
    assert score == 74


def test_apostrophe_form_remains_confirmation_required_guard() -> None:
    # Regression guard: the apostrophe form already worked and must stay
    # CONFIRMATION_REQUIRED at 74 (no behavior shift from the gate change).
    status, family, score = _decide("you're idle")

    assert status is MatchDecisionStatus.CONFIRMATION_REQUIRED
    assert family is LexicalMatchFamily.PHONETIC
    assert score == 74


def test_spoken_your_idle_form_remains_confirmation_required_guard() -> None:
    # Regression guard: "your idle" (2 tokens, direct homophone) already
    # worked and must stay CONFIRMATION_REQUIRED at 74.
    status, family, score = _decide("your idle")

    assert status is MatchDecisionStatus.CONFIRMATION_REQUIRED
    assert family is LexicalMatchFamily.PHONETIC
    assert score == 74


def test_youre_idol_form_remains_confirmation_required_guard() -> None:
    # Regression guard: "You're idol" (2 tokens, both homophone groups)
    # already worked and must stay CONFIRMATION_REQUIRED at 74.
    status, family, score = _decide("You're idol")

    assert status is MatchDecisionStatus.CONFIRMATION_REQUIRED
    assert family is LexicalMatchFamily.PHONETIC
    assert score == 74


def test_soundex_collision_merge_is_not_a_contractive_split() -> None:
    # Negative (D2): a 3-token query whose adjacent merge is a bare Soundex
    # collision (NOT a true homophone/contractive split) must NOT match.
    # "youre" merges to Y600 — the SAME signature the candidate "your" carries
    # (a genuine collision) — so the single adjacent-pair splice condition is
    # met on its own.  But the full alignment does NOT line up (the third token
    # "not" does not sign against "idol"), so the gate rejects it and the
    # pipeline resolves to NOT_FOUND.  This is the exact D2 false-positive the
    # plan calls out: a colliding merge must not be treated as a split.
    status, _family, score = _decide("you re not")

    assert status is MatchDecisionStatus.NOT_FOUND
    assert score is None


def test_second_splice_position_contractive_split_reaches_confirmation_required() -> None:
    # D4: the gate must try EVERY adjacent splice point, not only the first.
    # Under the old loop (range(delta) == [0]) the position-1 splice was never
    # tried, so this case resolved to NOT_FOUND; now it must match.
    #
    # Query "your i dol" (3 tokens) vs title "Your Idle" (2 tokens).  The
    # contractive split lands at position 1: "i"+"dol" -> "idol", whose
    # signature equals the candidate's "idle" (both homophone group H19), and
    # the first token "your" already aligns positionally.  The position-0
    # splice ("your"+"i" -> "youri") does NOT match the candidate, so only
    # the second splice is valid — proving the loop reaches merge_index == 1.
    #
    # The merged "idol" against "idle" is a genuine homophone (COMMON_HOMOPONE
    # 74), not a Soundex value collision, so the full alignment lines up and
    # the pipeline confirms at the phonetic floor.
    status, family, score = _decide("your i dol", index=_build_idle_index())

    assert status is MatchDecisionStatus.CONFIRMATION_REQUIRED
    assert family is LexicalMatchFamily.PHONETIC
    assert score == 74
