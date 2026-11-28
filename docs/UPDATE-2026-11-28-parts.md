# November 28 Claude adapter 0.3.28: the adapter tested part by part

This is the first of three passes over the Claude adapter, each going down a level: its parts, then their sub-parts, then single functions and branches. Each part was tested against its documented contract and against the data saved from the eval runs since November 24. It builds on [Claude adapter 0.3.27](UPDATE-2026-11-28-outcome-handoff.md). What the hooks check and say is unchanged.

## Distribution identities

- The Claude adapter is **0.3.28**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The parts and what testing them found

| Part | How it was tested | Found |
| --- | --- | --- |
| Record loading and validation | Each rule of the record format, probed one at a time | Consistent with the SPEC |
| Check arithmetic | 14,710 random valid checks against a separate implementation with exact fractions and calendar dates | No difference |
| Source readers | Timing on long quotes | Money reading slowed `check` 2.3 times (fixed) |
| Quote provenance | Every quote in the 207 saved sessions against its transcript | 2 of 2,074 not found, both reworded by the agent ("lodge quote" for "lodging quote") |
| Reply reader | The saved Stop-block replay | Unchanged since 0.3.26 |
| Hook commands | `stop-gate`, `show` and `pre-write` on every saved session's final record and transcript | 621 runs, none over a second, no errors |
| Outcomes and handoff | The SKILL's rules for the ledger, against the code and its tests | Consistent |
| CLI, wrappers and tests | The wrapper scripts, and a coverage run of the suite | An intermittent test timeout (fixed), and a stale wrapper comment (fixed) |

Line and branch coverage of `record.py` by its own tests is 94%.

## What changed

- **Money reads quickly again.** 0.3.26 ran up to three more regexes on every number: a currency-code search, a month check and an am/pm check. On a 1.2 MB quote of 600,000 numbers, `check` took 6.3 s, against 2.8 s on 0.3.25, and the hooks' timeout is 10 s. Each check now first looks at the character next to the number. A month, a currency code or "am" or "pm" needs a letter there, so numbers without one skip the regexes. The decimal-word check ("one point five") compiles its regex once instead of looking it up for each number. The same quote now reads as money in 3.3 s and as plain numbers in 2.5 s, faster than 0.3.25's 2.75 s. Every reading is the same as before: across the 2,074 quotes in the saved records, no number or money reading changes, nor any of the 510 live checks. The letter checks skip the same spaces the regexes do, any but a line break, so a no-break space between a number and its month, currency word or am/pm reads as before. The first push skipped only spaces and tabs, so `Due 20 May` (with a no-break space) sourced $20 and `June 25 euros` lost its 25 (Codex review). On 1.27 million random texts of numbers, months, currency words, am/pm and every kind of space, money and plain readings now match 0.3.27's exactly; the first push differed on 4.5% of them.
- **A test no longer depends on the runner's stdin.** `show` reads hook JSON from stdin. One outcome test ran it with no input, so it inherited whatever stdin the test runner had, and when that was an open pipe it waited out its 10-second timeout. It is the only test that ran a stdin-reading command without input, and it timed out in a coverage run, so it is the likeliest source of the intermittent error the 0.3.27 PR reported. The test now gives `show` an empty stdin. Agents are not affected: the Bash tool's stdin is `/dev/null`, and `show` returns in a tenth of a second there.
- **The pre-write wrapper's comment** said the hook "never blocks". Since 0.3.21 it holds a write once, and the comment now says so.

## Evidence

- `rumbo/tests/test_money_reading.py` checks that reading money costs less than 1.8 times reading plain numbers on the same text. On 0.3.27 the ratio is 2.0 and the test fails; it is 1.4 now.
- The same file checks that every space but a line break reads as an ordinary space next to a month, a currency word or am/pm. The first push fails it for 11 of the 12 spaces tried.
- Both suites pass, with their output saved; across the saved records and the replay, every count is unchanged.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.27 merge on main. There is no data migration.
