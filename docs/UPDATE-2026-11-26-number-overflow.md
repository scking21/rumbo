# November 26 Claude adapter 0.3.24: an enormous number in a quote no longer stops the hooks

This builds on [Claude adapter 0.3.23](UPDATE-2026-11-26-hook-speed.md). What the hooks check and say is unchanged.

## Distribution identities

- The Claude adapter is **0.3.24**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

A fuzz run over valid records with awkward quotes found the first crash in the number reader. A scaled number with an exponent past what a Python `Decimal` holds raised `decimal.Overflow` while a quote was read: "$1e999999k", "1e999999 thousand" or "£2.5e999999M".

The reader has raised on "$1e999999k" since at least 0.3.9, but only when it reached that number while looking for a value it had not found earlier in the quote. 0.3.23 reads all of a quote's numbers at once, so from then on every check whose quotes held such a number raised it:

- `check` and `show` crashed with a traceback, so no record lines reached the agent at its prompts.
- The Stop gate fails closed on an error, so every stop of the session got a "gate error" block, up to the block limit.
- `pre-write` ignores its own errors, so it showed nothing before writes.

Nobody writes such a number on purpose, but a pasted log or a typo can.

## What changed

- **No amount.** The reader treats a scaled number it cannot represent as naming no amount, and reads on.
- **Fuzzing.** `rumbo/tests/test_hook_fuzz.py` already gave every command malformed records. It now also gives them records that validate, built from awkward pieces of quotes and replies: exponents, very long digit runs, other scripts' digits, fractions, spelled and scaled amounts, ranges, odd times and dates. Without the fix, 74 of its 200 records fail it: the Stop gate blocks each with a gate error, and `check` and `show` crash on 65 of them.

## Evidence

- `rumbo/tests/test_numeric_boundaries.py` reads the three quotes above as naming no amount, while "$1.5k" still names 1,500. It also checks that `check` and the Stop gate get through a record that holds one of them without an error.
- The new fuzz test runs 200 such records through `validate`, `check`, `show`, the Stop gate and `pre-write`. It found nothing else.
- Neither did longer runs: 2,000 valid records from ten other seeds, and 3,000 malformed records with random hook input, each through the same five commands.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.23 merge on main. There is no data migration.
