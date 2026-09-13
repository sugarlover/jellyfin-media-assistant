# Generic Series Playback Fallback — Hermes Kanban Plan

Status: FROZEN
Parent feature: Generic Series Playback Fallback
Dependency rule: a child card may start only after its parent is DONE with an
accepted clean commit.

Each card gets exactly one detached engineering run at a time. A card is DONE
only after:

1. focused tests pass;
2. repository-standard validation passes;
3. candidate is frozen;
4. independent reviewer returns mechanically valid ACCEPT;
5. accepted commit is recorded;
6. repository is clean.

If any gate fails, the card remains blocked with the run ID and concrete
failure reason. The next card starts from the parent's accepted clean HEAD.

---

## JMA-SERIES-001 — Add ordered whole-series episode lookup

### Goal

Provide one native read-only lookup that returns all episodes belonging to a
resolved Jellyfin Series in deterministic season/episode order.

### Scope

- Reuse the existing Jellyfin API client/query machinery.
- Retrieve Episode items under one resolved Series.
- Sort by ParentIndexNumber then IndexNumber ascending.
- Preserve enough season/episode metadata for later policy code.
- Add focused API/service tests for ordering and returned content.
- Keep existing search_season behavior unchanged.

### Explicitly out of scope

- No generic-series fallback policy.
- No 15-episode rule.
- No Season 0 filtering policy beyond faithfully returning metadata.
- No orchestration behavior change.
- No queue/playback changes.
- No voice grammar changes.
- No public documentation changes.

### Acceptance evidence

- New whole-series lookup is available through the existing JMA service/action
  boundary or an equivalently narrow existing native boundary.
- Existing explicit-season lookup behavior still passes.
- Focused tests prove ordered multi-season episode retrieval.
- Full repository validation passes.
- Independent reviewer ACCEPT.
- Clean accepted commit recorded.

---

## JMA-SERIES-002 — Implement pure generic-series episode selection policy

Parent: JMA-SERIES-001

### Goal

Implement the frozen selection algorithm as a deterministic, side-effect-free
policy over an already retrieved list of episode metadata.

### Scope

Given available episode metadata:

- exclude Season 0 / Specials for generic-series selection;
- order regular episodes by season then episode;
- de-duplicate episodes;
- if Season 1 has >=15 available episodes, return all Season 1 episodes only;
- if Season 1 has 1..14, return all Season 1 episodes then later regular
  episodes until total reaches 15 or the series is exhausted;
- if Season 1 has none, return the first 15 regular episodes, or all when fewer
  than 15 exist;
- return an empty result when no regular episodes exist.

Add focused unit tests for the complete policy matrix, including missing episode
numbers and duplicate protection.

### Explicitly out of scope

- No Jellyfin network/service changes.
- No orchestration wiring.
- No Play/Add behavior changes.
- No explicit-season behavior changes.
- No voice grammar changes.
- No public documentation changes.

### Acceptance evidence

Focused tests mechanically prove:

1. S1 >15 -> all S1 only.
2. S1 =15 -> all 15.
3. S1 1..14 -> top up chronologically to 15.
4. Entire series <15 -> all available regular episodes.
5. No S1 -> first 15 regular episodes.
6. Specials excluded.
7. Missing episode numbers skipped without reordering.
8. Duplicate episode identities do not duplicate the plan.
9. No regular episodes -> empty selection.

Full repository validation passes, independent reviewer ACCEPTs, and a clean
accepted commit is recorded.

---

## JMA-SERIES-003 — Wire generic-series orchestration to the accepted policy

Parent: JMA-SERIES-002

### Goal

Replace the current implicit "generic Series means Season 1" behavior with the
accepted whole-series lookup + pure selection policy while preserving explicit
season behavior and existing queue/playback semantics.

### Scope

- Generic Series request:
  - retrieve the whole-series episode list using Card 001;
  - apply the Card 002 selector;
  - build the playback plan from that selection;
  - return a truthful no-playable-episodes failure when selection is empty.
- Explicit season request:
  - continue using season-bounded behavior;
  - queue all available episodes in that season;
  - never top up from another season;
  - one available episode means a one-item plan.
- Preserve existing Play versus Add behavior.
- Add higher-level orchestration regression tests.
- Update docs/voice-commands.md so generic show requests no longer promise
  unconditional Season 1 behavior.
- Update docs/architecture.md only as necessary to describe the new resolver
  behavior accurately.

### Explicitly out of scope

- No watched/progress-aware Resume command.
- No new voice grammar required solely for this behavior.
- No player-resolution changes.
- No queue-store semantics changes.
- No advancement changes.
- No playback-strategy changes.

### Acceptance evidence

Higher-level tests prove:

- generic S1 >15 uses all S1 only;
- short S1 tops up to 15;
- absent S1 starts from earliest regular season;
- fewer than 15 total uses all regular episodes;
- specials remain excluded;
- explicit season with 1 or several episodes remains season-bounded;
- no regular episodes returns a clean failure;
- Play and Add consume the resulting plan with existing semantics.

Repository-standard validation must include:

- pytest regression suite;
- configuration surface audit;
- JellyHA dependency audit;
- repository packaging audit;
- git diff --check.

Candidate is frozen, independent reviewer returns ACCEPT, accepted commit is
recorded, and repository is clean.

---

## Deferred follow-up

A future independent feature may add watched/progress-aware commands such as:

- Resume Supernatural

That feature is intentionally not part of this board.
