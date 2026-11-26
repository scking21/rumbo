# November 26 Claude adapter 0.3.23: the hooks stay fast on records with long replaced quotes

This fixes a slowdown in [Claude adapter 0.3.22](UPDATE-2026-11-26-replaced-words.md). What the hooks check and say is unchanged.

## Distribution identities

- The Claude adapter is **0.3.23**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

0.3.22 names the values that only a replaced item's words give. To find them, it read a check's whole source text again together with each replaced item's quote, for every check with unsourced values. Reading numbers from a quote cost about 25 ms per value for each 12 KB of text.

So a large record slowed every hook that lists problems: `show`, `pre-write`, `check` and the Stop gate. In a synthetic test that 0.3.21 handled in a tenth of a second, they took 42 seconds. Each check in it had 21 values, and some of its replaced items held long quotes. The hooks' timeout is 10 seconds. The eval records are small, so none of the live sessions came near it.

## What changed

- **Only the replaced item's own quote is read**, since each value is read within one text. A quote that names no value of the check's kind (no digit, number word, date word, time word or money word) is skipped.
- **Each text's numbers are read once.** Which numbers a text states does not depend on the number looked for. So the set of numbers a quote states is now worked out once and kept for the hook's run, for at most 256 texts. Before, every value read the quote again. The answers are the same as before.

| Synthetic record | 0.3.21 | 0.3.22 | 0.3.23 |
| --- | --- | --- | --- |
| 40 items, 10 checks of 10 values, long quotes on replaced items | 0.02 s | 4.6 s | 0.05 s |
| 60 items, 30 checks of 20 values, long quotes on replaced items | 0.1 s | 42 s | 0.08 s |
| 60 items, 30 checks of 20 values, long quotes on live items | 8.8 s | over 120 s | 0.05 s |

The last record was already slow on 0.3.21, close to the timeout, because every check read the same long quotes again.

## Evidence

`rumbo/tests/test_replaced_sources.py` builds a record with long quotes on replaced items and checks:

- `open_problem_lines` and `record_problems` finish within 2 seconds;
- `check` and `pre-write` each finish within 5 seconds;
- the number readings stay right with and without the minutes reading, and the kept readings stay bounded.

Run against 0.3.22, the first test takes 10 seconds and fails. The whole suite passes unchanged, including every test of the number reader.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.21 merge on main, since 0.3.22 has the slowdown. There is no data migration.
