# Rumbo 0.3 architecture and invariants

Deliver a real provider-neutral contract/evidence referee, a local acceptance board, and a reproducible OpenAI plugin review bundle. No hosted endpoint, account, credentials, model calls, or directory approval is assumed.

## Scope and invariants
- Python 3.9+ POSIX standard-library core; optional OAuth owner portal uses Python 3.10+ with Authlib/Requests; SQLite transactional event log with deterministic JSON hashes and replay. Hashes detect accidental/local alteration only when the verifier or trusted external checkpoint is preserved; they do not prove truth or prevent a same-account attacker from replacing history.
- Operator-mapped owners can create/revise/decide through a separate OAuth/PKCE browser portal with owner-only audience/scope and CSRF-protected secure sessions. Agent MCP has no human-authority tools.
- Human-configured contracts contain goal, original request, decision owner, constraints, bounded tasks, dependencies and typed acceptance checks. Agents cannot activate scope revisions or decide acceptance through MCP. Human decisions are authenticated by a configured host principal or trusted local CLI, never an actor field supplied in a tool call. Local same-user processes remain within one trust boundary.
- Server assigns identity/role/project from configuration. Workers claim expiring leases, register confined artifact files, run deterministic checks, request a human decision. Reviewer assertions remain visibly separate from deterministic test/check receipts. An independent configured reviewer must differ from the artifact maker; separate labels do not prove organizational independence.
- Every artifact, receipt and decision binds exact task, contract revision and SHA-256 artifact revision. Contract/artifact changes and stale dependencies invalidate acceptance without erasing history. Rejected decisions supersede earlier approval.
- No execution of artifact instructions, shell commands, remote content, arbitrary file access or model calls. Uploaded text is bounded to 128 KiB per artifact and 64 MiB per project and stored by content digest; it carries no repository/commit authenticity claim. Supported checks: file_contains, json_equals, sha256, and explicitly human-reviewed manual_review.
- MCP stdio and authenticated JSON HTTP transport share a strict tool dispatch. HTTP defaults to loopback. Development bearer fixtures are loopback-only; production is an OAuth protected resource with externally configured issuer/introspection and server-owned subject-to-project mapping. Real OAuth 2.1 authorization-code/PKCE integration, production TLS and domain verification are deployment gates, not included operational claims.
- Responsive accessible read-only board shows goal → task → artifact → evidence → decision; visible stale/claimed/checked/accepted distinctions, useful empty/error/live state. Local board does not expose human write actions. Plugin UI extension only if confirmed by published docs.
- Keep Claude adapter; fix legacy source reference scope and missing/unreadable transcript handling with regression coverage. Existing historical benchmark remains old-version evidence only.
- Submission ZIP excludes lifecycle hooks and registered app references; includes portable plugin manifest, remote MCP configuration template only when endpoint is externally configured, workflow skills, reviewer cases and honest preparation status.

## Decision time and lease expiry

Each mutation uses one finite numeric decision timestamp for lease eligibility,
prepared mutation metadata, and the ledger event's `at`. In Python it is captured
only after `BEGIN IMMEDIATE` has acquired the write lock and the ledger has been
replayed. In Sites it is captured after the asynchronous state read and replay,
separately for each optimistic compare-and-swap attempt. A failed append discards
that attempt's eligibility decision; a retry rereads/replays and samples again.

This sample is the lease-eligibility linearization point, not a completion or
commit timestamp. Artifact reads, checks, hashing, and storage may finish after
it. Work eligible at that point retains that decision for the attempt; no second
clock sample retroactively revokes it. A lease expiring at or before the decision
time is absent, including exact fractional-second boundaries. Expired claims
cannot authorize artifact submission; existing same-actor renewal and expired
lease reclamation rules are unchanged. The clock does not add lease requirements
to actions that previously had none or change actor/role authorization.

Read-only snapshots sample fresh time. A mutation also builds a fresh candidate
return projection before persistence completes: Python validates it before the
SQLite transaction commits, and Sites validates it before its CAS append. Each
Sites retry rebuilds this projection with a new clock sample. The response can
already show an expired lease while event/artifact metadata retains the earlier
valid decision time, or show a lease that expires while append/commit completes.
It describes the projection sample, not elapsed time inside persistence; a later
snapshot samples again.

Invalid, nonnumeric, boolean, or nonfinite clock values fail with `BAD_CLOCK`.
An invalid decision or return-projection clock leaves the ledger unchanged;
there is no stale-projection fallback. Uploaded content-addressed blobs may
already have been stored and can remain unreferenced after a failed attempt,
as with other pre-append failures. The host supplies the trusted clock; this does
not protect against a dishonest or backward-moving host clock.

## Acceptance
Run complete legacy and new suites, real stdio and HTTP protocol subprocess tests, concurrent lease contention, persistence/restart, stale revisions, forged role input, malformed data, path confinement and injection rendering. Visually inspect desktop and narrow board. Validate schemas/package, deterministic reproduction and ZIP contents. Deliver artifacts and exact commands/logs. Separate local distribution evidence, optional hosted validation and actual public-review requirements as documented in [current scope](SUBMISSION-REQUIREMENTS.md#current-scope-and-milestones); do not turn unverified checks into universal gates.
