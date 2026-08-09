# Frozen-reference contract tests

These tests characterize the stable pre-upgrade implementation stored under
`reference/current-working`.

They intentionally inspect the frozen source rather than importing the full
Home Assistant integration. This keeps the first test layer independent of a
Home Assistant installation, Jellyfin server, network connection, and secrets.

The tests are not an endorsement of the current search behavior. They document
the boundary that the new robust-search implementation must preserve or change
only through an explicit, reviewed contract decision.
