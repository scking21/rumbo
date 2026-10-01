# Rumbo

Keep coding agents on the course you actually agreed to.

*Rumbo* is Spanish for a ship's course or heading.

## 0.3.0 local review candidate

Rumbo now has a working provider-neutral contract/evidence engine, CLI, MCP transports, a read-only acceptance board and OpenAI plugin packaging. It records **agreed goal → bounded task → exact artifact → evidence → human decision**.

This release has **not been uploaded, submitted, approved, published or deployed**. The local plugin ZIP is reviewable and testable. Public-directory submission still needs a real HTTPS/OAuth service, approved listing/legal URLs, publisher/domain verification, reviewer access, a walkthrough video and live host QA. The public-package generator refuses absent production configuration; see [deployment gates](docs/DEPLOYMENT.md) and [verification report](docs/RELEASE-REVIEW.md).

### What works

- Versioned human-owned contracts with original words, constraints, bounded tasks and dependency checks
- Expiring task claims with transactional conflict detection
- SHA-256 artifact identity confined to an explicitly selected project root, plus bounded authorized UTF-8 artifact uploads and exact-byte review
- Deterministic `file_contains`, `json_equals` and `sha256` checks; attributed `manual_review` assertions
- Evidence and decisions bound to exact contract/artifact revisions; changed bytes, requirements and dependency decisions invalidate acceptance
- Human acceptance distinct from work claims, passing checks and reviewer assertions
- SQLite persistence with a hash-linked event chain and restart verification
- Agent-safe CLI, MCP stdio and authenticated stateless Streamable HTTP; no human approval tools in MCP
- A separate OAuth/PKCE browser owner portal for mapped accounts to create/revise contracts, inspect exact bytes and decide, with secure sessions and CSRF protections
- An inline MCP Apps acceptance board plus an anonymous **synthetic-only** local demo
- Existing Claude Code planning adapter, with stricter provenance fixes

Python 3.9+ on POSIX (Linux/macOS) is required; tested on Linux/Python 3.12. The core and server use the standard library. Windows is not supported by the current symlink-safe file-opening implementation. The optional OAuth owner portal requires Python 3.10+ and Authlib/Requests; it was tested on Python 3.12. Development-only schema and browser checks use optional tooling.

## Try the deterministic demo

From this repository root, use a new empty directory:

```sh
mkdir /tmp/rumbo-demo
python3 -m rumbo --root /tmp/rumbo-demo demo
printf '%s\n' '{"mode":"demo","demo_root":"/tmp/rumbo-demo"}' > /tmp/rumbo-demo-server.json
python3 -m rumbo serve --config /tmp/rumbo-demo-server.json --port 8765
```

Open `http://127.0.0.1:8765` on the same computer. The data is visibly synthetic. It includes accepted export work, a failed dependency-baseline check, a reviewer assertion awaiting a human, a stale document and blocked/unclaimed work. Demo mode provides no writable MCP access and refuses to expose a project if its current `demo` flag is false. No model calls, accounts, passwords or telemetry are needed.

## Use a real project

1. Add `.rumbo/` to the project's `.gitignore`. The private state contains the original request and review text.
2. Prepare a contract JSON using [the contract guide](docs/CONTRACTS.md). The human owner initializes it through the trusted local operator flow:

```sh
python3 -m rumbo --root /path/to/project operator create_contract \
  --owner owner-id --file /path/to/approved-contract.json
```

The terminal shows the entire operation and requires a typed confirmation. This is an accidental-use safeguard, **not proof of human identity**. Same-account shell access can bypass it; use host policy and operating-system separation where that matters. Agents must never use this operator flow to impersonate the human.

3. Agents can use the MCP server or the explicit local CLI:

```sh
python3 -m rumbo --root /path/to/project --actor maker state
python3 -m rumbo --root /path/to/project --actor maker call claim_task \
  --json '{"task_id":"export","contract_revision":1,"lease_seconds":300}'
python3 -m rumbo --root /path/to/project --actor maker call submit_artifact \
  --json '{"task_id":"export","contract_revision":1,"path":"export.csv"}'
python3 -m rumbo --root /path/to/project --actor maker call run_checks \
  --json '{"task_id":"export","contract_revision":1,"artifact_revision":1}'
python3 -m rumbo --root /path/to/project --actor maker mcp
```

