# Prototype: revisions that only stale what changed

Rumbo keeps the person's own words as the source of truth, has scripts check facts rather than trusting an agent's claims, and leaves the final call to the person. This branch keeps one change to the local Python engine, chosen because it was the only one of five prototyped ideas that changed outcomes in live agent sessions (see "What was tested and dropped" below).

Existing contracts behave exactly as before. The hosted Sites runtime (`openai-sites/`) does not have the feature. Its parity tests still pass because the default behaviour is unchanged.

## How it works

Set `"revision_scope": "task"` in the contract. Each artifact, evidence item and decision is then stamped with a fingerprint of the task's id, title, dependencies and acceptance criteria, plus the shared goal and constraints. A contract revision makes a task stale only when its fingerprint changes.

- Rewording one task no longer un-accepts the others.
- Changing the goal or a constraint still stales every task.
- If the field is omitted, or removed in a later revision, the old rule applies and every revision stales every task.
- The owner portal's revision form keeps the field, and the board compares records against the task's current fingerprint.

## Evidence from live sessions

Real headless Claude Code sessions ran against synthetic projects, with the plugin from `main` and from this branch, using the same prompts. In scenario A the owner accepts three tasks, then revises only the docs task's acceptance criterion.

| | main | branch |
|---|---|---|
| Tasks stale right after the docs-only revision | 3 of 3, in 3 of 3 runs | 1 of 3 (docs), in 3 of 3 runs |
| Tasks the owner had to accept again | 3 per run | 1 per run |

## What was tested and dropped

Round 2 used 30 sessions (sonnet, plus haiku for the CI scenario).

- **Engine Stop gate (`ACCEPTANCE_LOST`, `UNCLAIMED_CHANGES`).** It surfaced nothing that `main` missed: the agent told the user that accepted work was affected in 3 of 3 runs on both arms (scenario A) and flagged the constraint conflict in 3 of 3 runs on both arms (scenario E, six turns). It blocked every small edit outside the contract (6 of 6 edit turns in scenario B, 0 on `main`), and raised session cost by about 10% in A and 28% in E.
- **Commit artifacts and CI attestations.** In 12 sessions (6 sonnet, 6 haiku) the code passed its tests on the first try on both arms, so CI never had anything to catch. In 1 of 6 branch sessions the task stayed at `produced`, because the agent didn't run the file check after registering the commit.
- **Constraints tied to quoted words.** Dropped after round 1: no session on either arm broke the dependency constraint it was meant to protect.

These results come from a small number of runs on synthetic projects. They show the dropped ideas didn't help in these scenarios, not that they never could.
