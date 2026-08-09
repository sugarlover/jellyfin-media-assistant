# Contributing to Jellyfin Media Assistant

Thanks for helping improve Jellyfin Media Assistant.

The project is in public beta, so changes should favor small, reviewable behavior improvements with regression coverage over broad rewrites.

## Before changing code

1. Read [docs/architecture.md](docs/architecture.md) to identify the subsystem that owns the behavior.
2. Read [docs/developer-guide.md](docs/developer-guide.md) for local setup and test commands.
3. Check [docs/known-limitations.md](docs/known-limitations.md) to see whether the behavior is an intentional beta limitation.
4. For substantial behavior changes, open an issue first so the public contract can be discussed before implementation.

## Pull-request expectations

A pull request should:

- describe the user-visible problem and intended behavior;
- keep secrets, private network addresses, household entity IDs, and local paths out of tracked files;
- add or update tests for behavior changes;
- preserve existing response/action contracts unless the change explicitly updates them;
- avoid hard-coded aliases or device names that belong in a user's Home Assistant configuration;
- update user or developer documentation when the public behavior changes; and
- pass the standard test and audit gates.

Run before submitting:

```bash
python -m pytest -q
python -m tools.configuration_surface_audit
python -m tools.jellyha_dependency_audit
python -m tools.repository_packaging_audit
```

## Playback support

Chromecast is the supported playback platform for the first beta. Changes for other Home Assistant media-player platforms are welcome, but they should be isolated behind the playback strategy boundary and should not regress Chromecast behavior.

## AI-assisted contributions

AI-assisted code is welcome. Please review and test generated changes rather than treating generated output as authoritative. The project itself is extensively AI-assisted and relies on automated regression tests, explicit architecture boundaries, and live validation to keep changes understandable and safe.
