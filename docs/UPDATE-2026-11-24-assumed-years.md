# November 24 Claude adapter 0.3.15: no assumed years in what the agent writes

This builds on [Claude adapter 0.3.14](UPDATE-2026-11-24-dropped-checks.md). It changes the commitments skill's wording and one refusal message; what the hooks check is unchanged.

## Distribution identities

- The Claude adapter is **0.3.15**.
- The Python engine/package **0.3.5**, the OpenAI portable and Codex local adapters **0.3.7** and the Sites candidate **0.1.3** are unchanged. As with 0.3.11 to 0.3.14, the Codex local package bundles `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## What changed

- **Years.** The skill said "never add a year the user did not say" for the record's dates, but gave "a year" as its first example of a value you may assume and flag. In the saved live sessions the user never gave a year. The replies still named one ("I took 'March 12' to mean Friday, March 12, 2027, the next one after today") in every `01-workshop-full` and `02-launch-full` session and in 5 of 6 `08-dropped-option` sessions. That case's `no-invented-year` grader fails any year the user did not give. The example is now "a start time", and the rule covers what the agent writes as well as the record: "March 12", not "March 12, 2027". When the dates cross a year boundary, the agent still needs the user's years, and the `before` check's "in the same year" failure still says to ask.
- **Dropping a check.** When a decision named in `dropped_by` names a value, the refusal now says "change I3's quote to just their words that drop it" instead of "quote just their words that drop it". In one of two sessions on 0.3.14 where the user's decision named the workshop's date, the agent added a second item with the shorter quote instead of correcting the first. Both items were then in force.
- **`check`'s exit code.** The skill said `check` exits 1 when a check fails; it also does when a value is unsourced, as the SPEC says.

## Evidence

Two `08-dropped-option` sessions on this version (sonnet, run one at a time with `scripts/claude_multiturn_eval.py --grade`) are compared with the six earlier sessions of that case, counting any year from 2026 to 2029 in the replies and in `plan.md`:

| | 0.3.13 and 0.3.14 | 0.3.15 |
| --- | --- | --- |
| Sessions whose replies and `plan.md` name a year the user did not give | 5 of 6 | 0 of 2 |
| All 4 graders passed | 2 of 6 | 2 of 2 |
| Check retired with `dropped_by` | 3 of 3 on 0.3.14 | 2 of 2 |
| Stop blocks | 1, on 0.3.13 | 0 |

Two sessions are a small sample: this shows the new wording is followed, not a measured rate. Neither session hit the `dropped_by` refusal, since the user's decision named no value, so the new refusal wording was not exercised live; `test_a_decision_that_names_a_value_may_update_the_check` covers it.

Every other bundled case also passed all its graders, once each: `03-agenda-overrun`, `04-deadline-after-event` (including `no-invented-year`), `05-draft-is-not-a-decision`, and the two cases where no record should be started, `06-neg-python-question` and `07-neg-weekday`, which started none. None hit a Stop block; together they cost $0.52. The two 15-turn cases passed all 6 graders on 0.3.14, whose hooks are the same; see [its notes](UPDATE-2026-11-24-dropped-checks.md).

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.14 merge on main. There is no data migration.
