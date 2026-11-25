# Eval results across models: Claude adapter 0.3.15 and 0.3.18

Every bundled eval case was run on the Claude adapter 0.3.15 with three models: sonnet and haiku three times each and opus twice. That is 11 cases, 88 sessions and 248 gradings. The hooks in 0.3.15 are those of 0.3.14; 0.3.16 to 0.3.18 change only what the Stop gate reads and when the hooks nudge (see [the 0.3.18 notes](UPDATE-2026-11-25-empty-record.md)). The same 88 sessions were then run on 0.3.18; [the last section](#0318-against-0315) compares the two.

## How the runs were made

- `scripts/claude_multiturn_eval.py` drove each case's turns through `claude -p --resume` with the plugin loaded from a copy of the 0.3.15 tree, so every session ran the same version.
- Cases `09-unit-price-budget`, `10-overnight-window` and `11-rejected-option` are new in `rumbo/evals`. They check a budget given as a price per person, a window that runs past midnight, and a "no" to one option that leaves another undecided.
- Every grading was made, or made again, by a sonnet judge with three votes per grader. Each vote reasons in a few sentences and ends with a `VERDICT:` line, and a grader needs two matching votes. Of the 232 gradings a judge made, 8 had split votes: 6 on haiku's sessions, 2 on opus's, none on sonnet's. The other 16 gradings check files (no record created) and need no judge.
- The tables below come from `python3 scripts/eval_summary.py LABEL=DIR ...` over the runs' directories. The replays of saved Stop blocks come from `python3 scripts/replay_stop_blocks.py [--scripts DIR] [--told] RUN_DIR ...`, which asks a given version's reader whether each reply stated its block's assumed values.
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
- **A year the user never gave.** In `04-deadline-after-event`, every haiku and opus reply put the dates in 2027, the year of the next May 9 after the run date, often saying it was assumed ("Assuming the next May 9 (2027)"). No sonnet reply did. None of these sessions started a record, so the commitments skill, which says not to add a year, was never loaded. A one-turn request gets only the prompt-time nudge to start a record. In 0.3.18 that nudge also asks the agent to keep such dates without a year.
- **A "no" read as a choice.** In `11-rejected-option` the user rules out the hotel ballroom and never picks the community center. Every haiku plan and one of the two opus plans listed the community center as decided. In one haiku session the record itself held the community center as `uncertain`, and the plan still called it decided. The hooks warn before a write only about failing or unsourced checks, not about items that are not decided, and the skill had not said that an item's status decides how it is written. 0.3.18 adds that to the skill.
- **Stop blocks.** Of the 32 blocks, 19 named problems with checks, and in 14 every problem was an assumed value. Most of the rest asked for a record in a session that had none. 0.3.16 reads 4 of those 14 as already stated in the reply, 0.3.17 reads 13 and 0.3.18 all 14; see [the 0.3.17 notes](UPDATE-2026-11-25-told-assumptions.md). Of the 5 blocks with a conflict, one came from a record that was out of date with the reply, and in 3 of the other 4 the reply had stated everything: 0.3.18 reads those 3 as stated.

## 0.3.18 against 0.3.15

The same cases, models and run counts were run again on 0.3.18, from a copy of the tree at that release, and graded by the same sonnet judge. A 5-hour usage limit cut two batches short: `--rerun DIR` ran the cut-off sessions again in place, and `--regrade DIR --errors-only` gave the verdicts the judge had missed. All 88 sessions completed and every grading has a verdict.

| Model | Gradings passed | Stop blocks | Empty records | Case 04 replies with a year | Sessions naming a record id | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| sonnet | 93 → 93 of 93 | 7 → 3 | 0 → 0 | 0 → 0 of 3 | 0 → 0 | $8.51 → $8.74 |
| haiku | 83 → 88 of 93 | 11 → 23 | 3 → 1 | 3 → 1 of 3 | 0 → 2 | $0.62 → $0.54 |
| opus | 54 → 61 of 62 | 14 → 5 | 1 → 0 | 2 → 0 of 2 | 0 → 0 | $13.14 → $12.89 |

The graders that changed, on haiku and opus (sonnet passed every grading on both versions):

| Case | Grader | haiku | opus |
| --- | --- | --- | --- |
| `02-launch-full` | ads first, newsletter second | 3/3 → 3/3 | 1/2 → 2/2 |
| | budget total | 2/3 → 2/3 | 1/2 → 1/2 |
| | dates to hit | 3/3 → 3/3 | 1/2 → 2/2 |
| | flyers do not fit | 2/3 → 3/3 | 1/2 → 2/2 |
| | insurance is a condition | 2/3 → 3/3 | 1/2 → 2/2 |
| `04-deadline-after-event` | no invented year | 0/3 → 2/3 | 0/2 → 2/2 |
| `05-draft-is-not-a-decision` | draft and idea stay open | 2/3 → 3/3 | 2/2 → 2/2 |
| `11-rejected-option` | a "no" is not a choice | 0/3 → 0/3 | 1/2 → 2/2 |

What the comparison shows:

- **Records that hold the decisions.** Empty records fell from 4 to 1, and the launch case, where the empty records had cost 7 gradings, now fails one grading on each of haiku and opus. The empty record left is haiku's in `11-rejected-option`. It was started at the session's last stop, right after the no-record block; the empty-record nudge never fires on a stop right after a block, and no turn followed.
- **Years.** Haiku and opus replies to `04-deadline-after-event` that named a year fell from 5 of 5 to 1 of 5, with the no-record nudge's new line.
- **Fewer blocks on sonnet and opus,** 7 to 3 and 14 to 5. Two of sonnet's three flagged a quote that began just after the negation in "No, don't use the hotel ballroom". Both agents then quoted the whole sentence, as the block asks; that is the provenance check working. The other blocks are an assumed value or a conflict that the reply did not state, and none is read as stated on replay.
- **More blocks on haiku,** 11 to 23, while its gradings rose from 83 to 88. Haiku kept fuller records, and the gate checked what they held. Of its 23 blocks:
  - 12 asked for a record in a session that had none (10 before);
  - 5 named check problems, 3 were short repeats, and 2 flagged an objective quote that was not the user's words;
  - 1 was the new empty-record nudge.
  
  Several blocked replies kept an open conflict in view at a later turn without its full values. Examples: "**Still open:** the 9:45 schedule conflict, the 30- and 10-minute assumptions", and "The 9:45 start still ends at 12:35". The gate read only a conflict's full values as stating it.
- **A "no" read as a choice** still fails on haiku. Two of its three sessions kept no decisions in a record. In the third, the record held the community center as `uncertain`, and the plan still called it decided, despite the new skill line.
- **Record ids.** Two haiku replies named record ids to the user ("**Catering (C2):** …" and "C1 and C2 are open, and his terms are recorded as I8"). No session did on 0.3.15.

## Limits

Two or three sessions per case and model show what each model does, not a rate. The judge is a model too, and each grader is a short instruction about one behavior. The 0.3.18 runs show that version's effect on these cases, not on other work.
