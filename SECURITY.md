# Security policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue.

1. Open the repository's **Security** tab on GitHub.
2. Choose **Report a vulnerability** (GitHub private vulnerability reporting).
3. Describe the problem, the version, and how to reproduce it. Do not include passwords,
   tokens or Alarmo codes.

You can expect an acknowledgement within about a week. This is a community project maintained
in spare time; there is no bounty and no formal SLA. Fixes are released as a new version and
described in the changelog once users have had a chance to update.

## Supported versions

Only the latest release receives fixes.

## What this integration does and does not protect

See [docs/security-and-quality.md](docs/security-and-quality.md) and the "Security notes" in the
README. In short: permissions are enforced on the server for modes and overlays, but Home
Assistant has no per-service permissions for non-admin users, so guest accounts are not a
security boundary.
