# Hosted synthetic workflow verification — 2026-10-03

This report covers the isolated hosted candidate's ordinary functional workflows. It is **not an independent security review, managed-host test, deployment, or release clearance**. The canonical Python engine remains the semantic oracle; the Claude adapter and local distribution remain independent. All identities and uploaded content used here were synthetic.

## Evidence boundary

The tested functional implementation is the isolated hosted branch through `782ef90`, plus the offline test-fixture correction accompanying this report. The branch also incorporated the canonical/oracle fixes (`aae5657`, `60fa319`, and `3995f02`) for differential verification. Integration/cherry-picking changes commit IDs; recheck the resulting source rather than treating this branch's result as exact-commit CI.

- Baseline hosted aggregate: **30 passed, 0 failed, 0 skipped**
- Before the metadata configuration correction: **60 passed, 0 failed, 0 skipped**; ESM build and artifact validation also completed. These runs used Miniflare defaults and should not be described as strictly offline
- Interim non-runtime subset: **58 passed, 0 failed, 0 skipped**, excluding both Miniflare tests explicitly
- Final corrected offline suite: **65 passed, 0 failed, 0 skipped**, including the two D1/R2 runtime cases, four static/mock configuration cases, and a real workerd outbound-denial regression
- Browser suite: **6 tests collected**, no browser-case execution claimed successful. The selected Escape case could not reach page execution: the expected Playwright binary was missing, its official download yielded a truncated archive, and the available system Chromium failed at startup with `socket() failed: Operation not permitted`. The remaining browser cases were not executed
- `git diff --check` passed

The final command, from this directory with the corrected fixtures, was:

```sh
node --test tests/*.test.mjs
```

Non-runtime tests use in-memory SQLite/object fixtures, direct calls to the Worker handler, a DOM fixture with fetch bound to that handler, and local Python-oracle subprocesses. Runtime tests use only the explicit offline Miniflare factory. No managed account is used. DOM success is not real-browser success.

## Reproduced failures fixed

Each behavior below had a failing deterministic regression before its fix (or a fix-revert failure), then passed:

1. **Repeated confirmation dismissal:** after an earlier confirmation, native-style dismissal reused the dialog's old `returnValue`, causing an unintended revision. Reset the value for every opening and correct the DOM shim, which had previously hidden the bug
2. **Interrupted project selection:** an unsuccessful refresh kept the previous project visible under a new selection; the selector also remained usable during pending work. Clear loaded context before reads, disable project switching during operations, and record newly created selection in the reload URL
3. **Uncommitted upload export:** a failed upload's quota reservation caused otherwise valid committed-history exports to fail. Derive the export manifest from the captured ledger's referenced historical uploads, excluding unfinished reservations
4. **Large valid export verification:** the offline verifier's 12,000-record ceiling rejected a supported 10,000-event ledger with 9,998 historical artifacts (20,000 export records including header/footer). Align its bound with the engine event budget plus one upload per event
5. **Malformed check kinds:** JavaScript property-key coercion accepted `["file_contains"]` as a kind. Require a string, matching the updated canonical Python validation
6. **Complete contract replacement defaults:** omitted `demo` inherited a prior true value. New revision events now explicitly carry the canonical false default; old events are not rewritten
7. **Full-ledger upload residue:** a ledger-rejected upload had already consumed quota and stored bytes. Check the event budget before storing the upload. The regression uses a genuine valid approximately 16 MiB persisted history, rather than altering the production budget constant
8. **Stalled owner requests:** stalled headers or response bodies left all owner controls disabled indefinitely. Bound the entire fetch/body operation to 30 seconds, preserve drafts, and tell the owner to refresh/check saved state before retrying. The write-response test proves the server can have committed despite a lost response; the export test proves no partial download is offered

## Additional passing workflow coverage

- Upload interrupted by a concurrent contract revision, followed by restart/reclaim/retry using the already uploaded digest
- Checks interrupted by artifact replacement, with no obsolete evidence committed
- Competing owner revisions, equal-content uploads to separate tasks, expiring claims and old-worker retry rejection
- Dependency rejection/reacceptance, new check receipts, uncertain reviewer assertions, same-content replacement revisions, removed/restored tasks and exact UTF-8 upload limits compared with Python
- Export snapshot consistency during later writes, cancel/retry determinism, historical-byte corruption, and empty/BOM/CRLF/multibyte preservation
- Stale owner inspection rejection, refreshed exact-byte acceptance, repeated-click single decision, draft preservation and recovery after failed reads
- Earlier completed local workerd tests covered eight competing claimants and full D1/R2 teardown/restart with surviving leases, worker session, exact Unicode bytes and subsequent checks/acceptance

## Synthetic runtime network boundary

Source-only inspection found that the original synthetic runtime configuration could make an optional external request for Miniflare's default `Request.cf` metadata:

- `node_modules/miniflare/dist/src/index.js:70665`: `https://workers.cloudflare.com/cf.json`
- `setupCf` at lines 70751–70787 calls `undici.fetch` with a 3-second abort signal when no suitable cached metadata exists
- The inspected fetch call has no body or repository/test payload; ordinary connection metadata is still exposed
- Configuration assembly invokes it before the local Worker starts
- Source supports an explicit `cf` object or `cf: false` without that fetch, providing an offline configuration path

The corrected `tests/offline-runtime.mjs` factory explicitly sets `cf: false` and disables telemetry before construction. Its outbound service rejects Worker fetches in-process; the actual workerd regression observes Miniflare's local HTTP 500 conversion with the expected denial message. All runtime constructors use that factory. The synthetic browser server uses direct Worker-handler calls (no Miniflare) and rejects global Worker fetches in-process. Static/mock tests cover these configuration boundaries, including caller override attempts. Hosting configuration is unchanged.

The original default configuration is unsuitable for strictly offline synthetic verification. Managed HTTPS/OAuth, production persistence, separate real reviewer accounts, browser rendering, and full independent review remain unverified.
