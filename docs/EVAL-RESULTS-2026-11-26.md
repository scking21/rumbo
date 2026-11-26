# Eval results across models: Claude adapter 0.3.21 against 0.3.18

Every bundled eval case from `01` to `11` ran on the Claude adapter 0.3.21 with sonnet, haiku and opus. The runs were graded by the same sonnet judge as [the 0.3.18 runs](EVAL-RESULTS-2026-11-25.md#0318-against-0315), and are compared with them here. Between the two versions:

- 0.3.19 reads a conflict already told in a later status line ([notes](UPDATE-2026-11-25-told-conflicts.md)).
- 0.3.20 lists undecided items before a write ([notes](UPDATE-2026-11-25-not-decided.md)).
- 0.3.21 holds a write once so the agent reads those lines first ([notes](UPDATE-2026-11-26-write-hold.md)).

## How the runs were made

- `scripts/claude_multiturn_eval.py` drove each case's turns through `claude -p --resume`, with the plugin loaded from a copy of the tree, as for 0.3.18.
- There were 88 sessions, as on 0.3.18, with more runs where the write hold acts:
  - Sonnet ran every case twice, and `01-workshop-full` four times.
  - Haiku ran every case three times, `01-workshop-full`, `02-launch-full` and `11-rejected-option` five times, and `08-dropped-option` six times.
  - Opus ran every case twice.
  - On 0.3.18, sonnet and haiku had three runs of every case and opus two.
- The cases where the pre-write hook has lines to show (01, 02, 08 and 11) ran first on the first version of the 0.3.21 change. That version keyed an undecided item's line by its text and held no write after a no-record block. The later runs used a copy identical to the release, except for one haiku and one sonnet batch that keyed lines as the release does but did not yet hold a write after a no-record block.
- 5-hour usage limits cut sessions in four batches. `--rerun DIR` ran them again from the start with the batch's own copy, and `--regrade DIR --errors-only` gave the verdicts the judge had missed. All 88 sessions completed, and every grading has a verdict.
- The tables come from `python3 scripts/eval_summary.py LABEL=DIR ...`, and the held writes from `python3 scripts/hold_outcomes.py RUN_DIR ...`. Cost is that of one session of every case, from each case's average, since the two versions ran different numbers of each case.

## Results

| Model | Sessions | Gradings passed | Stop blocks | Held writes | Cost of one session of each case | Sessions naming a record id |
| --- | --- | --- | --- | --- | --- | --- |
| sonnet | 33 → 24 | 93 of 93 → 73 of 74 | 3 → 1 | 15 | $2.91 → $3.18 | 0 → 0 |
| haiku | 33 → 42 | 88 of 93 → 125 of 133 | 23 → 36 | 17 | $0.18 → $0.26 | 2 → 0 |
| opus | 22 → 22 | 61 of 62 → 62 of 62 | 5 → 5 | 12 | $6.44 → $7.53 | 0 → 0 |

In the two cases where no record should be started (`06-neg-python-question` and `07-neg-weekday`), no model started one on either version. One haiku record stayed empty on each version.

The graders that changed:

| Case | Grader | sonnet | haiku | opus |
| --- | --- | --- | --- | --- |
| `01-workshop-full` | accessibility note | 3/3 → 4/4 | 3/3 → 4/5 | 2/2 → 2/2 |
| `02-launch-full` | budget total | 3/3 → 2/2 | 2/3 → 3/5 | 1/2 → 2/2 |
| | flyers do not fit | 3/3 → 2/2 | 3/3 → 4/5 | 2/2 → 2/2 |
| | insurance is a condition | 3/3 → 2/2 | 3/3 → 4/5 | 2/2 → 2/2 |
| `04-deadline-after-event` | no invented year | 3/3 → 2/2 | 2/3 → 1/3 | 2/2 → 2/2 |
| `08-dropped-option` | dropped conflict not open | 3/3 → 2/2 | 3/3 → 5/6 | 2/2 → 2/2 |
| | dropped conflict not repeated | 3/3 → 1/2 | 3/3 → 6/6 | 2/2 → 2/2 |
| `11-rejected-option` | a "no" is not a choice | 3/3 → 2/2 | 0/3 → 5/5 | 2/2 → 2/2 |

Every other grader passed in every session on both versions.

## What the comparison shows

- **A "no" is no longer read as a choice.** In `11-rejected-option` every haiku plan on 0.3.15, 0.3.18 and 0.3.20 listed the community center as decided, though the user had only ruled out the ballroom. On 0.3.21 each haiku session wrote its plan before it had a record, as before. That write was held, and each session started a record and wrote the venue as a proposal to confirm: 5 of 5.
- **What agents did with a hold.** Haiku changed the file after 16 of its 17 held writes. Sonnet and opus changed it after 12 of 27. When they did not, they said their draft already handled the lines and wrote it again unchanged. Their changes were mostly labels such as "(draft)" or "a proposal to confirm"; once, opus added a schedule conflict to its plan.
- **Cost.** One session of every case cost 9% more on sonnet, 17% more on opus and 45% more on haiku, a few cents. A held write is written again in full, and haiku sessions kept fuller records and did more work with them. The text 0.3.19 and 0.3.20 add to the context counts too.
- **Haiku's other misses** are 8 of its 123 gradings outside `11-rejected-option`, against 2 of 87 on 0.3.18:
  - four in `02-launch-full`: the committed total twice, the flyers and the insurance condition;
  - an accessibility note in `01-workshop-full`;
  - a dropped deadline left open in `08-dropped-option`;
  - a year in two `04-deadline-after-event` replies. Both asked which year was meant, naming "May 9, 2027" and "May 2026" as the choices, and the grader counts any date with a year.

  In the sessions with a hold, each miss was already in the version of the plan the hold stopped. The others had no hold. Haiku's launch gradings varied before too (2 of 3 on 0.3.15 for three of these graders).
- **Sonnet's one miss:** in `08-dropped-option`, a reply restated that the dropped deadline fell after the workshop, in a session with no hold or block.
- **Stop blocks.** Only five cases had blocks on either version: 01, 02, 05, 08 and 11. Haiku's rate there was about the same: 1.5 per session, against 1.5 on 0.3.18. By case it fell in 01 and 11 and rose in 02 and 08. Sonnet had 1 block where it had 3, and opus 5 where it had 5.
- **Record ids.** No reply named a record id. On 0.3.18, two haiku replies had, each right after a full Stop block.

## A coding task that looks like planning

`12-neg-code-with-times` is new. It asks for a small Python module and its tests in two turns that mention 9:30 and a Friday deadline. The plugin counts both prompts as planning, though the work needs no decision record. It ran on 0.3.18 and on 0.3.21, from the same copies as above, with three haiku sessions and two each of sonnet and opus per version.

| Version | Gradings passed | Stop blocks | Held writes | Records started | Cost per session: sonnet, haiku, opus |
| --- | --- | --- | --- | --- | --- |
| 0.3.18 | 21 of 21 | 7 | 0 | 0 | $0.11, $0.007, $0.24 |
| 0.3.21 | 21 of 21 | 0 | 7 | 0 | $0.12, $0.009, $0.28 |

- On 0.3.18, every session's second turn ended in the Stop gate's no-record block, and the agent then told the user why the work needed no record.
- On 0.3.21, the test file's first write was held instead. Every agent wrote it again unchanged and started no record. Haiku and sonnet told the user ("The first write was held by a hook asking for a decision record. I wrote the file again without one ..."), and opus did not mention it.
- So the session's one no-record enforcement moved from the stop to the write, at a few cents' cost, and the graded work was the same.

## Limits

Two to six sessions per case and model show what each model does on these cases, not a rate. The judge is a model too, and each grader is a short instruction about one behavior. Different batches ran on three versions of the 0.3.21 change, as described above; the differences affect when a write is held, not what the hooks check.
