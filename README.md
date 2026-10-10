# Rumbo

Know what your coding agents changed, what evidence supports it, and what still needs your decision.

Rumbo is a local-first contract and evidence ledger for agent-assisted software work. You agree on a goal and bounded tasks; agents claim work, register exact artifact bytes and add evidence; the human owner accepts or rejects the result. Changing requirements, artifact bytes or dependency decisions makes earlier acceptance stale.

Use it when multiple workers hand off work, you need to preserve agreed constraints, or “the checks passed” is not enough to decide whether a result is ready. Rumbo records the agreement and evidence; it does not supervise models or guarantee correctness.

*Rumbo* is Spanish for a ship's course or heading.

## Start here

- **See the board:** run [the local synthetic demo](#try-the-deterministic-demo) below
- **Try the full workflow:** follow [the copy-paste local quickstart](docs/QUICKSTART.md), from contract to human acceptance
- **Connect an agent:** use [the installed local plugin setup](docs/INSTALLED-PLUGIN.md) after initializing an owner-approved project

Local file registration works on files in an explicitly selected project root and detects later changes there. Remote/hosted workflows use server-mapped files or explicitly uploaded bytes; they cannot see your laptop or detect later edits to the original uploaded file. The [experimental Sites runtime](openai-sites/README.md) has an owner-private deployment; managed authentication and reviewer access remain unverified.

## Requirements

Python 3.9+ on POSIX (Linux/macOS) is required; tested on Linux/Python 3.12. The core and server use the standard library. Windows is not supported by the current symlink-safe file-opening implementation. The optional OAuth owner portal requires Python 3.10+ and Authlib/Requests; the optional WorkOS profile also requires PyJWT/cryptography; it was tested on Python 3.12. Development-only schema and browser checks use optional tooling.

No installation or third-party Python packages are needed for the demo and local quickstart when run from this repository root. Obtain the source checkout first, then keep your terminal in the directory containing this README and `rumbo/`.

## Try the deterministic demo

From this repository root, paste the following into a POSIX shell. Each run creates a fresh temporary project and lets the OS choose an available port:

```sh
demo_root="$(mktemp -d "${TMPDIR:-/tmp}/rumbo-demo.XXXXXX")"
python3 -m rumbo --root "$demo_root" demo
python3 - "$demo_root" <<'PYCONFIG' > "$demo_root/server.json"
import json, sys
print(json.dumps({"mode": "demo", "demo_root": sys.argv[1]}))
PYCONFIG
python3 -m rumbo serve --config "$demo_root/server.json" --port 0
```

The server prints `Rumbo HTTP listening on 127.0.0.1:PORT`. Open `http://127.0.0.1:PORT` on the same computer, substituting the printed port; press Ctrl-C in the terminal to stop it. To choose a fixed port instead, replace `--port 0` with an available port such as `--port 8765`.

The data is visibly synthetic. It includes accepted export work, a failed dependency-baseline check, a reviewer assertion awaiting a human, a stale document and blocked/unclaimed work. Demo mode provides no writable MCP access and refuses to expose a project if its current `demo` flag is false. No model calls, accounts, passwords or telemetry are needed. The temporary project remains available for inspection in `$demo_root`.

## Use a real project

Start with [the complete local quickstart](docs/QUICKSTART.md). It creates a disposable project, supplies the exact contract and artifact used by every command, and shows the owner-confirmed acceptance step. Then adapt [the contract guide](docs/CONTRACTS.md) to the real request and use the actual task IDs and current revisions from `state`.

Add `.rumbo/` to the project's `.gitignore`: its private state contains the original request and review text. The human owner initializes the contract through the trusted local operator flow. Its typed confirmation is an accidental-use safeguard, **not proof of human identity**; agents must never impersonate the owner. Use host policy and operating-system separation where that matters.

Agents can use the explicit local CLI shown in the quickstart or [the installed MCP plugin](docs/INSTALLED-PLUGIN.md). A remote MCP server can register files already in its mapped root, or receive explicitly authorized UTF-8 text with `rumbo_ingest_artifact` (128 KiB per file, 64 MiB total per project). `rumbo_read_artifact` lets reviewers inspect exact registered bytes. Upload receipts establish received-byte identity only, not a Git commit, repository provenance or test execution. There is no automatic repository sync. See [deployment](docs/DEPLOYMENT.md).

## Components and release status

The Python engine is **0.3.2**, the OpenAI adapter is **0.3.3**, and the Claude adapter is **0.3.4**. See [the current update notes](docs/UPDATE-2026-10-09-B.md) and [the previous update and rollback notes](docs/UPDATE-2026-10-09.md). They are versioned independently; a component version does not establish hosted or installed-host verification.

Rumbo now has a working provider-neutral contract/evidence engine, CLI, MCP transports, a read-only acceptance board and OpenAI plugin packaging. It records **agreed goal → bounded task → exact artifact → evidence → human decision**.

The separate [OpenAI Sites runtime](openai-sites/README.md) has an **owner-private deployment**. It is an experimental hosted upload workflow, not the Python executable engine; managed authentication and reviewer access remain unverified. No public-directory upload, submission, approval or publication is claimed. The local Python plugin remains a separate reviewable distribution.

A Sites review-draft ZIP can be prepared before portal verification, with unresolved fields omitted and a separate honest readiness report. Final submission still needs verified access, required review materials and owner review. See [draft packaging and submission sequence](docs/DRAFT-PACKAGING.md); historical local-only verification is in [the earlier release report](docs/RELEASE-REVIEW.md).

The goal remains a free public plugin in the OpenAI ecosystem, using the existing Sites candidate or another supported OpenAI route without additional-cost services or an external-hosting fallback. No new dashboard work is planned. A synthetic local-engine walkthrough and approved policy review copy are published in the [OpenAI-hosted review materials](https://rumbo-review-materials.aggie-king21.chatgpt.site/). Independent security-audit approval is not a mandatory submission gate; existing test coverage and its limits remain documented. See [current scope and milestones](docs/SUBMISSION-REQUIREMENTS.md#current-scope-and-milestones).

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
- Operator-only SQLite-consistent backup/restore with historical-upload verification
- Optional WorkOS Connect JWT + active-introspection profile and a nonroot persistent deployment kit
- Existing Claude Code planning adapter, with stricter provenance fixes

## OpenAI plugin packages

```sh
python3 scripts/package_release.py --kind local --output dist/rumbo-openai-0.3.3-local-plugin.zip
python3 scripts/package_release.py --kind source --output dist/rumbo-0.3.2-source.zip
```

The local archive includes portable root `plugin.json` and `mcp.json`, a compatibility manifest, workflow skills and a real stdio launcher. The installed server starts unbound. Its owner provisions approved aliases in `PLUGIN_DATA/projects.json`; the agent selects one alias once per process with a unique worker identity. Legacy `RUMBO_PROJECT_ROOT`, `RUMBO_ROLE` and `RUMBO_ACTOR` cannot configure this launcher. See [installed setup and lease limits](docs/INSTALLED-PLUGIN.md). No marketplace entry or installation is performed by packaging.

For the current Sites candidate, prepare a draft without inventing completed portal checks:

```sh
python3 scripts/package_release.py --kind review-draft \
  --mcp-url https://rumbo-review-candidate.aggie-king21.chatgpt.site/mcp \
  --output dist/rumbo-sites-review-draft.zip
```

This writes the ZIP and `dist/rumbo-sites-review-draft.readiness.json`. The draft uses Sites-specific skills, project keys, server-issued worker sessions and its actual review cases. It omits unresolved publisher identity, legal/support URLs and video. Its endpoint is currently owner-private; creating this archive proves no managed login, portal access or submission readiness. Node.js 24+ and the `jsonschema` developer dependency are needed for source-catalog and pinned-schema validation. See [the full packaging contract](docs/DRAFT-PACKAGING.md).

The legacy final-gated archive below is for the **Python remote profile**, not a way to promote the Sites draft. It retains the complete external-attestation requirements:

```sh
python3 scripts/package_release.py --kind submission \
  --production-config /path/to/verified-production.json \
  --output dist/rumbo-openai-0.3.3-public-review.zip
```

The script never uploads. Local packaging does not establish public eligibility. The public archive excludes Claude lifecycle hooks, app references and local execution. [Current official requirements and links](docs/SUBMISSION-REQUIREMENTS.md).

## Claude Code adapter and migration

The Claude adapter lives in `rumbo/` beside the engine modules (`.claude-plugin/`, `hooks/`, `skills/`, `scripts/record.py`), because the Claude directory submission reads the plugin from that path. It uses none of the engine code. It is versioned independently of the engine and the OpenAI plugin. Its installation remains:

```text
/plugin marketplace add scking21/rumbo
/plugin install rumbo@rumbo
```

Those commands access the revision actually on the remote; verify its branch/version before relying on candidate behavior. New engine state lives in `.rumbo/state.sqlite3`; legacy planning records remain `.rumbo/record.json`. Nothing is silently converted or deleted.

In 0.3, missing or unreadable transcripts now trigger the existing bounded Stop provenance warning/block behavior rather than silently skipping verification. Source checks respect `refs` and exclude done/rejected/replaced items. Missing/null refs use active items plus the objective; explicit `[]` uses only the objective. Historical records may need corrected refs. Read [migration details](docs/MIGRATION.md) and the [legacy specification](claude-plugin/rumbo/SPEC.md).

## Verify

```sh
python3 -m unittest discover -s tests -v
(cd rumbo && python3 -m unittest discover -s tests -v)
python3 -m compileall -q rumbo scripts
```

The new tests cover real stdio and HTTP execution, restart, concurrent claims, stale evidence, principal isolation, malformed inputs, confined files, deterministic demo reproduction and extracted ZIP execution. Board source/Node runtime checks are separate from browser checks. Browser coverage and actual ChatGPT host integration are separate claims. The Sites candidate has its own synthetic Chromium suite and exact-commit CI; managed host authentication remains unverified. A read-only GitHub Actions workflow is included to run all tests with Chromium and fail on any skipped test; that CI run must be checked on the exact review commit, not assumed to have passed; [exact limits](docs/BOARD.md).

## Deployment and recovery

[Operations](docs/OPERATIONS.md) covers the nonroot/read-only container, persistent roots, request-limiting TLS proxy, status-only health, safe logs and exact setup gates. [WorkOS](docs/WORKOS.md) documents the optional strong-verification profile while the generic OAuth provider remains supported. [Backups](docs/BACKUP.md) are explicit operator actions, not automatic retention or self-service export. No service or credentials are provisioned by these files.

## Trust and limits

A passing receipt proves only its named condition. A matching hash proves byte identity, not correctness. A supplied report is not independently executed test evidence. A distinct reviewer principal gives attribution, not guaranteed organizational independence. The board cannot approve work.

Contracts and leases do not grant permission for any external action. The local CLI and ledger are within one trusted operating-system account. Hash chaining detects alteration relative to a preserved verifier/checkpoint, but an actor able to replace the database and verifier can replace history. There is no cryptographic witnessing, signature service, external checkpoint storage, model supervisor, universal agent enforcement, automatic repository sync or multi-project selector. The server uses one operator-provisioned project per authenticated subject; there is no automatic account/workspace signup. [Security details](SECURITY.md).

No Astra/Luna/Agents API/Decisions API integration or MCP Events is claimed. Deterministic tests and the core require no model service. Future instruction specialization would not be fine-tuning.

## Historical experiment

The original 20-run synthetic planning comparison measured version **0.1.0**, not this release or its multi-agent coordination. It suggested some schedule-conflict benefit while also showing invented facts, small samples and roughly doubled wall time. It is not evidence of 0.3 effectiveness. The full unchanged historical narrative and proposed research are preserved in [the 0.2.2 roadmap archive](docs/ROADMAP-HISTORY-0.2.2.md).

## Privacy and license

Local deterministic operation has no telemetry or network requests. The optional OAuth resource server sends presented access tokens to its explicitly configured authorization-server introspection endpoint. Connected AI hosts process tool output under their own terms. See [PRIVACY.md](PRIVACY.md).

The separate owner-private hosted candidate is deployed at v4 (Sites source `c477594`), with the tested owner-browser deletion and expired-session cleanup controls from GitHub source `efb8fa6`. Deletion removes project content but retains pseudonymous/linkable hash-derived guard keys indefinitely to prevent delayed uploads from restoring it. It does not erase exported/client copies or establish provider backup/log deletion timing. See [hosted data handling and retention](openai-sites/PRIVACY.md).

MIT, Copyright (c) 2026 Corby King.
