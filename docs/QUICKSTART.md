# Local quickstart: from agreement to acceptance

Run the blocks below, in order, in the **same terminal at the repository root**.
You need Python 3.9+ and a POSIX shell on Linux/macOS. No package installation,
model service, account or network access is needed. Keep the terminal in the
checkout: `--root` selects the project whose state Rumbo manages; it does not
change where Python finds the source package.

This exercise creates a new temporary project with synthetic data. The two
`operator` commands are for **you, the human owner**, to inspect and confirm.
Agents must not run them on your behalf. Do not pipe confirmations into them.

## 1. Prepare the example agreement

This contract defines one task, `export`, and a deliberately narrow check: the
file must contain `name,amount`. Passing that check does not prove CSV correctness.

```sh
project_root="$(mktemp -d "${TMPDIR:-/tmp}/rumbo-project.XXXXXX")"
printf '.rumbo/\n' > "$project_root/.gitignore"
cat > "$project_root/contract.json" <<'JSON'
{
  "project_id": "quickstart-csv",
  "goal": "Create a synthetic CSV for the local quickstart",
  "original_request": "Make a CSV with name and amount columns and one Demo row. I will review it.",
  "decision_owner": "quickstart-owner",
  "constraints": ["Synthetic data only", "Human review before acceptance"],
  "tasks": [{
    "id": "export",
    "title": "Create the sample CSV",
    "dependencies": [],
    "acceptance": [{"id": "header", "kind": "file_contains", "value": "name,amount"}]
  }]
}
JSON
printf 'Temporary project: %s\n' "$project_root"
```

## 2. Approve the contract as its human owner

The command prints the complete contract. Read it, then type
`CONFIRM create_contract` at the prompt if you agree. This creates contract
revision `1`.

```sh
python3 -m rumbo --root "$project_root" operator create_contract \
  --owner quickstart-owner --file "$project_root/contract.json"
```

The terminal requirement is an accidental-use safeguard, **not proof of human
identity**. Same-account shell access can bypass it; use host policy and OS
separation where that matters.

## 3. Claim the task, create its artifact and run the check

These are worker actions. The one-hour lease belongs to `quickstart-maker`.
If it expires before submission, rerun the claim command with the same actor.

```sh
python3 -m rumbo --root "$project_root" --actor quickstart-maker call claim_task \
  --json '{"task_id":"export","contract_revision":1,"lease_seconds":3600}'
printf 'name,amount\nDemo,5\n' > "$project_root/export.csv"
python3 -m rumbo --root "$project_root" --actor quickstart-maker call submit_artifact \
  --json '{"task_id":"export","contract_revision":1,"path":"export.csv"}'
python3 -m rumbo --root "$project_root" --actor quickstart-maker call run_checks \
  --json '{"task_id":"export","contract_revision":1,"artifact_revision":1}'
python3 -m rumbo --root "$project_root" state
```

The task should now have status `checks_passed`, artifact revision `1` and a
passing `header` receipt. It is **not accepted yet**. Repeating artifact
submission increments its revision, even for identical bytes; use the current
revision printed by `state` if you repeat steps.

## 4. Inspect and decide as the human owner

Inspect the exact file and current state before accepting this synthetic example:

```sh
cat "$project_root/export.csv"
python3 -m rumbo --root "$project_root" state
cat > "$project_root/decision.json" <<'JSON'
{
  "task_id": "export",
  "contract_revision": 1,
  "artifact_revision": 1,
  "outcome": "accepted",
  "reason": "Reviewed the synthetic CSV contents and the narrow header check"
}
JSON
python3 -m rumbo --root "$project_root" operator decide \
  --owner quickstart-owner --file "$project_root/decision.json"
```

Read the printed decision and type `CONFIRM decide` only if it represents your
decision. You can instead set `outcome` to `rejected` and write your actual reason.

```sh
python3 -m rumbo --root "$project_root" state
python3 -m rumbo --root "$project_root" verify
```

After acceptance, `state` should show `accepted`. `verify` checks ledger integrity;
it does not establish artifact quality. Later changes to the local `export.csv`
make the task stale when state is read. The files remain in the printed temporary
directory for inspection; nothing is uploaded or automatically deleted.

## Apply it to your work

- Choose your actual project root and add `.rumbo/` to its `.gitignore`. State
  includes the original request and private review text
- Have the owner prepare and approve the actual request, task IDs, dependencies
  and acceptance criteria using [the contract guide](CONTRACTS.md). The quickstart
  header check is a teaching example, not an adequate release criterion
- Use the current contract/artifact revisions from `state`, rather than assuming
  they remain `1`
- Connect an agent with [the installed local plugin setup](INSTALLED-PLUGIN.md),
  or configure a [separately authorized MCP transport](DEPLOYMENT.md)

Local file registration observes files inside the selected project root. A
remote server sees only its mapped files or explicitly uploaded bytes; it cannot
read your laptop or notice edits to the original uploaded file. See the
[separate experimental Sites runtime](../openai-sites/README.md) for that profile.
