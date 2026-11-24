# November 24 Claude adapter 0.3.14: a user's decision can drop a check

This builds on [Claude adapter 0.3.13](UPDATE-2026-11-24-quote-speed.md). It adds one optional field to the decision record's checks; a record without it reads exactly as before.

## Distribution identities

- The Claude adapter is **0.3.14**.
- The Python engine/package **0.3.5**, the OpenAI portable and Codex local adapters **0.3.7** and the Sites candidate **0.1.3** are unchanged. As with 0.3.11 to 0.3.13, the Codex local package bundles `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

Since 0.3.12 a newer check can replace an obsolete one of the same kind, as when the budget with Dr. Okafor gives way to the budget with the maker-space team. A decision that drops an option can leave nothing of that kind to check. In a 0.3.12 live session (`01-workshop-full`, sonnet) the user said "I think we should go with just the maker-space team for this workshop." The agent recorded that decision as an item replacing Dr. Okafor's terms, and replaced each budget check with one for the maker-space team. Its check that the March 12 workshop came before Dr. Okafor's April 1 payment deadline had no successor: with the maker-space team there is no payment deadline. Its April 1 now came only from a replaced item, so `check` reported `second month-day 04-01 not in the user's quoted words`. The prompt hook then listed it as an `ASSUMPTION`, telling the agent to ask the user about April 1 or call it its own assumption, and the Stop gate treats such a value as an open problem until a reply states it. Deleting the check is reported too, so nothing could retire it. That session reached its usage limit at this turn, so what the agent would have done next was not observed.

## What changed

