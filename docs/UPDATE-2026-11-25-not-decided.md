# November 25 Claude adapter 0.3.20: undecided items before a write, and no record ids for the user

This builds on [Claude adapter 0.3.19](UPDATE-2026-11-25-told-conflicts.md). It adds lines to what the pre-write hook shows and one clause to the Stop gate's block; what the hooks check is unchanged.

## Distribution identities

- The Claude adapter is **0.3.20**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gaps

Both come from the live runs on 0.3.18 ([results](EVAL-RESULTS-2026-11-25.md#0318-against-0315)).

- **A "no" read as a choice.** In `11-rejected-option` the user rules out the hotel ballroom and never picks the community center. Every haiku plan, on 0.3.15 and on 0.3.18, listed the community center as decided. In one haiku session on each version, the record itself held the community center as `uncertain`. The plan still called it decided, even after 0.3.18 told the skill that only `commitment` items are written as decided. The pre-write hook, which runs right before the plan is written, showed only failing or unsourced checks, and this record had none.
- **Record ids shown to the user.** Two haiku replies named record ids: "**Catering (C2):** The $180 figure is my assumption" and "C1 and C2 are open, and his terms are recorded as I8". No session had done so on 0.3.15. Both came right after a full Stop block, which lists its problems by id. The short repeat block and the prompt-time summary already said to describe problems "in the user's terms rather than the record's ids"; the full block's closing instructions did not.

## What changed

- **Pre-write hook.** Besides the record's open problems, the hook now lists each live item the user has not decided: status `exploring`, `preference`, `draft`, `authorized`, `deferred` or `uncertain`, and not replaced. Each is a line such as `NOT DECIDED I2 [uncertain]: Community center at $900`. They are introduced with "rumbo: the user has not decided the items marked NOT DECIDED. In what you write, present each as open, a proposal or something to confirm, never as decided." At most 8 items are shown, then "... and N more items not decided". As with problems, a set of lines is shown once per session while it stays the same.
- **Stop block.** The block's closing instructions now include "describe each in the user's terms, never by the record's ids, which they never see".
- **Skill.** "Before writing" names the `NOT DECIDED` lines and says to present each undecided item as open.

## Evidence

- `rumbo/tests/test_drift_hooks.py` covers the hook's undecided lines. With no problems, they come with their own introduction. A rejected, committed or replaced item is left out. The lines are shown once per session while unchanged, and nothing is shown once every item is decided. Problems come first, and the list is capped at 8.
- `rumbo/tests/test_record.py` checks the block's new clause.

These changes add text, so only live runs can show whether models follow it.

**Live.** Haiku ran the three cases these changes come from three times each, graded by the same sonnet judge. A 5-hour usage limit cut seven of the nine sessions: `--rerun` ran them again from the start, and `--regrade --errors-only` gave the four verdicts the judge had missed. Case 11 did not run on 0.3.19.

| Case | Grader | 0.3.18 | 0.3.19 | 0.3.20 |
| --- | --- | --- | --- | --- |
| `11-rejected-option` | a "no" is not a choice | 0/3 | - | 0/3 |
| | ballroom ruled out | 3/3 | - | 3/3 |
| `05-draft-is-not-a-decision` | draft and idea stay open | 3/3 | 1/3 | 3/3 |
| | the other two graders | 6/6 | 6/6 | 5/6 |
| `01-workshop-full` | all six graders | 18/18 | 18/18 | 14/18 |

- **The undecided lines reached no plan.** In `11-rejected-option` each session wrote `plan.md` before it had a record and started one only when the Stop gate asked, after the plan; each plan listed the community center as decided. `05-draft-is-not-a-decision` writes no file. The lines were shown in two workshop sessions, once each, at turns 14 and 15. One of them was stale: a preference for the maker-space team that a later commitment had settled without replacing it. That plan still named the team as the only speaker.
- **A hook's added context comes after the write.** Claude Code attaches a `PreToolUse` hook's `additionalContext` to the tool's result, once the file is written. In the saved runs on 0.3.15 and 0.3.18, agents changed the file again after 11 of the 42 contexts the pre-write hook added, and haiku after none. So the lines can shape only a later edit. The next release holds the write once instead.
- **The workshop misses** come from two sessions that kept little or no record. One never started a record in 15 turns, though the Stop gate asked at turn 2. The other recorded five items and no check. Their plans left out the $300 line cap or what the printer needs, and the session without a record offered Dr. Okafor again. On 0.3.18 and 0.3.19 every haiku workshop session kept a record of 10 to 17 items and 2 to 5 checks. Neither session saw an undecided line before those plans, so this release did not cause the misses. With 3 sessions per case, they show how much haiku varies here.
- **The lodging miss** in `05-draft-is-not-a-decision`: that session recorded "We'll take it" as `uncertain`, and its summary kept the lodge open.
- **Record ids.** No reply named a record id. On 0.3.18, two of these nine sessions had, each right after a full Stop block. Here only one session had full blocks after turn 2 (two, about quotes), and neither reply after them named an id.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.19 merge on main. There is no data migration.
