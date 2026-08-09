# Historical note — shadow search testing

Status: **retired in Step 44B**

During the robust-search migration, `jellyfin_assist.compare_search` called native `jellyfin_assist.search` and upstream `jellyha.search` side by side and returned a read-only comparison. It was useful for proving parity while production still had a JellyHA search dependency.

Native search became the sole production backend in Step 42D. After the household installation later passed full standalone playback tests with JellyHA disabled, Step 44B removed the comparison action, its `jellyha.search` service call, and the shadow runtime module.

Historical comparison behavior remains recoverable from Git history and the earlier migration documentation. It is intentionally not shipped as a callable runtime action because the public integration must not require JellyHA.
