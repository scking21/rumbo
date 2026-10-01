# Rumbo 0.3.0 review candidate

Prepared 2026-10-01 from repository base `1d9c5b95265fcbb8181d25bd52dfa0947a7d88f5`.

**Status:** implemented and locally tested review candidate. No OpenAI upload, submission, approval or publication; no production deployment, new accounts, persistent credentials or external model calls. A draft code-review branch and independent CI are separate next steps.

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

- New suite: **113 tests; 108 passed, 5 optional browser tests explicitly skipped**
- Legacy Claude adapter suite: **95 passed**
- The 24 owner tests use real local HTTP/Authlib behavior with an explicitly synthetic external provider transport; no live identity-provider call
- Real subprocess MCP initialization/tool/resource flows; actual HTTP auth, origin/Host checks, two-principal isolation and owner/MCP authority separation
- Threaded claim/upload concurrency, persistence/restart, stale revisions, failed checks, malformed/deep JSON, duplicate headers, path/secret-file protection, corrupted history and partial-upload retry
- Node/source board tests include real Engine snapshots, injected markup as text, native-bridge fixtures, recorded questions and inactive acceptance after new evidence
- Package byte-for-byte reproduction, hook/app/secret-path exclusion, official portable JSON schemas, extracted local launcher execution and guarded public URL validation
- `compileall`, `git diff --check`, local plugin manifest validator, both skill validators and Python wheel build
- Strict test runner deliberately exits nonzero when optional tests skip, so the CI browser stage cannot silently report an incomplete pass

Commands:

```sh
# Python 3.10+ environment with requirements-owner.txt installed
python3 scripts/run_tests.py
(cd rumbo && python3 -m unittest discover -s tests -v)
python3 -m compileall -q rumbo scripts
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/rumbo-wheel .
python3 scripts/package_release.py --kind local --output dist/rumbo-0.3.0-local-plugin.zip
python3 scripts/package_release.py --kind source --output dist/rumbo-0.3.0-source.zip
```

The local run used Python 3.12, Authlib 1.8.0, Requests 2.34.2, Node, and jsonschema 4.26.0. Owner dependencies were installed in a temporary test directory, not globally. Core/agent MCP uses the standard library and declares Python 3.9+ POSIX; the owner portal requires Python 3.10+. The included CI Python 3.9 job has not yet run.

## Explicitly unverified

- Rendered browser layout, keyboard/screen-reader behavior and owner sign-in in a real browser: cloud CUA loopback was blocked and local Chromium could not create required process sockets. See [the exact browser limits](BOARD.md)
- Actual ChatGPT/Codex installation, global/thread panel behavior and live host tool-selection tests; bridge fixtures do not certify the host
- Included GitHub Actions workflow results and screenshots: check the exact review commit after the draft PR exists
- Real OAuth issuer/client registration, PKCE consent round trip, production HTTPS cookies, token/account revocation policy, proxy/hosting operation and public endpoint availability
- Public publisher/domain verification, reviewer-account provisioning, legal/support/listing URLs and accessible walkthrough video

## Product/trust boundaries

The service is operator-provisioned, one configured project per subject. It has no automatic signup, invitations, multi-project chooser, repository synchronization, arbitrary command runner, binary uploads, universal agent pause mechanism, external audit witness or model supervisor.

A receipt proves only its stated condition against exact bytes. Uploaded bytes do not authenticate a Git commit or test execution. A reviewer assertion is attributed, not mathematically proven. OAuth identifies a configured account, not physical human presence. Same-account server administrators/local shell processes remain trusted. Hash chaining is tamper-evidence relative to preserved history/verifier, not an adversarial security boundary. Filename blocking is not a universal secret detector; use dedicated clean/upload-only roots.

The board cannot approve work. The owner portal is a separate authenticated surface. Already established owner sessions are not introspected again on every request; provider-side revocation can take up to their remaining lifetime (maximum 30 minutes). Sessions are in process memory and restart signs owners out. Backups, TLS, operator mappings and retention remain deployment responsibilities.

## Before public submission

Complete [deployment gates](DEPLOYMENT.md), verify the [five positive and three negative cases](reviewer-cases.json) in the live host, inspect the final production ZIP and obtain the owner's review before any upload/submission. The packager rejects absent/unverified production configuration and never uploads. A local ZIP, source review or CI pass does not equal directory approval.
