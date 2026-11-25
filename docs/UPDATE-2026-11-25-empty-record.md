# November 25 Claude adapter 0.3.18: a record with only its objective gets one nudge

This builds on [Claude adapter 0.3.17](UPDATE-2026-11-25-told-assumptions.md). It adds one prompt-time line and one Stop-gate nudge for a record that holds nothing but its objective; nothing else the hooks check changes.

## Distribution identities

- The Claude adapter is **0.3.18**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

The Stop gate checks what the record holds: failing checks, assumed values, quotes the user never said. A record with only its objective holds none of these, so every stop passes, however many decisions, dates and amounts the user gives.

In repeated runs of every eval case on 0.3.15 (sonnet three times each, haiku three times each, opus twice each; graded by a sonnet judge; see [the results](EVAL-RESULTS-2026-11-25.md)), 39 sessions started a record. Four of them never added an item, over 3 to 15 turns:

| Session | Items and checks at the end | Failed gradings |
| --- | --- | --- |
| haiku, `01-workshop-full` | 0 and 0 | none |
| haiku, `02-launch-full` | 0 and 0 | 3 of 6: budget total, flyers that do not fit, the insurance condition |
| haiku, `11-rejected-option` | 0 and 0 | 1 of 2, as in the two haiku sessions that did keep a record |
| opus, `02-launch-full` | 0 and 0 | 4 of 6: ads first, budget total, dates to hit, flyers that do not fit |

Those two launch sessions account for 7 of the 8 failed launch gradings on haiku and opus. In the opus one, the user asked for both marketing options, and the final plan listed the newsletter as dropped. The agent had decided that on its own, and no record item held the user's words to check it against. The haiku launch session had started its record only because the Stop gate's no-record nudge asked for one; it then recorded nothing. No sonnet session left its record empty.

## What changed

- **Prompt hook.** While the record has no items and no checks, `show` adds one line after the objective: "rumbo: no decisions recorded yet. As the user decides, drafts or rules things out, add items with their exact words, and a check for any schedule, deadline or budget (see the commitments skill)." It also counts planning-looking prompts, as it does when there is no record.
- **Stop gate.** With such a record and no other problem, the gate blocks once per session, once the session has had two planning-looking prompts. It asks the agent to record the user's decisions so far with their exact words and a check for any schedule, deadline or budget, or to tell the user in one line why the work does not need them. It never blocks a stop that comes right after a block, and a new `.empty` marker keeps it to once per session.
- **Skill.** "A record with only its objective checks nothing: once you start one, record the decisions the user has already made, and keep adding them."

## Evidence

`rumbo/tests/test_empty_record.py` covers the change:

- The prompt hook names the empty record and stops once the record has an item.
- The Stop gate nudges after two planning prompts and not before, only once per session, never right after a block, and per session.
- A record with an item or a check is not nudged, and other problems (an unverified objective quote) are reported first.
- Nothing is counted without a session id.

This release is not yet verified live: the account running the evals reached its weekly usage limit before it could run. The four sessions above are the cases to rerun.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.17 merge on main. There is no data migration; an `.empty` marker left in the state directory is ignored by earlier versions.
