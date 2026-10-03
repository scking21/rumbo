# Contract and evidence guide

The trusted human owner supplies the original request and approves the structured interpretation. Rumbo does not establish that a quote really came from a human, and never infers permission from a contract.

Example contract:

```json
{
  "project_id": "csv-export",
  "goal": "Ship a CSV export without adding runtime dependencies",
  "original_request": "Export CSV. No new runtime dependencies. I will review it.",
  "decision_owner": "owner",
  "constraints": ["No new runtime dependencies", "Human review before release"],
  "tasks": [{
    "id": "dependency-baseline",
    "title": "Preserve the runtime dependency baseline",
    "dependencies": [],
    "acceptance": [{"id": "dependencies", "kind": "json_equals", "key": "dependencies", "value": {}}]
  }]
}
```

Register the actual package.json as this task's artifact. This check rejects any changed runtime `dependencies` object, including version changes. It does not inspect devDependencies, optionalDependencies, peerDependencies, lockfiles, imports or install scripts. Add explicit `json_equals` criteria for each approved namespace and capture the complete human-reviewed baseline. An absent key fails rather than assuming an empty object. This is a concrete dependency-manifest guard, not a general software supply-chain proof.

## Check kinds

- `file_contains`: UTF-8 file contains the exact nonempty string `value`. Not a semantic test.
- `json_equals`: JSON object has top-level `key` exactly equal to JSON `value`. Whitespace/key ordering do not affect object equality; numeric representations remain deliberately exact under canonical JSON.
- `sha256`: bytes match the exact lowercase 64-character `value`. Not a quality assertion.
- `manual_review`: `prompt` names what a configured reviewer should inspect. Only a different configured reviewer actor can add pass/fail/uncertain evidence. It is an attributed assertion.

There is deliberately no arbitrary shell-command check. Run test suites in your already authorized environment, inspect their outputs, and describe them accurately as reviewer assertions unless a future separately trusted runner genuinely executes and attests them. Never upload a fabricated report as independent execution evidence.

## Ownership, revisions and status

Contracts have 1–100 tasks, each with 1–30 acceptance criteria and acyclic dependencies. Leases are 30–3600 seconds. An active claim by another actor conflicts; same actor can renew. Every artifact submission increments its revision, including identical bytes, and requires an active maker lease. Registered artifacts are regular files ≤5 MiB within the selected root. Remote uploads are valid UTF-8 text ≤128 KiB, stored content-addressed in `.rumbo/artifacts/` with a 64 MiB project quota. Their filename is display-only; source is explicitly `uploaded_text`. `rumbo_read_artifact` supports exact-revision inline inspection up to 128 KiB. These receipts prove received bytes, not repository provenance. Symlinks, traversal, known private/configuration directories and common credential files are refused.

Evidence binds task, contract revision, artifact revision and SHA-256. Acceptance also binds the exact evidence IDs. Later checks/assertions invalidate an earlier acceptance until the human decides again, even if they pass. Changing upstream acceptance invalidates downstream artifact lineage; accepting it again does not silently restore older downstream approval.

Contract edits use `operator revise_contract --owner owner --file revision.json` with `{ "expected_revision": 1, "reason": "Human-approved reason", "contract": { ...complete replacement contract... } }`. All tasks are conservatively invalidated on every contract change. Task removal hides that task from the current projection but its prior events remain in the ledger. The original project ID and decision owner cannot be changed through this release's revision operation.

After inspecting exact current evidence, the owner uses `operator decide --owner owner --file decision.json` with `{ "task_id":"dependency-baseline", "contract_revision":1, "artifact_revision":1, "outcome":"accepted", "reason":"Reviewed the actual manifest and its check" }`. `rejected` is the other outcome; the latest current decision supersedes earlier ones. No MCP action can make these decisions.

## Data and integrity

Events are stored in `.rumbo/state.sqlite3`, serialized transactions with a hash-linked payload chain. `python3 -m rumbo --root /path/to/project verify` opens the existing database in SQLite read-only mode and prints sequence count/head for external preservation by the operator. It does not create a missing project directory or main ledger, change database permissions, or initialize a contract; a missing or uninitialized contract is an error. Existing committed WAL history is included. SQLite may create its usual `-wal`/`-shm` companion files for a closed WAL-mode database, so this is SQL read-only verification, not a guarantee of zero auxiliary filesystem writes. Verification checks the ledger only, not current artifact availability or correctness; use `state` and exact artifact review for those separate questions. This does not create an external signature or witness. Back up the database under normal file/security policy while the service is stopped, or with SQLite's backup API. No automatic purge, replication, repair, migration or export is performed.
