# Security

Do not include Jellyfin API keys, access tokens, credentials, or other secrets in
public GitHub issues.

Jellyfin Media Assistant diagnostics are designed to redact the configured
Jellyfin API key, but users should still review diagnostics and logs before
posting them publicly.

For the public beta, security-sensitive reports that would expose a working
credential should not be opened as a normal issue. Revoke or rotate the affected
credential first, then report the underlying defect without the secret.
