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

Pending: two `08-dropped-option` sessions on this version, counted for replies that name a year.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.14 merge on main. There is no data migration.
