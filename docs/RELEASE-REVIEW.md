# Rumbo 0.3.0 review candidate

Portability and packaging follow-up prepared 2026-10-01 against verified remote base `21c005d5670c9111526de34fc0001e846bfe4ea6`. All 35 files changed by that commit match the recovered local index byte-for-byte. Local HEAD remains the older `cf61658517f41471f0a3617c6948cc4d2ba5a2ae`; the incremental review patch is against the verified index/remote base, not that older HEAD.

**Status:** implemented and locally tested review candidate. No OpenAI upload, submission, approval or publication; no production deployment, new accounts, persistent credentials or external model calls. [Draft code-review PR #1](https://github.com/scking21/rumbo/pull/1) remains the review destination. This report records pre-push checks for the incremental portability/packaging patch; its own exact-head CI must be checked separately on that PR.

## Implemented

- Deterministic contract/evidence referee, bounded leases, revision-linked acceptance and dependency invalidation
- Confined project-file artifacts plus 128 KiB UTF-8 uploads, immutable digest storage, 64 MiB/project upload quota and exact-byte review
- SQLite transactional persistence, hash-chain verification, 10,000-event/16 MiB ledger bounds and controlled corrupt-storage failure
- Real CLI, MCP stdio, authenticated stateless HTTP and OAuth protected-resource metadata/issuer introspection
- Separate OAuth/PKCE owner portal for operator-mapped accounts, secure bounded sessions, CSRF-protected contract/decision forms and inert exact-byte previews
- Read-only inline MCP Apps board with distinct receipts, reviewer assertions, human decisions and explicit stale/superseded states
- Fixed Claude provenance behavior; unchanged historical benchmark is not evidence of this release's effectiveness
- Reproducible local-plugin/source ZIP tooling, public-package fail-closed gates, review cases and official-schema checks
- Read-only standard-Ubuntu GitHub Actions verification with pinned official actions, real Chromium, strict no-skips test mode and one-day synthetic screenshot artifacts

## Actual verification completed locally

- Current readiness follow-up local suite: **172 tests; 166 passed, 6 optional browser tests explicitly skipped**
- Independently rechecked [remote base CI run 4](https://github.com/scking21/rumbo/actions/runs/36857951432) on `21c005d5670c9111526de34fc0001e846bfe4ea6`: **162 new tests including all 6 Chromium cases, plus 95 legacy tests passed**. All three jobs succeeded, including Python 3.9 core and isolated Docker/nginx smoke. These results do not certify this newer local patch
- Current legacy Claude adapter suite: **95 passed**
- Fresh independent recheck on 2026-10-01: **166 new plus 95 legacy tests passed**, with **6 browser cases unexecuted**. Explicit Chromium launch failed with `socket() failed: Operation not permitted`; no alternate route was attempted. Docker and nginx remain absent. The optional owner integration test now skips explicitly when Authlib/Requests are absent instead of failing import in a partially installed development environment; strict CI still rejects every skip.
- WorkOS: 11 real-signature/fixture-provider tests; backup/restore: 28 tests; deployment shape/port/secret-file helpers: 5 tests; health/logging/challenge routes: 5 tests
- Independent read-only adapter review verified the issuer-canonicalization fix, offline-access scope separation and absence of a confirmed authorization bypass
- The 24 owner tests use real local HTTP/Authlib behavior with an explicitly synthetic external provider transport; no live identity-provider call
- Real subprocess MCP initialization/tool/resource flows; actual HTTP auth, origin/Host checks, two-principal isolation and owner/MCP authority separation
- Threaded claim/upload concurrency, persistence/restart, stale revisions, failed checks, malformed/deep JSON, duplicate headers, path/secret-file protection, corrupted history and partial-upload retry
- Node/source board tests include real Engine snapshots, injected markup as text, native-bridge fixtures, recorded questions and inactive acceptance after new evidence
- Package byte-for-byte reproduction, hook/app/secret-path exclusion, official portable JSON schemas, extracted local launcher execution and guarded public URL validation
- Source-package audit fixed known credential filenames entering non-plugin subtrees and nested deployment filenames bypassing the deployment allowlist. Ten synthetic rejection fixtures failed before the fix and pass after it; this is filename-based hygiene, not general secret detection
- Current `compileall`, `git diff --check`, reproducible source/local ZIP builds and Python wheel build; separate plugin/skill validators were historical checks, not rerun in this pass
- A pre-decoder, quote/escape-aware 64-container JSON depth bound now replaces dependence on interpreter recursion limits. Regression tests cover exact boundary, 15,000 nested arrays, UTF-8/16/32, malformed JSON and MCP HTTP/stdio plus owner form rejection
- macOS system-ancestor support is covered by synthetic platform/ownership/target fixtures and the 28-test backup suite on Linux. The new CI matrix targets Ubuntu/macOS with Python 3.12/3.14; those added runs have not executed
- Strict test runner deliberately exits nonzero when optional tests skip, so the CI browser stage cannot silently report an incomplete pass

Commands:

```sh
# Python 3.10+ environment with requirements-authkit.txt installed
python3 scripts/run_tests.py
(cd rumbo && python3 -m unittest discover -s tests -v)
python3 -m compileall -q rumbo scripts
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/rumbo-wheel .
python3 scripts/package_release.py --kind local --output dist/rumbo-0.3.0-local-plugin.zip
python3 scripts/package_release.py --kind source --output dist/rumbo-0.3.0-source.zip
```

The local run used Python 3.12, Authlib 1.8.0, Requests 2.34.2, PyJWT 2.15.1, cryptography 50.0.2, Playwright 1.62.0, jsonschema 4.26.0 and Node. Optional packages were already present in a temporary dependency directory with pip installation metadata; no package installation or credential provisioning occurred in this pass. This pass did not independently re-verify their original download provenance. Required top-level dependency constraints are in requirements-authkit.txt. Core/agent MCP remains Python 3.9+ POSIX; owner login requires Python 3.10+.

## Explicitly unverified

- Local browser execution remains blocked by cloud CUA loopback restrictions and Chromium process-socket limits. Baseline CI verified the actual-engine browser path and produced inspected synthetic screenshots. New exact-head CI, a full screen-reader audit and live owner/provider browser sign-in remain distinct gates. See [browser evidence and limits](BOARD.md)
- Actual ChatGPT/Codex installation, global/thread panel behavior and live host tool-selection tests; bridge fixtures do not certify the host
- Exact-head CI for this incremental patch, including the newly added macOS/Python 3.14 matrix. No macOS or Python 3.14 interpreter is available locally. The reported Python 3.14 behavior was not directly reproduced here; the missing explicit bound was confirmed and regressions no longer depend on interpreter recursion
- Updated container runtime/backup smoke after this patch; the preceding remote base passed Docker/nginx CI, but neither executable is available locally
- Real OAuth issuer/client registration, PKCE consent round trip, production HTTPS cookies, token/account revocation policy, proxy/hosting operation and public endpoint availability
- Public publisher/domain verification, reviewer-account provisioning, legal/support/listing URLs and accessible walkthrough video

## Product/trust boundaries

The service is operator-provisioned, one configured project per subject. Optional WorkOS JWT+active-introspection verification, status-only health, safe logs, approval-gated Compose/Render recipes and operator backup/restore are now implemented; none provisions infrastructure or credentials. The direct Render recipe explicitly requires separate verification of managed-ingress/rate controls and storage ownership rather than claiming it inherits the Compose nginx configuration. It has no automatic signup, invitations, multi-project chooser, repository synchronization, arbitrary command runner, binary uploads, universal agent pause mechanism, external audit witness or model supervisor.

A receipt proves only its stated condition against exact bytes. Uploaded bytes do not authenticate a Git commit or test execution. A reviewer assertion is attributed, not mathematically proven. OAuth identifies a configured account, not physical human presence. Same-account server administrators/local shell processes remain trusted. Hash chaining is tamper-evidence relative to preserved history/verifier, not an adversarial security boundary. Filename blocking is not a universal secret detector; use dedicated clean/upload-only roots.

The board cannot approve work. The owner portal is a separate authenticated surface. Already established owner sessions are not introspected again on every request; provider-side revocation can take up to their remaining lifetime (maximum 30 minutes). Sessions are in process memory and restart signs owners out. Backups, TLS, operator mappings and retention remain deployment responsibilities.

## Before public submission

Complete [deployment gates](DEPLOYMENT.md), verify the [five positive and three negative cases](reviewer-cases.json) in the live host, inspect the final production ZIP and obtain the owner's review before any upload/submission. The packager rejects absent/unverified production configuration and never uploads. A local ZIP, source review or CI pass does not equal directory approval.
