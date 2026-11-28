# November 28 Claude adapter 0.3.30: the adapter tested branch by branch

This is the last of three passes over the Claude adapter, each going down a level: its parts in [0.3.28](UPDATE-2026-11-28-parts.md), their sub-parts in [0.3.29](UPDATE-2026-11-28-sub-parts.md), and here single functions and branches, by mutation testing. A mutant is `record.py` with one small change: a comparison, a constant, an `and` or `or`, a `not`, `True` or `False`, or a `continue` or `break`. A mutant that every test still passes marks a branch whose behaviour no test pins.

## Distribution identities

- The Claude adapter is **0.3.30**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## How the mutants were run

- Every line inside a function body that a test reaches gave mutants: 2,056 in 127 functions. Up to 12 were drawn from each function, 918 in all, so that small functions count as much as large ones.
- Each of the 458 tests ran alone under coverage, with its name as the coverage context, also in the `record.py` processes it starts. That gave, for each line, the tests that reach it. A mutant ran only those tests, fastest first, and stopped at the first failure.
- The first run lost every in-process test from that map: coverage names their contexts `loading|<test>`. Survivors that a hand run killed showed it, and the counted run used the corrected map.

## What the mutants found

On 0.3.29's own tests, 719 mutants failed a test, 8 ran past their time limit and 191 survived: 79.2% were caught. Each survivor was read. They fell into three groups:

| Group | Examples | What was done |
| --- | --- | --- |
| A bug | Count nouns: a plural met its singular only by a single guess, so `no cookies` never met `$2 per cookie` | Fixed (below) |
| An untested branch | A fraction at index 0 of a quote; a file exactly at the hook's size limit; clock values 1 and 12; a range's 12 and 1; eight against nine outcomes or undecided items; a 120-character retraction; JSON nested exactly 64 deep; a total exactly at the cap; a check, item or reference after one that is skipped or refused, where `break` for `continue` stopped the walk | 50 tests in `rumbo/tests/test_branches.py` |
| No input tells it apart | A wider look-back window; a read chunk of 1,025 bytes; JSON indentation; a cache size; values validation rejects before a reader sees them; a guard in front of the regex that decides; `(start + 12) % 24` against `(start - 12) % 24`; a loop guard in the gate's error path that its caller already took | Left as they are |

With the new tests, 81 of the 189 survivors that still apply fail a test. The other 2 were in the rewritten count-noun code. That makes 808 of 916 applicable mutants caught, 88.2%. The 108 left are of the third kind, or sit at the edge of a window that no realistic input reaches, such as a number 41 instead of 40 characters before its unit.

## What changed

- **A count noun meets its price per unit in either number.** A zero quantity is sourced by `no seats` only when the user gave a price per seat. The noun and the unit were compared after cutting each to one guessed singular, which got many plurals wrong: `cookies` became `cooky`, `classes` `classe`, `boxes` `boxe`, `pies` `py` and `buses` `buse`. So `Cookies are $2 per cookie. No cookies sold.` called the zero count of cookies the agent's own assumption. Each word now gives every singular it can have: the word itself, and without its `s`, without its `es`, and with `ies` as `y`. `people` stays `person`. Two words match when one of these is the same. A plural of another unit still does not match: `$2 per seat. No tables sold.` leaves the zero count unsourced.

## Evidence

- `rumbo/tests/test_branches.py` holds 50 tests. On 0.3.29 one fails, the count-noun test, for the 5 plurals it names. The other 49 pin behaviour that was already right but untested.
- Across the 207 saved records (1,053 checks, 142 distinct quotes), no validation, unsourced value, check result or problem line changes. The replay of the saved Stop blocks (80 blocks in 57 runs) is identical.
- Both suites pass, with their output saved.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.29 merge on main. There is no data migration.
