# Security advisories and triage

Last reviewed: 2026-10-28

## Dependency audits

Audits were run with `npm audit` in `frontend` and `pip-audit` in
`backend`. After the compatible npm updates and Next.js pin, the frontend audit
reports three low-severity findings and no critical, high, or moderate findings.
The post-sync Python audit reported eight advisory instances across five
packages. Repeated advisory IDs are emitted for multiple installed dependency
paths; the report is not 18 distinct root causes. The project itself is not
published on PyPI, so pip-audit cannot resolve its local distribution metadata.

| Dependency | Finding | Triage |
|---|---|---|
| Next.js | Critical remote code execution and other advisories affected 16.3.5. | Fixed by pinning 16.4.3. Re-run `npm audit` after dependency changes. |
| `@modelcontextprotocol/sdk`, `body-parser` | High OAuth redirect, authentication, request-limit, and compressed-body denial-of-service advisories were present in the initial audit. | Compatible npm updates removed them; absent in the post-fix audit. |
| `deepmerge` (optional `shadcn` CLI dependency) | Prototype poisoning advisory; three low findings are reported in the current tree. | A forced fix replaces the CLI with a breaking major release. Evaluate whether the CLI is needed, then remove or upgrade it deliberately. No high or critical finding remains. |
| `fast-uri`, `hono`, `ip-address`, `qs`, `sharp`, `source-map-js`, `undici` | Moderate/high URL, denial-of-service, redirect, TLS, and integrity advisories were present in the initial audit. | Compatible npm updates removed them; absent in the post-fix audit. |
| `cryptography` | Multiple security advisories affected installed 44.0.3; the project constraint capped versions below 45. | Project constraint now permits only the patched 50.x series. Local environment was synced to 50.0.2. |
| `certifi` 2026.7.22 | PYSEC-2026-4320; fixed in 2026.10.18. | Upgrade the transitive dependency and rerun pip-audit. |
| `dnspython` 2.8.0 | CVE-2026-114605; fixed in 2.9.0. | Upgrade the transitive dependency and rerun DNS-related tests. |
| `opentelemetry-api` 1.45.0 | CVE-2026-114603; fixed in 1.45.1. | Upgrade the dependency and verify telemetry initialization. |
| `pip` 26.1.2 | PYSEC-2026-3721; fixed in 26.2. | Update the CI installer image/tooling to pip 26.2 or later. |
| `pytest` 8.4.2 | PYSEC-2026-1845; fixed in 9.0.3. | Dev-only dependency. Upgrade after confirming plugin compatibility in the full suite. |

The dependency audit is point-in-time and transitive packages can change when
lockfiles are regenerated. Re-run both commands before release.

## Authorization and secret handling review

| Area | Finding | Resolution |
|---|---|---|
| Exploration ownership | No environment-specific owner bypass is present. | Existing strict owner check retained for every environment. |
| Flow update | Nested update validates flow/project association and tester role on the path project. | Existing checks retained. |
| Trace download | Confirmed: a report signature bypassed caller ownership. | Trace download now requires an authenticated execution owner and resolves evidence by execution ID. |
| Viewport WebSocket | Confirmed: the single-use ticket was still in the query string. | Ticket now arrives in the first WebSocket message, after connection acceptance; the ticket endpoint remains authenticated and expires tickets in 30 seconds. |
| Credential decryption | Service plaintext fallback: not present; it already required the versioned encrypted format. Migration handling: confirmed; malformed legacy Fernet data could be treated as plaintext and re-encrypted. | Migration now decrypts legacy Fernet values or fails closed, while migrating historical plaintext values into the versioned format. Credential errors no longer include exception contents in logs. |
| Credential reuse | Confirmed: exploration credentials could be sourced from another same-host project. | Removed host-based fallback; credentials are limited to the exploration session's project. |
| Budget migration | Confirmed: migration 034 referenced a filename instead of a revision ID. | Migration now follows revision 033, allowing the budget columns to be applied. |

No bearer token or WebSocket ticket is placed in a URL by the live viewport client.
