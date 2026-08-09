# Default media player options registration hotfix

Home Assistant derives `supports_options` from the registered config-flow handler.
For custom integrations, the config-entry API can be serialized before that handler is
registered, leaving a cached `supports_options: false` response for the frontend.

This hotfix:

- explicitly returns `True` from `async_supports_options_flow`;
- keeps the documented `async_get_options_flow` implementation; and
- clears the config entry's public state cache after successful setup so the next API
  response recalculates options support.

Existing entries do not need to be deleted or recreated. After copying the files and
restarting Home Assistant, the entry should report `supports_options: true` and expose
the Configure/cogwheel control.
