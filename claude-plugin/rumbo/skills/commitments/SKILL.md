---
name: commitments
description: Keeps a record of what the user has actually decided, drafted, or is still exploring, and checks times, dates and budgets; use it in multi-step work where decisions accumulate.
---

# Commitments

Maintain a decision record so later steps do not treat a draft as a decision, or
miss a scheduling conflict. The record is a memory aid, nothing more.

## Inputs and outputs

- Record file: `.rumbo/record.json` in the user's project.
- All subcommands: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/record.py" <sub> --record "<record path>"`.
- `init --objective TEXT --quote - <<'QUOTE'` — create the record with the goal and the user's own words, then a line with the user's exact words, then a line `QUOTE`; refuses to overwrite. Always pass the user's words through `--quote -` with a quoted heredoc (`<<'QUOTE'`); inside double quotes the shell rewrites `$` amounts and backticks.
- `validate` — print `RECORD_OK`, or one fault line per problem.
- `check` — validate, then print `PASS`/`FAIL` per check; exit 1 if any check fails.
- `show [--max-chars N]` — compact summary; silent when no record exists.
- `stop-gate` — read the Stop hook input on stdin; block up to three times per session while checks or provenance remain unresolved; an unchanged repeat asks only for a one-line status.
- Exit codes: 0 clean, 1 content problem, 2 tool or I/O problem.

## When to start

Run `init` the first time the user sets a multi-step goal, passing the user's
own words verbatim through `--quote -` with a quoted heredoc (`<<'QUOTE'`),
since inside double quotes the shell rewrites `$` amounts and backticks. The objective is what the user is trying to
achieve. Constraints, cautions and limits go in items, never in the objective.
If a hook line says "no decision record yet", decide whether this is multi-step
work with decisions; if it is, run init with the user's own words; if not,
ignore it.

## When to update

Update only when a message adds, narrows, replaces, defers or rejects something
that affects later work. Do not atomize every sentence into an item.

## Status rules

| What the user said | Status |
| --- | --- |
| "please draft X", "sketch X" | `draft` — work to produce, not a decision |
| "I like X" | `preference` |
| "let's try X", "compare these" | `authorized` — for that experiment only, not adoption |
| Clear assent to a concrete proposal | `commitment` — within its stated scope |
| "I think we should go with X", "let's go with X", "we'll take it" | `commitment` — the user chose it; hedging words do not reopen it |
| "not yet", "wait on X" | `deferred` |
| An explicit no | `rejected` |
| Anything ambiguous | `uncertain` |

Record the scope words literally. "for this workshop" means `scope: this
workshop only` — do not widen it or treat other questions as closed.

A status becomes `commitment` only when the item's `quote` is the user adopting
it; confirming one piece (for example a start time) does not make the rest of a
draft decided. Once the user has chosen, do not list the choice as still open or
ask them to decide it again.

## Sourced values

A check's values must come from the user's quoted words. If you must assume a value (a year, a shortened break), leave it visible (`check` shows it as UNSOURCED) and tell the user plainly that it is your assumption. Never change a value to make a check pass.

List the supporting item ids in each check's `refs`. Only those items' quotes
and the objective quote source the check; `done`, `rejected`, and replaced items
cannot source it. Missing or null `refs` falls back to all active items for legacy
records, while `refs: []` means only the objective. Include every supporting item
explicitly so unrelated numbers cannot accidentally make an assumption look sourced.

Add items and checks by editing the JSON directly, then run `validate`:

```json
{"id": "I3", "text": "Maker-space team only", "quote": "I think we should go with just the maker-space team for this workshop.",
 "ref": "E12", "status": "commitment", "scope": "this workshop only", "replaces": []}
{"id": "C1", "kind": "fits_window", "label": "session schedule", "start": "09:45", "segments_min": [75, 20, 75], "end": "12:30", "refs": ["I1"]}
```

Every item carries the user's verbatim words in `quote`. A newer item that
supersedes an older one lists the older id in `replaces`; never delete history.

## Times, dates and money

Whenever the record holds a schedule, a deadline relative to an event, or a
budget cap, add a check:

- `fits_window` — `start`, `end` as `HH:MM`, `segments_min` as a list of minutes.
- `before` — `first`, `second` as either both `MM-DD` or both `YYYY-MM-DD`.
- `within_budget` — `amounts`, `total_cap`, optional `item_cap`.

Run `check` before delivering any plan, schedule or summary. A FAIL line is a
conflict: resolve it, or state it plainly to the user.

A value is sourced however the user wrote it: "March 20th", "20 March" or "3/20"
for `03-20`; "9am" or "noon" for `09:00` or `12:00`; "2-hour" for 120 minutes;
"$1.5k" for 1500. A bare "at 9" does not say morning or evening: ask.

Write dates as MM-DD unless the user stated the year; never add a year the user
did not say; if the dates cross a year boundary, you need the user's years.

## Tell the user

When an item becomes a commitment or is replaced, say it in one line:
"Treating as decided: ...". If the user corrects an item, fix the record
immediately; the user's correction always wins over the record.

## Stopping

The Stop hook blocks, up to three times per session, while a check fails, a value
is unsourced, a quote is not found in the user's messages, the harness transcript
is missing or unreadable, a failing check was deleted, or the record is unreadable.
An unavailable transcript is unverified provenance, not a clean result; disclose
it if a readable harness transcript cannot be supplied. Never invent transcript
evidence. An `EARLIER_APPROVAL` line means the user approved something in an earlier
session and has said something this session that may take it back (it names
the item or an earlier decision and uses a word like cancel or instead). Check with
them. If it changed, add the new item with `replaces`, or set the old one to
`rejected`. If it still stands, record their confirmation from this session as
a new item that replaces the old one.

If a repeat block lists problems you already told the user about, add
one line naming what is still open rather than repeating the explanation.
Resolve each conflict or disclose it, update
the record, then finish. Never delete or weaken a check to get past the gate, and
copy quotes exactly from the user's messages or they will be reported as unverified.

A quote is also unverified when it starts just after a negation in the same
clause ("We don't have a venue yet, so let's book the library" does not verify
"let's book the library"). If the user did say it, quote the whole sentence.

## Authority boundary

The record never creates permission the user did not give. A summary field in
the record is not evidence of what the user said — the verbatim quote is.