A remote MCP server can register files already in its mapped root, or receive explicitly authorized UTF-8 text with `rumbo_ingest_artifact` (128 KiB per file, 64 MiB total per project). `rumbo_read_artifact` lets reviewers inspect exact registered bytes. Upload receipts establish received-byte identity only, not a Git commit, repository provenance or test execution. It does not automatically see the user's laptop/ChatGPT workspace and has no repository-sync service. See [deployment](docs/DEPLOYMENT.md).

## OpenAI plugin packages

```sh
python3 scripts/package_release.py --kind local --output dist/rumbo-0.3.0-local-plugin.zip
python3 scripts/package_release.py --kind source --output dist/rumbo-0.3.0-source.zip
```

The local archive includes portable root `plugin.json` and `mcp.json`, a compatibility manifest, workflow skills and a real stdio launcher. The host must set `RUMBO_PROJECT_ROOT` to the approved project before launch; it fails rather than guessing. No marketplace entry or installation is performed by packaging.

For the public archive, supply verified real production values using the documented gates:

```sh
python3 scripts/package_release.py --kind submission \
  --production-config /path/to/verified-production.json \
  --output dist/rumbo-0.3.0-public-review.zip
```

The script never uploads. Local packaging does not establish public eligibility. The public archive excludes Claude lifecycle hooks, app references and local execution. [Current official requirements and links](docs/SUBMISSION-REQUIREMENTS.md).

## Claude Code adapter and migration

The Claude adapter remains in `rumbo/` with its existing hook layout and `scripts/record.py`. Its installation remains:

```text
/plugin marketplace add scking21/rumbo
/plugin install rumbo@rumbo
```

Those commands access whatever revision is actually on the remote; this unpushed local candidate is not available there. New engine state lives in `.rumbo/state.sqlite3`; legacy planning records remain `.rumbo/record.json`. Nothing is silently converted or deleted.

In 0.3, missing or unreadable transcripts now trigger the existing bounded Stop provenance warning/block behavior rather than silently skipping verification. Source checks respect `refs` and exclude done/rejected/replaced items. Missing/null refs use active items plus the objective; explicit `[]` uses only the objective. Historical records may need corrected refs. Read [migration details](docs/MIGRATION.md) and the [legacy specification](rumbo/SPEC.md).

## Verify

```sh
python3 -m unittest discover -s tests -v
(cd rumbo && python3 -m unittest discover -s tests -v)
python3 -m compileall -q rumbo scripts
```

The new tests cover real stdio and HTTP execution, restart, concurrent claims, stale evidence, principal isolation, malformed inputs, confined files, deterministic demo reproduction and extracted ZIP execution. Board source/Node runtime checks are separate from browser checks. Browser rendering and actual ChatGPT host integration were not verified in this environment. A read-only GitHub Actions workflow is included to run all tests with Chromium and fail on any skipped test; that CI run must be checked on the exact review commit, not assumed to have passed; [exact limits](docs/BOARD.md).

## Trust and limits

A passing receipt proves only its named condition. A matching hash proves byte identity, not correctness. A supplied report is not independently executed test evidence. A distinct reviewer principal gives attribution, not guaranteed organizational independence. The board cannot approve work.

Contracts and leases do not grant permission for any external action. The local CLI and ledger are within one trusted operating-system account. Hash chaining detects alteration relative to a preserved verifier/checkpoint, but an actor able to replace the database and verifier can replace history. There is no cryptographic witnessing, signature service, external checkpoint storage, model supervisor, universal agent enforcement, automatic repository sync or multi-project selector. The server uses one operator-provisioned project per authenticated subject; there is no automatic account/workspace signup. [Security details](SECURITY.md).

No Astra/Luna/Agents API/Decisions API integration or MCP Events is claimed. Deterministic tests and the core require no model service. Future instruction specialization would not be fine-tuning.

## Historical experiment

The original 20-run synthetic planning comparison measured version **0.1.0**, not this release or its multi-agent coordination. It suggested some schedule-conflict benefit while also showing invented facts, small samples and roughly doubled wall time. It is not evidence of 0.3 effectiveness. The full unchanged historical narrative and proposed research are preserved in [the 0.2.2 roadmap archive](docs/ROADMAP-HISTORY-0.2.2.md).

## Privacy and license

Local deterministic operation has no telemetry or network requests. The optional OAuth resource server sends presented access tokens to its explicitly configured authorization-server introspection endpoint. Connected AI hosts process tool output under their own terms. See [PRIVACY.md](PRIVACY.md).

MIT, Copyright (c) 2026 Corby King.
