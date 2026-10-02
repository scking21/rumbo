# Hosted candidate operations

## Runtime and authority

Deployment build: `dist/server/index.js`, a bundled ESM Worker with no runtime npm dependencies, Node-only imports, local filesystem, subprocesses, model API calls, or paid external services. Logical bindings are D1 `DB` and R2 `ARTIFACTS`. Drizzle generates the immutable schema migrations. Sites manages OAuth and trusted identity headers. A direct Worker deployment outside that trusted boundary is not supported.

Every project key is derived from the Site user ID plus the owner-chosen alias. All event, worker and artifact queries are project-scoped. D1 batches atomically append an event only at its expected head and then update that exact head. A competing caller replays/revalidates the new state before retrying. Content quota reservation happens before R2 upload; failed upload reservations remain bounded and can be retried under the same digest. R2 keys are project-scoped and content-addressed; existing bytes are verified and never intentionally overwritten.

Worker handles are coordination identifiers scoped by the authenticated user and project, not bearer credentials. A separate reviewer membership cannot be selected through MCP. Atomic SQL guards prevent an account opening a worker session while it is promoted to reviewer. Owner-browser actions use HttpOnly/Secure/SameSite=Strict cookies, hashed session state, CSRF, same-origin Fetch Metadata and transport-mode checks. Do not weaken these checks to accommodate a test client.

## Verify locally

Use Node 24 and Python 3.12. Run `npm ci`, `npm test`, `npm run validate`, `npm audit --audit-level=moderate`, and `npm run test:browser` after installing official Playwright Chromium. The main tests include the unchanged Python oracle, a 20,000-number canonicalization sweep, D1/R2 adapter tests, real workerd runtime tests, HTTP owner/MCP paths and DOM interaction tests. The browser suite uses an explicitly enabled synthetic fixture server which is never bundled or deployed.

The parent repository's original Python/Claude tests and CI remain applicable and unchanged. The separate `verify-sites.yml` workflow tests this adapter. A passing DOM test is not visual browser QA. A saved/deployed private Site is not a verified OAuth connection or a public-directory submission.

## Release gates

- Resolve any remaining behavior-parity gaps before presenting the hosted runtime as equivalent for its supported upload workflow
- Synthetic Chromium workflows passed and their screenshots were visually inspected for runtime source `60a9f9f8e5bc595a3322a38c435592374937a823`. Keep that evidence bound to unchanged runtime inputs. Managed HTTPS/OAuth read-only connection, deployed persistence readback and two separate authenticated reviewer/worker account checks remain unverified
- Complete independent review; a partially interrupted review is not clearance
- Establish publisher-approved policy/legal URLs, retention/deletion and recovery procedures, reviewer access, final listing/ZIP and the user's final review
- Preserve the local distribution for project-file registration, local file staleness and local backup/restore

No automatic final submission, public audience change, merge or reviewer grant is authorized by this candidate's build/test process.

## Dependency maintenance

All npm packages are development-only. Build and schema generation use current pinned official-registry versions. Transitive esbuild is overridden to the directly pinned safe build version. Any additional security overrides must be checked against migration generation, build, workerd runtime, browser tests and a fresh dependency audit. Keep the lockfile; do not rely on a previously green audit after adding a new test dependency.
