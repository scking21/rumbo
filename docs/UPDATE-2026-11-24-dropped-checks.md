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
- A decision that has itself been replaced no longer drops anything, so when the user brings the option back the record is invalid until the agent names the decision now in force or removes `dropped_by`.
- A decision whose words give a value of the check's kind that the check does not have is an update, not a drop ("Dr. Okafor's slides are now due March 5" gives a new date), and the refusal tells the agent to write a newer check with it that lists the old one in `replaces`. The values read are dates for `before`, clock times and durations for `fits_window`, and money amounts or "free" for `within_budget`; a value the check already has, such as the workshop's own date, does not count.
- At least one of the check's values must come only from the quotes of the items the decision replaced. A check whose values all still come from items in force is about the current plan, so it cannot be dropped by a decision that happens to replace one of its items.

The commitments skill says to replace a check with the same kind of check for what the user chose, and to use `dropped_by` only when that choice leaves nothing of that kind to check.

## Evidence

The live session's own record validates with `C8.dropped_by: "I16"`, and `check` then prints C8 as `DROPPED` and exits 0 instead of reporting April 1 as unsourced. `rumbo/tests/test_check_dropped.py` covers each refusal and the hooks, and the crash fuzz test now writes random `dropped_by` values. A separate fuzz of 3,000 otherwise-valid records with random decision wording found no crash; validation took at most 8 ms, also on 20,000-character adversarial quotes.

`rumbo/evals/08-dropped-option` is a new four-turn case: a workshop on March 12, Dr. Okafor's slides due for approval on March 20, then the user goes with the maker-space team and asks for the final plan. One sonnet session on each version, run with `scripts/claude_multiturn_eval.py --grade` (haiku judge, majority of three):

| | 0.3.13 | 0.3.14 |
| --- | --- | --- |
| The agent flagged the March 20 conflict when it came up | PASS | PASS |
| The plan does not list the dropped conflict as open | PASS | PASS |
| The plan treats the speaker as settled | PASS | PASS |
| Replies after the choice do not explain the dropped conflict again | FAIL | PASS |
| Stop blocks | 0 | 0 |
| Cost | $0.38 | $0.19 |

On 0.3.13 the agent kept the failing check and restated the conflict after the choice ("The earlier date conflict is moot, but I'll state it for the record") and again in the final summary; a reply that states a conflict passes the Stop gate, so it never blocked. On 0.3.14 the agent recorded the decision as an item that replaced Dr. Okafor's terms and set `dropped_by` on the check without being asked: `check` printed `C1: DROPPED before slide approval deadline vs. workshop date by I2`, and its replies said only that the deadline no longer applied. This is one session per version; it shows the field is used as intended, not a measured rate.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

The adapter suite also runs from the repository root now (`python3 -m unittest discover -s rumbo/tests`); `test_record.py` used to start `scripts/record.py` by a relative path and failed 206 subtests there. To roll back, return to the 0.3.13 merge on main. A record that uses `dropped_by` then reads the dropped check as live again; there is no other data migration.
