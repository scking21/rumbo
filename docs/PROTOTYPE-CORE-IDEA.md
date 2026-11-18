# Prototype: strengthening the core idea

Rumbo keeps the person's own words as the source of truth, has scripts check facts rather than trusting an agent's claims, and leaves the final call to the person. This prototype adds five features to the local Python engine and the Claude plugin. Existing contracts behave exactly as before. Every new feature is opt-in, through a new contract field, check kind, action or hook.

The hosted Sites runtime (`openai-sites/`) does not have these features. Its parity tests still pass because the default behaviour is unchanged.

## 1. Constraints tied to the owner's words

A constraint can now be an object instead of a string:

```json
{"text": "Column order unchanged", "quote": "Keep the column order exactly as it is today."}
```

`quote` must appear word for word in `original_request`, ignoring differences in whitespace. If it doesn't, the contract is refused with `QUOTE_NOT_IN_REQUEST`. Plain string constraints still work. The board shows the quote under the constraint.

## 2. CI results as attested evidence

- A new check kind, `{"id": "tests", "kind": "ci_status", "name": "unit tests"}`, is satisfied only by a CI attestation.
- A new host role, `ci`, is configured like any other principal, for example a token that only your CI job holds. That principal can call `attest_ci` (MCP `rumbo_attest_ci`) and nothing else, and no other role can call `attest_ci`.
- An attestation names the commit it tested. It is refused if that commit is not the task's registered commit, or if the CI actor is the artifact's maker.

Rumbo still runs no tests itself. The evidence is labelled `ci_attestation` and says who reported it.

## 3. A Git commit as the unit of work

`submit_commit` (MCP `rumbo_submit_commit`) registers a full commit id as a task's artifact. It records the files the commit changed, and its identity is the SHA-256 of the commit object. The project root must be the repository's top level.

`file_contains`, `json_equals` and `sha256` checks can name a `file`. That file is read from the commit (`git cat-file blob <commit>:<file>`), not from the working tree. Private paths such as `.env` are refused, as they are for file artifacts. Git runs only fixed plumbing commands (`rev-parse`, `cat-file`, `diff-tree`) with no shell, so no filters, text conversion or external diff tools are involved.

## 4. Revisions that only stale what changed

Set `"revision_scope": "task"` in the contract. Each artifact, evidence item and decision is then stamped with a fingerprint of the task's id, title, dependencies and acceptance criteria, plus the shared goal and constraints. A contract revision makes a task stale only when its fingerprint changes. Rewording one task no longer un-accepts the others. Changing the goal or a constraint still stales every task. If the field is omitted, the old rule applies and every revision stales every task.

## 5. A Stop gate for the engine ledger

The Claude plugin now runs `scripts/engine-gate.sh` as a second Stop hook. The hook does nothing unless the project has `.rumbo/state.sqlite3`. It opens the ledger read-only and blocks (at most 3 times per session) when:

- `ACCEPTANCE_LOST`: a task the owner accepted is no longer accepted, because its bytes, commit, dependencies or agreed definition changed, or new work replaced it.
- `UNCLAIMED_CHANGES`: the Git working tree has changes (outside `.rumbo/`) while no task is claimed.

The hook never writes the ledger. Its per-session counter lives under `$RUMBO_STATE_DIR/engine-gate`.

## Verification

`tests/test_core_idea.py` covers each feature end to end against a real SQLite ledger and a real Git repository. The gate is tested as a subprocess. `tests/test_board.py` has one browser test for the new board sections.

## Not done in this prototype

- The Sites runtime and its JavaScript engine.
- MCP `inputSchema` support for quoted constraints in the owner portal forms.
- Signed or provider-verified CI results. Today an attestation is as trustworthy as the CI principal's token.
- Configuring the engine gate (for example, turning off `UNCLAIMED_CHANGES` for exploratory sessions).
