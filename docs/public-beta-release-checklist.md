# Public beta release checklist

This checklist separates repository changes that can be validated while the GitHub repository is private from publication steps that require a public repository.

## Repository-ready gate

- [ ] `pytest` passes.
- [ ] `tools.configuration_surface_audit` passes.
- [ ] `tools.jellyha_dependency_audit` passes.
- [ ] hassfest GitHub Action passes.
- [ ] Root `README.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, `CHANGELOG.md`, and `hacs.json` are present.
- [ ] `manifest.json` contains `documentation`, `issue_tracker`, `codeowners`, `name`, `domain`, and a prerelease version.
- [ ] No JellyHA runtime dependency remains.
- [ ] No external queue service, port 8787, manual scripts, helpers, REST commands, `intent_script`, or queue-advancement automation is required.
- [ ] Managed Assist sentence provisioning works from a clean/missing installed sentence file.

## GitHub publication gate

- [ ] Add an original `brand/icon.png` before enabling HACS validation.
- [ ] Make `sugarlover/jellyfin-media-assistant` public.
- [ ] Enable GitHub Issues.
- [ ] Set repository description to: `Jellyfin search, queue, and Chromecast playback for Home Assistant Assist.`
- [ ] Add repository topics: `home-assistant`, `hacs`, `jellyfin`, `voice-assistant`, `chromecast`, `media-player`.
- [ ] Add the HACS validation workflow with category `integration` and no ignored checks.
- [ ] Confirm HACS validation passes.
- [ ] Confirm hassfest passes after publication.

## Clean-install acceptance gate

Use a clean Home Assistant test state or remove the existing integration only after taking a backup.

- [ ] Install from HACS as a custom repository.
- [ ] Restart Home Assistant.
- [ ] Add Jellyfin Media Assistant through the UI.
- [ ] Validate Jellyfin server URL/API key/user ID.
- [ ] Configure default and allowed playback targets.
- [ ] Confirm the managed English Assist sentence file is provisioned automatically.
- [ ] Confirm diagnostics show all 27 intent handlers registered and voice sentences current.
- [ ] Play a movie on Chromecast.
- [ ] Play an album and confirm automatic queue advancement.
- [ ] Verify What's Playing, Queue Status, Shuffle, Next, Repeat Queue, Repeat Off.
- [ ] Verify ambiguous search followed by numbered selection.
- [ ] Restart Home Assistant and confirm queue state persists.
- [ ] Download diagnostics and confirm secrets are redacted.

## Release gate

- [ ] Set manifest/constant version to the release identifier being published.
- [ ] Update `CHANGELOG.md` with the release date.
- [ ] Merge the release candidate into the intended default/release branch.
- [ ] Create a full GitHub prerelease named/tagged `v0.1.0-beta.1` (a tag alone is not sufficient for HACS release selection).
- [ ] Install/update that exact release through HACS once more.
- [ ] Publish beta testing notes with supported-platform limitations and issue-reporting guidance.
