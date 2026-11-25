# Eval results across models, Claude adapter 0.3.15

Every bundled eval case was run on the Claude adapter 0.3.15 with three models: sonnet and haiku three times each and opus twice. That is 11 cases, 88 sessions and 248 gradings. The hooks in 0.3.15 are those of 0.3.14; 0.3.16 to 0.3.18 change only what the Stop gate reads and when the hooks nudge (see [the 0.3.18 notes](UPDATE-2026-11-25-empty-record.md)).

## How the runs were made

- `scripts/claude_multiturn_eval.py` drove each case's turns through `claude -p --resume` with the plugin loaded from a copy of the 0.3.15 tree, so every session ran the same version.
- Cases `09-unit-price-budget`, `10-overnight-window` and `11-rejected-option` are new in `rumbo/evals`. They check a budget given as a price per person, a window that runs past midnight, and a "no" to one option that leaves another undecided.
- Every grading was made, or made again, by a sonnet judge with three votes per grader. Each vote reasons in a few sentences and ends with a `VERDICT:` line, and a grader needs two matching votes. Of the 232 gradings a judge made, 8 had split votes: 6 on haiku's sessions, 2 on opus's, none on sonnet's. The other 16 gradings check files (no record created) and need no judge.
- Usage limits cut off two batches of sessions and two rounds of grading. Interrupted sessions were rerun, and `--regrade DIR --errors-only` asked the judge again only for the verdicts it had not given.

## Results

| Model | Sessions | Gradings passed | Stop blocks | Cost |
| --- | --- | --- | --- | --- |
| sonnet | 33 | 93 of 93 | 7 | $8.51 |
| haiku | 33 | 83 of 93 | 11 | $0.62 |
| opus | 22 | 54 of 62 | 14 | $13.14 |

No reply in any session named a record id such as C1 or I3 to the user. In the two cases where no record should be started (`06-neg-python-question` and `07-neg-weekday`) no model started one.

The failed gradings:

| Case | Grader | sonnet | haiku | opus |
| --- | --- | --- | --- | --- |
| `02-launch-full` | ads first, newsletter second | 3/3 | 3/3 | 1/2 |
| | budget total | 3/3 | 2/3 | 1/2 |
| | dates to hit | 3/3 | 3/3 | 1/2 |
| | flyers do not fit | 3/3 | 2/3 | 1/2 |
| | insurance is a condition | 3/3 | 2/3 | 1/2 |
| `04-deadline-after-event` | no invented year | 3/3 | 0/3 | 0/2 |
| `05-draft-is-not-a-decision` | draft and idea stay open | 3/3 | 2/3 | 2/2 |
| `11-rejected-option` | a "no" is not a choice | 3/3 | 0/3 | 1/2 |

Every other grader passed in every session.

## What the failures show

- **A record that stays empty.** 39 sessions started a record. Four of them never added an item: three on haiku and one on opus. The two launch sessions among them account for 7 of the 8 failed launch gradings. In the opus one, the user asked for both marketing options, and the final plan listed the newsletter as dropped. The agent had decided that on its own, and no record item held the user's words. The haiku launch session had started its record only because the Stop gate asked for one. 0.3.18 adds a prompt-time line and a one-time Stop nudge for such a record.
- **A year the user never gave.** In `04-deadline-after-event`, every haiku and opus reply put the dates in 2027, the year of the next May 9 after the run date, often saying it was assumed ("Assuming the next May 9 (2027)"). No sonnet reply did. None of these sessions started a record, so the commitments skill, which says not to add a year, was never loaded. A one-turn request gets only the prompt-time nudge to start a record.
- **A "no" read as a choice.** In `11-rejected-option` the user rules out the hotel ballroom and never picks the community center. Every haiku plan and one of the two opus plans listed the community center as decided. In one haiku session the record itself held the community center as `uncertain`, and the plan still called it decided. The hooks warn before a write only about failing or unsourced checks, not about items that are not decided, and the skill had not said that an item's status decides how it is written. 0.3.18 adds that to the skill.
- **Stop blocks.** Of the 32 blocks, 19 named problems with checks, and in 14 every problem was an assumed value. Most of the rest asked for a record in a session that had none. 0.3.16 reads 4 of those 14 as already stated in the reply, and 0.3.17 reads 13. See [the 0.3.17 notes](UPDATE-2026-11-25-told-assumptions.md).

## Limits

Two or three sessions per case and model show what each model does, not a rate. The judge is a model too, and each grader is a short instruction about one behavior. The sessions ran on 0.3.15, so they show the problems the later versions address, not those versions' effect.
