# Third-party notices

## JellyHA

Portions of Jellyfin Media Assistant's native Jellyfin item lookup and Chromecast playback implementation were adapted from JellyHA.

- Project: JellyHA
- Upstream: https://github.com/zupancicmarko/JellyHA
- Copyright: Copyright (c) 2026 zupancicmarko
- License: MIT
- Upstream manifest version observed during migration: 1.2.0
- Verified adaptation source commit: `6b8b2f679f922ea3a0d9c3c4b9827ee7053308f9`
- Verified adaptation source files: `custom_components/jellyha/services.py` and `custom_components/jellyha/api.py`

The upstream MIT license notice retained for the adapted code is stored at `docs/provenance/JELLYHA_LICENSE.txt`. Additional provenance details are recorded in `docs/provenance/jellyha.json`.

JellyHA is **not** a runtime dependency of Jellyfin Media Assistant. A full JellyHA source snapshot was used as a migration/contract fixture during private development but is intentionally not distributed in the public repository now that the runtime dependency has been retired.
