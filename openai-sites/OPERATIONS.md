# Hosted candidate operations

## Runtime and authority

Deployment build: `dist/server/index.js`, a bundled ESM Worker with no runtime npm dependencies, Node-only imports, local filesystem, subprocesses, model API calls, or paid external services. Logical bindings are D1 `DB` and R2 `ARTIFACTS`. Drizzle generates the immutable schema migrations. Sites manages OAuth and trusted identity headers. A direct Worker deployment outside that trusted boundary is not supported.

Every project key is derived from the Site user ID plus the owner-chosen alias. All event, worker and artifact queries are project-scoped. D1 batches atomically append an event only at its expected head and then update that exact head. A competing caller replays/revalidates the new state before retrying. Content quota reservation happens before R2 upload; failed upload reservations remain bounded and can be retried under the same digest. R2 keys are project-scoped and content-addressed; existing bytes are verified and never intentionally overwritten.

Each optimistic append attempt captures one decision timestamp after its asynchronous state read and ledger replay. That timestamp governs lease eligibility and all prepared/event metadata. Failed CAS attempts reread/replay and take a fresh timestamp before retrying. Exact expiry (`expires_at <= decision time`), including fractional times, removes the lease. This is an eligibility linearization point, not a commit-time claim: artifact work may finish later. The candidate return projection samples fresh time before each CAS append and is returned unchanged on success. Its lease status can already be expired, or expire during the append; it describes its projection sample, not time spent inside persistence. A later read-only snapshot samples again. Invalid decision or return clocks fail as `BAD_CLOCK` without committing a ledger event; pre-append uploaded blobs may remain unreferenced. Every retry rebuilds the candidate projection, without a stale-state fallback. Host-clock integrity remains an operator assumption. The canonical Python path follows the same rule after acquiring its SQLite write lock. See [the decision-time contract](../docs/ARCHITECTURE.md#decision-time-and-lease-expiry).

Worker handles are coordination identifiers scoped by the authenticated user and project, not bearer credentials. A separate reviewer membership cannot be selected through MCP. Atomic SQL guards prevent an account opening a worker session while it is promoted to reviewer. Owner-browser actions use HttpOnly/Secure/SameSite=Strict cookies, hashed session state, CSRF, same-origin Fetch Metadata and transport-mode checks. Do not weaken these checks to accommodate a test client.

## Verify locally

Use Node 24 and Python 3.12. Run `npm ci`, `npm test`, `npm run validate`, `npm audit --audit-level=moderate`, and `npm run test:browser` after installing official Playwright Chromium. The main tests include the unchanged Python oracle, a 20,000-number canonicalization sweep, D1/R2 adapter tests, real workerd runtime tests, HTTP owner/MCP paths and DOM interaction tests. The browser suite uses an explicitly enabled synthetic fixture server which is never bundled or deployed.

The canonical Python and independently versioned Claude adapter suites remain required alongside the Sites suite. The separate `verify-sites.yml` workflow tests this adapter. A passing DOM test is not visual browser QA. A saved/deployed private Site is not a verified OAuth connection or a public-directory submission.

After dependencies are already installed, use explicit process-only offline settings for local test/build validation. These disable npm's optional registry update check as well as package fetching, and retain the synthetic runtime's disabled CF metadata bootstrap:

```sh
export npm_config_offline=true npm_config_update_notifier=false CLOUDFLARE_CF_FETCH_ENABLED=false
npm test
npm run validate
```

These commands use the existing local dependency tree; they do not install missing packages or provide a browser-download fallback. `npm ci`, `npm audit` and initial browser installation are separate network-requiring preparation steps, not part of this offline run. The flags change only this shell/process environment, not persistent npm or system configuration.

## Distribution readiness and evidence limits

- Resolve any remaining behavior-parity gaps before presenting the hosted runtime as equivalent for its supported upload workflow
- Current synthetic CI evidence is recorded per exact head on [draft PR #7](https://github.com/scking21/rumbo/pull/7). Earlier synthetic Chromium workflows passed and their screenshots were visually inspected for runtime source `60a9f9f8e5bc595a3322a38c435592374937a823`. Keep that evidence bound to unchanged runtime inputs. Managed HTTPS/OAuth read-only connection, deployed persistence readback and two separate authenticated reviewer/worker account checks remain unverified
- Independent security review remains partial. This is a coverage limitation, not a mandatory submission approval or a prerequisite to generating/distributing the local package or creating a review draft. No security clearance is claimed
- For public MCP review, satisfy the actual portal requirements for the selected supported route, including public listing/legal URLs and final owner review. The checks above describe this optional hosted candidate; do not present every managed-host check as a universal plugin requirement
- Preserve the local distribution for project-file registration, local file staleness and local backup/restore

The goal remains a free public plugin hosted within the OpenAI ecosystem, with no external-hosting fallback or additional-cost services. The private Sites-to-public-directory route is unresolved; that is a platform question to investigate, not a requirement for the owner to buy hosting. No new dashboard work is planned. The [OpenAI-hosted review materials](https://rumbo-review-materials.aggie-king21.chatgpt.site/) include the authorized synthetic local-engine walkthrough; they do not establish managed-host execution. Existing useful UI is retained. See [submission scope](../docs/SUBMISSION-REQUIREMENTS.md#current-scope-and-milestones).

No automatic final submission, public audience change, merge or reviewer grant is authorized by this candidate's build/test process.

## Dependency maintenance

All npm packages are development-only. Build and schema generation use current pinned official-registry versions. Transitive esbuild is overridden to the directly pinned safe build version. Any additional security overrides must be checked against migration generation, build, workerd runtime, browser tests and a fresh dependency audit. Keep the lockfile; do not rely on a previously green audit after adding a new test dependency.
