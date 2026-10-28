# Security audit triage

Audit run: 2026-10-28. Sources: `npm audit` and `pip-audit`.

## JavaScript dependencies

`npm audit` reported 13 advisories: 1 low, 4 moderate, 7 high, and 1 critical.

| Package | Severity | Triage |
| --- | --- | --- |
| `next` 16.3.5 | Critical | Upgrade to a patched Next.js release is required. The required package install could not complete because registry access timed out, so this remains open and must block production deployment until patched. |
| `@modelcontextprotocol/sdk` | High | Transitive through tooling. Upgrade when its parent dependency permits; avoid using the affected OAuth/HTTP transports with untrusted servers until then. |
| `body-parser` | High | Transitive. Apply the available compatible lockfile update; request body compression is a potential DoS surface. |
| `deepmerge` | High | Transitive through `shadcn`; remediation requires a breaking `shadcn` major upgrade. Track and upgrade with compatibility review. |
| `source-map-js` | High | Transitive. Apply a compatible lockfile update. |
| `sharp` | High | Transitive. Apply a compatible lockfile update to a release with patched `librsvg`. |
| `undici` | High | Transitive. Apply a compatible lockfile update; affected client and WebSocket paths can expose availability and cross-origin risks. |
| `zod` | High | Transitive through `shadcn`; remediation requires its breaking major upgrade. Track with the `shadcn` compatibility review. |
| `fast-uri` | Moderate | Transitive. Apply a compatible lockfile update because URI parsing is security sensitive. |
| `hono` | Moderate | Transitive. Apply a compatible lockfile update; affected static serving can bypass path middleware. |
| `ip-address` | Moderate | Transitive. Apply a compatible lockfile update to avoid input-driven CPU exhaustion. |
| `qs` | Moderate | Transitive. Apply a compatible lockfile update to avoid input-driven exceptions. |

`npm audit fix` did not complete in the available registry window. The audit's
non-breaking fixes and the Next.js upgrade therefore remain outstanding.

## Python dependencies

`pip-audit` found 18 advisories across six installed packages. The backend
currently constrains `cryptography` to `<45`, which excludes all listed fixes;
this must be updated with compatibility review before release.

| Package | Installed | Triage |
| --- | --- | --- |
| `cryptography` | 44.0.3 | Multiple PYSEC/GHSA advisories; upgrade to at least 50.0.0, then review encryption compatibility and run the full backend suite. |
| `certifi` | 2026.7.22 | Upgrade to at least 2026.10.19. |
| `dnspython` | 2.8.0 | Upgrade to at least 2.9.0. |
| `opentelemetry-api` | 1.45.0 | Upgrade to at least 1.45.1. |
| `pip` | 26.1.2 | Upgrade the build environment to at least 26.2.0; this is not an application runtime dependency. |
| `pytest` | 8.4.2 | Upgrade the development dependency to at least 9.0.3 after test compatibility review. |

`pip-audit` also notes that the local `kova-backend` project metadata is not
published on PyPI; the audit applies to its installed dependencies.