A check may name the user's decision in `dropped_by`. A dropped check stays in the record as history: `check` prints `C8: DROPPED before workshop date before Dr. Okafor's payment deadline by I16` and leaves it out of the exit code, and `show`, `pre-write` and the Stop gate no longer report it. Removing it from the record is reported like removing a replaced check.

The field is refused (`RECORD_BAD_REF`) whenever it could hide a problem still in force:

- The decision must be an item, a `commitment` or `rejected`, whose own `replaces` lists one of the check's `refs`. Flipping the check's own item to `rejected` is not enough: the user's decision is recorded as its own item with their words.
- A decision that has itself been replaced no longer drops anything, so when the user brings the option back the record is invalid until the agent names the decision now in force or removes `dropped_by`. A rejection that drops a check is treated like an approval at the Stop gate. Its words must have been recorded for that status, so an approval from an earlier session cannot be rewritten as a rejection to drop a check. If the user takes it back in a later session, the gate reports it as `EARLIER_APPROVAL` until the record replaces it.
- A decision whose words name a value of the check's kind may be an update, not a drop ("Dr. Okafor's slides are now due March 5"). The refusal tells the agent to write a newer check with the new value that lists the old one in `replaces`, or, if the user only dropped the option, to quote just their words that drop it. A value is a digit or a number word ("one" and the word "may" alone do not count), or by kind a month or weekday name (`before`), an hour, minute, quarter, half, noon, midnight or o'clock (`fits_window`), or a currency sign, "free" or a money word (`within_budget`). Any value counts, including one the check already has, such as the workshop's own date. Telling the two apart would mean reading every form the source check reads, and review found that a narrower reader missed several.
- At least one of the check's values must come only from the quotes of the items the decision replaced. A check whose values all still come from items in force is about the current plan, so it cannot be dropped by a decision that happens to replace one of its items.

The commitments skill says to replace a check with the same kind of check for what the user chose, and to use `dropped_by` only when that choice leaves nothing of that kind to check.

## Evidence

The live session's own record validates with `C8.dropped_by: "I16"`, and `check` then prints C8 as `DROPPED` instead of reporting April 1 as unsourced. It still fails on that session's real conflict, sessions that end at 12:35, after the 12:30 close. `rumbo/tests/test_check_dropped.py` covers each refusal and the hooks, and the crash fuzz test now writes random `dropped_by` values. A separate fuzz of 3,000 otherwise-valid records with random decision wording found no crash; validation took at most 8 ms, and at most 0.1 s on 24,000-character adversarial quotes. Review of this change found that the first version, which compared a decision's values with the check's own, could drop a check whose deadline had moved to another year ("March 20, 2027" against 2026-03-20) or was given as `03-25`, "3/25/2027" or the end of "March 20–25". It could also read "two hundred fifty dollars" as fifty and miss "three-quarter hour". The rule above replaces that comparison.

`rumbo/evals/08-dropped-option` is a new four-turn case: a workshop on March 12, Dr. Okafor's slides due for approval on March 20, then the user goes with the maker-space team and asks for the final plan. Three sonnet sessions on each version, run one at a time with `scripts/claude_multiturn_eval.py --grade` (haiku judge, majority of three), before the review fix above, which does not change this case:

| | 0.3.13 | 0.3.14 |
| --- | --- | --- |
| The agent flagged the March 20 conflict when it came up | 3 of 3 | 3 of 3 |
| The plan does not list the dropped conflict as open | 3 of 3 | 3 of 3 |
| The plan treats the speaker as settled | 3 of 3 | 3 of 3 |
| Replies after the choice do not explain the dropped conflict again | 0 of 3 | 2 of 3 |
| The check was retired with `dropped_by` | (no such field) | 3 of 3 |
| Replies after the choice that explain the record to the user | 1, 3 and 6 | 0, 0 and 0 |
| Stop blocks | 1 | 0 |
| Mean cost | $0.29 | $0.20 |

On 0.3.13 every agent kept the failing check, since nothing could retire it, and restated the conflict after the choice to get its replies past the Stop gate ("The earlier date conflict is moot, but I'll state it for the record"). Two explained the record itself to the user: "I couldn't clear the flag in my records, because the tool only lets me replace a check with another of the same type", and, after the one block, "The record marks it as unsourced only because I marked Dr. Okafor's item as dropped, so that item no longer counts as a source. It is not my assumption." On 0.3.14 every agent recorded the decision as an item that replaced Dr. Okafor's terms and set `dropped_by` without being asked (`check` printed `C1: DROPPED before slide approval deadline vs. workshop date by I2`), and its replies said only that the deadline no longer applied. The 0.3.14 failure said it once in passing: "The earlier worry about it falling after March 12 is moot." Three sessions per version are a small sample.

These ran before the review fixes. Four later sessions on the final rule, with the plugin as merged:

- **The decision names a value.** Two sessions of a variant of `08-dropped-option` in which the user's decision names the workshop's date: "I think we should go with just the maker-space team for the March 12 workshop." This checks that the refusal is something an agent can act on. In both, the agent first quoted the whole sentence and was refused with `I2's words name a value ("March 12 workshop") ...`. It then quoted just "go with just the maker-space team", and the check was dropped. Neither session hit a Stop block. One kept the whole sentence as a second item, and the strict grader failed one for a passing mention ("His March 20 deadline fell after the workshop, but it no longer applies").
- **A complete 15-turn `01-workshop-full` session.** This is the scenario of the 0.3.12 gap above. It passed all 6 graders, cost $0.81 and named no record ids to the user. When the user went with the maker-space team, the agent dropped two checks about Dr. Okafor with that decision: his April 1 payment deadline and the schedule with his 60-minute session. It replaced the budget check with Dr. Okafor by the one with the maker-space team. The only checks still failing at the end were the two real conflicts, sessions that end at 12:35 after the 12:30 close and the printer's March 20 deadline after the March 12 workshop. Its one Stop block was for a quote of Dr. Okafor's reply that did not match the user's words; the agent quoted them exactly and the gate did not block again.
- **A complete 15-turn `02-launch-full` session**, which has no option to drop, passed all 6 graders with no Stop block, cost $0.86 and named no record ids. Its budget checks replaced one another as the plan changed, and the only check failing at the end was the real conflict: 100 flyers at about $1 each bring the total to $1,230, over the $1,200 budget.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

The adapter suite also runs from the repository root now (`python3 -m unittest discover -s rumbo/tests`); `test_record.py` used to start `scripts/record.py` by a relative path and failed 206 subtests there. To roll back, return to the 0.3.13 merge on main. A record that uses `dropped_by` then reads the dropped check as live again; there is no other data migration.
