# Sanitized Home Assistant Behavioral Reference

These files preserve the sanitized Home Assistant configuration surface used by the
current pre-beta implementation.

They are **not** a complete Home Assistant configuration and should not be
copied over a live `/config` directory.

Jellyfin server URL, user ID, API key, default media player, and allowed playback
targets are owned by the Jellyfin Media Assistant config entry and options. Queue
state is persisted natively by the integration in Home Assistant storage. The
tracked Home Assistant YAML no longer requires Jellyfin REST commands, queue REST
commands, or a separately deployed queue service.

## Native queue advancement

Automatic queue advancement is now owned by the Jellyfin Media Assistant
integration. It listens to the configured playback targets and verifies both the
estimated completion percentage and Jellyfin item ID before advancing the queue.
Normal completion and safely rejected transitions remain silent; technical
failures create persistent notifications.

A separate Home Assistant queue-advancement automation is no longer part of the
public installation surface. Existing private deployments should disable their
legacy `Jellyfin Assist Queue Advancement - Chromecast` automation only after the
native integration listener is installed and ready for live validation.

## Helper entities

The public pre-beta reference no longer requires Jellyfin Media Assistant
`input_text` or `input_boolean` helpers. Pending multi-match selection state and persistent per-player queue state are
stored by the integration. Existing private helper entities may be retained
temporarily for rollback, but the current integration does not reference them.

## Native media orchestration

Jellyfin Media Assistant no longer requires any project-owned Home Assistant YAML
scripts. Media resolution, pending numbered selection, pending-player continuation,
queue control, playback support, and automatic queue advancement are all owned by
the integration.

The sanitized reference therefore has no `scripts.yaml` requirement. A Home
Assistant installation may of course keep its own unrelated `scripts.yaml` and
`script: !include scripts.yaml` entry; they are simply not required by Jellyfin
Media Assistant. Legacy project-owned `jellyha_*` script aliases are not part of
the current public runtime surface.

## Managed Assist sentences

Jellyfin Media Assistant packages its canonical Assist sentence file inside the
integration and provisions the managed copy under Home Assistant's
`custom_sentences/en/` directory during config-entry setup. The sanitized public
reference therefore does not carry a second manually installed sentence copy.

An unchanged managed file is updated automatically when the packaged sentence set
changes. If the installed managed file has been edited by the user, the integration
leaves it untouched and raises a Home Assistant repair issue instead of overwriting
local changes. The `repair_voice_sentences` action is recovery tooling, not a normal
installation step.
