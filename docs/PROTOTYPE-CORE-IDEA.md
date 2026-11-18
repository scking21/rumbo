# Prototype: what survived live agent sessions

Rumbo keeps the person's own words as the source of truth, has scripts check facts rather than trusting an agent's claims, and leaves the final call to the person. This branch keeps two changes. Each one changed outcomes in live Claude Code sessions run on `main` and on this branch with the same prompts. Ideas that did not change outcomes were removed (see "What was tested and dropped").

## 1. Revisions that only stale what changed (engine)

Set `"revision_scope": "task"` in the contract. Each artifact, evidence item and decision is then stamped with a fingerprint of the task's id, title, dependencies and acceptance criteria, plus the shared goal and constraints. A contract revision makes a task stale only when its fingerprint changes.

- Rewording one task no longer un-accepts the others.
- Changing the goal or a constraint still stales every task.
- If the field is omitted, or removed in a later revision, the old rule applies and every revision stales every task.
- The owner portal's revision form keeps the field, and the board compares records against the task's current fingerprint. Each task's fingerprint is computed once per projection.

The hosted Sites runtime (`openai-sites/`) does not have this feature. Its parity tests still pass because the default behaviour is unchanged.

| Scenario | main | branch |
|---|---|---|
| Owner rewords only the docs task (scenario A, 3 turns) | All 3 tasks stale, 9 of 9 runs | Only docs stale, 11 of 11 runs |
| Same revision inside an 11-turn conversation (scenario F) | All 3 stale and all 3 re-accepted, in the 2 runs where nothing else changed | Only docs re-accepted, in the 1 such run |

In 3 of the 6 scenario F runs, the agent had already edited `export.py` for an earlier request (adding `to_tsv`). That stales the code tasks on both arms, so in a realistic conversation the saving shows up less often than in scenario A.

## 2. The decision-record Stop gate passes a block the agent already answered (plugin)

Before this change, an unchanged problem blocked again right after the agent replied, up to the session's three blocks. In the long planning conversation (scenario G), that happened over an assumption the agent had already disclosed in its first reply. The agent repeated itself up to three times in one turn, and the session had no blocks left for anything later.

Now an unchanged repeat in the same stop passes. In a later stop, an open problem still gets the one-line status block, and the three-per-session limit is unchanged.

| Scenario G (10 turns, written in the owner's own prompting style) | main | branch |
|---|---|---|
| Runs with 3 blocks in a single turn | 3 of 6 | 0 of 4 |
| Most blocks in one turn | 3 | 1 |
| Final summary matched ground truth (graded) | 6 of 6 | 4 of 4 |
| Mean session cost | $0.36 | $0.34 |

## What was tested and dropped

There were 83 sessions in total, using sonnet plus haiku for the CI scenario. Costs below are per session. Claude Code reports cumulative cost across `--resume`, so each figure is the session's final turn, not a sum of its turns.

- **Engine Stop gate.** In scenario A the agent told the user that accepted work was affected in 8 of 9 sessions with a gate and 8 of 11 without one, a gap within run-to-run noise. Its `UNCLAIMED_CHANGES` check blocked 6 of 6 small requested edits (0 on `main`). A narrower version that only reported lost acceptance stopped those blocks, but showed no benefit and cost about 7% more in the six-turn scenario E ($0.15 against $0.14). The first version cost 19% more ($0.17).
- **Commit artifacts and CI attestations.** In 12 sessions the code passed its tests on the first try on both arms, so CI never had anything to catch.
- **Constraints tied to quoted words.** No session on either arm broke the constraint.

These are small samples on synthetic projects. "Dropped" means the idea didn't help in these scenarios, not that it never could.
