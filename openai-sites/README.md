# OpenAI Sites runtime candidate

This experimental hosted runtime is isolated from Rumbo's canonical Python engine and its unchanged Claude/local distributions. An owner-only private deployment exists at v3, source `ca406c4`. It has not been submitted to or approved for the public directory. Authenticated managed use remains unverified.

## Approved implementation boundary

Sites 0.1.75 requires an ESM Worker with `fetch(request, env, ctx)` and `dist/server/index.js`. The supported packaging contract does not expose Python Workers. This candidate therefore requires differential tests against `../rumbo/core.py`; it must not be described as the same executable engine. Maintaining two runtimes requires those tests on every shared semantic change.

Hosted artifacts are explicitly uploaded immutable UTF-8 bytes. A hosted server cannot inspect arbitrary laptop files or detect their later changes. Use the existing local distribution for safe project-file registration and local-file staleness detection. No local bridge or repository synchronizer is introduced.

## Implementation and verification plan

1. Add failing Python-oracle differential tests, then implement validation, replay, projection, mutations and exact-byte review in a storage-independent Worker engine
2. Add failing D1/R2 integration tests, then implement transactional append-CAS, isolated project memberships, immutable uploads and storage quotas
3. Add failing HTTP/MCP/owner-route security tests, then implement stateless MCP and same-origin, CSRF-protected owner decisions; never expose owner authority through MCP
4. Test browser owner flows, full Python and Claude regressions, package output; record the scope and limits of any independent review
5. Prepare an exact-commit draft PR and review packet; any authenticated private deployment/connection needs its required tool approval; never submit the public directory listing

Important review cases: concurrent distinct claims, same-content upload races and quotas, replay tampering, stale revisions/dependency decisions, untrusted text and JSON edge cases, tenant/project isolation, identity role spoofing, CSRF and interrupted owner flows.

## Source-only privacy changes

Owner-browser project deletion and expired browser-session cleanup are implemented in source, with exact-head verification tracked in draft PR #7. They are not in deployed v3, and the published review policy is unchanged. The deletion flow requires the exact project ID and a fresh confirmation, blocks further project activity, and supports continuation when cleanup is pending. No MCP delete tool or automatic project-age purge is added.

Owners should export before deletion; hosted restore is unavailable. Completion removes application-held project content and records while retaining a hash-derived deleted-project key and empty R2 guard objects indefinitely so delayed uploads cannot restore content. Those keys are pseudonymous/linkable technical metadata, not anonymous or zero-data erasure. The same owner cannot reuse that project ID. Provider backups/logs and already downloaded copies are outside the operation. See [the full retention limits](PRIVACY.md#source-only-deletion-and-cleanup-proposal) and [the bounded cleanup procedure](OPERATIONS.md#source-only-deletion-and-session-cleanup).

## Current verification status

The local automated suite includes Python-oracle differential cases, 20,000 seeded finite-number canonicalization comparisons, role/revision/artifact regressions, D1 SQL adapter tests, owner/MCP HTTP tests, DOM interactions and local workerd runtime tests using Miniflare-emulated D1/R2. Emulator success is not proof of managed hosted persistence or OAuth. The separate CI workflow runs real Chromium and retains synthetic desktop/mobile screenshots; its result must be checked on the exact PR commit.

An independent read-only engine/storage review returned several reproducible findings which were fixed with regression tests. Its final report was interrupted by a platform review restriction, so the independent review remains partial. No full security clearance is claimed. An independent audit is not a published mandatory submission gate and is not required to generate the local package or review draft.

See [data handling](PRIVACY.md), [operations and release gates](OPERATIONS.md), and the separate local Python distribution for capabilities that require local filesystem access. Local distribution readiness, this optional hosted candidate, and public-directory review are separate milestones; see [current scope](../docs/SUBMISSION-REQUIREMENTS.md#current-scope-and-milestones). Managed connection and reviewer tests describe hosted evidence limits, not universal packaging prerequisites.
