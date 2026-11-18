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
| Tasks stale right after the docs-only revision | 3 of 3, in 9 of 9 runs | 1 of 3 (docs), in 11 of 11 runs |
| Tasks the owner had to accept again | 3 per run | 1 per run |

## What was tested and dropped

Three rounds used 67 sessions (sonnet, plus haiku for the CI scenario).

- **Engine Stop gate.** In scenario A the user's follow-up un-accepts finished work. The agent told the user so in 8 of 9 sessions with a gate and 8 of 11 without one, a gap within run-to-run noise. In the six-turn scenario E both arms flagged the constraint conflict and the needed re-acceptance in every graded run. The first version also blocked on `UNCLAIMED_CHANGES`, which blocked every small requested edit outside the contract (6 of 6 edit turns in scenario B, 0 on `main`). A narrower version that only reported lost acceptance stopped those false blocks (0 of 4), but still made sessions about 15% more expensive in E.
- **Commit artifacts and CI attestations.** In 12 sessions (6 sonnet, 6 haiku) the code passed its tests on the first try on both arms, so CI never had anything to catch. In 1 of 6 branch sessions the task stayed at `produced`, because the agent didn't run the file check after registering the commit.
- **Constraints tied to quoted words.** Dropped after round 1: no session on either arm broke the dependency constraint it was meant to protect.

These results come from a small number of runs on synthetic projects. They show the dropped ideas didn't help in these scenarios, not that they never could.
