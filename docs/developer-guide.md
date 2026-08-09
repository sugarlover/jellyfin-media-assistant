# Developer Guide

This guide covers the repository workflow for contributors. For runtime design, read [Architecture](architecture.md) first.

## Repository layout

```text
custom_components/jellyfin_assist/   Home Assistant integration runtime
  matching/                          title/context matching engine
  search/                            Jellyfin catalog, cache, retrieval, response
tests/                               unit, Home Assistant-boundary, release tests
tools/                               local release/privacy/dependency audit tools
docs/                                public user and contributor documentation
reference/current-working/           sanitized compatibility fixtures, not install files
```

`reference/current-working/` exists for a small number of compatibility tests. It is not a second copy of the supported installation and should not be used as setup instructions.

## Local Python environment

GitHub CI currently tests with Python 3.12.

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

On macOS/Linux, use the equivalent `.venv/bin/python` path.

The local test environment uses lightweight Home Assistant stubs where practical; you do not need a full Home Assistant installation to run the main regression suite.

## Standard validation gates

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tools.configuration_surface_audit
.\.venv\Scripts\python.exe -m tools.jellyha_dependency_audit
.\.venv\Scripts\python.exe -m tools.repository_packaging_audit
```

Before committing, also run:

```powershell
git diff --check
```

### What the audits protect

- `configuration_surface_audit` — secrets/credential-adjacent values, private network literals, household entity IDs/paths, and retired configuration debt.
- `jellyha_dependency_audit` — confirms JellyHA remains provenance only and cannot silently re-enter the runtime dependency surface.
- `repository_packaging_audit` — checks public beta version, HACS metadata, root release files, documentation surface, and retired runtime artifacts.

## Test organization

- `tests/matching/` — normalization, deterministic, fuzzy, phonetic, context, and decision behavior.
- `tests/search/` — catalog loading/cache/index/planning/retrieval/response behavior.
- `tests/homeassistant/` — config flow, services, orchestration, queue, playback, diagnostics, advancement, and voice-boundary tests using HA stubs.
- `tests/release/` — public packaging, namespace, voice onboarding, privacy/configuration, and dependency retirement gates.
- `tests/reference/` — limited sanitized compatibility fixtures retained from earlier architecture boundaries.
- `tests/tools/` — standalone developer/search tooling tests.

Behavior changes should normally add a regression test in the narrowest relevant layer plus a higher-level test when an integration contract changes.

## Working on search

Search intentionally has two layers:

1. `search/` finds and structures a bounded candidate pool from the Jellyfin catalog.
2. `matching/` decides how query text and context compare to those candidates.

Avoid solving matching problems by making Jellyfin queries globally broad and avoid solving catalog problems by stuffing remote-query behavior into the matcher.

A safe matcher change should answer:

- Which new equivalence or error pattern should be accepted?
- Which false positive could that introduce?
- At what tier should it run (deterministic, context, fuzzy, phonetic)?
- What ambiguity margin should remain?
- Which regression examples demonstrate both the new match and the safety boundary?

## Working on voice commands

The packaged grammar is:

```text
custom_components/jellyfin_assist/custom_sentences/en/jellyfin_assist_media.yaml
```

When adding a phrase:

1. Put specific sentence patterns before broad wildcard patterns.
2. Avoid bare player wildcards that could capture native Home Assistant media commands.
3. Update `voice.py` only when the new sentence requires new slot parsing/routing.
4. Update `tests/homeassistant/test_voice_intents.py` and voice-sentence onboarding tests.
5. Update [Voice & Assist Command Guide](voice-commands.md) for new public syntax.

## Working on playback

Chromecast is the supported beta path. Keep platform-specific decisions behind the playback strategy boundary.

`orchestration.py` should decide **what** to play; `media_actions.py` should coordinate queue/session behavior; `playback.py` should prepare one concrete Jellyfin item; a playback strategy should decide **how** that item is delivered to a platform.

Do not hard-code a household player or alias in playback code.

## Working on queue behavior

Persistent queue semantics live in `queue_store.py`. Conversational/action semantics live in `queue_control.py`. Automatic end-of-item behavior lives in `advancement.py`.

When changing queue state, consider:

- persistence across Home Assistant restart;
- current/previous/next/upcoming response compatibility;
- Repeat Item and Repeat Queue interaction;
- shuffle preserving the currently playing item;
- Play versus Add session semantics; and
- advancement safety when Home Assistant player states change unexpectedly.

## Working on configuration

Connection values belong in config-entry data. User-selectable behavior belongs in config-entry options.

If persisted keys change:

- update `configuration.py` normalization;
- add an idempotent migration in `async_migrate_entry` as needed;
- preserve unknown keys unless there is a deliberate reason to remove them;
- update diagnostics with redaction in mind; and
- update [Configuration](configuration.md).

## Live testing

Automated tests are necessary but not sufficient for playback behavior. For changes that touch Jellyfin networking, Assist registration, media-player behavior, or advancement, live-test against a Home Assistant/Jellyfin installation when possible.

A useful live validation report includes:

- Home Assistant version and installation type;
- Jellyfin version;
- media-player platform;
- exact request/action;
- returned response;
- observed playback/queue result; and
- redacted diagnostics when something fails.

## Public-release safety

Never commit:

- `.env` containing real values;
- Home Assistant `secrets.yaml`;
- Jellyfin API keys;
- real Jellyfin user IDs when they identify a private instance;
- private IP addresses/hostnames from a household setup;
- real household entity IDs or NAS filesystem paths; or
- Home Assistant `.storage` data.

Use `.env.example`, `media_player.example_*`, and clearly artificial placeholder values in fixtures/docs.

## Third-party provenance

Jellyfin Media Assistant is not dependent on JellyHA at runtime, but portions of the native Jellyfin implementation were adapted from JellyHA. Preserve `THIRD_PARTY_NOTICES.md`, `docs/provenance/jellyha.json`, and the retained JellyHA MIT license when modifying adapted code.
