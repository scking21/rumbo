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
- `check` — validate, then print `PASS`/`FAIL` per check, `REPLACED` for a check a newer one replaces, and `DROPPED` for one a decision dropped; exit 1 if any check fails or is unsourced.
- `show [--max-chars N]` — compact summary; silent when no record exists.
- `stop-gate` — read the Stop hook input on stdin; block up to three times per session while checks or provenance remain unresolved. A failing or unsourced check that your reply already states (see Stopping) does not block. If the problems are unchanged when you stop again right after a block, the stop passes; at a later turn's stop, unchanged problems get a one-line status block.
- Exit codes: 0 clean, 1 content problem, 2 tool or I/O problem.

## When to start

Run `init` the first time the user sets a multi-step goal, passing the user's
own words verbatim through `--quote -` with a quoted heredoc (`<<'QUOTE'`),
since inside double quotes the shell rewrites `$` amounts and backticks. The objective is what the user is trying to
achieve. Constraints, cautions and limits go in items, never in the objective.
If a hook line says "no decision record yet", decide whether this is multi-step
work with decisions; if it is, run init with the user's own words; if not,
ignore it. A record with only its objective checks nothing: once you start
one, record the decisions the user has already made, and keep adding them.

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

A check's values must come from the user's quoted words. If you must assume a value (a start time, a shortened break), leave it visible (`check` shows it as UNSOURCED) and tell the user plainly that it is your assumption. Never change a value to make a check pass.

When the user later gives a value you assumed, or their own plan replaces the
one a check was about, add an item with their words and a check with their
values that lists the old check's id in `replaces`. That records the user's
correction; it is not changing a value to pass. When a decision drops the
option a check was about, replace that check with the same kind of check for
what the user chose. If their choice leaves nothing of that kind to check (a
speaker's payment deadline once they go without that speaker), record the
decision as an item that replaces the option's items, quoting just the words
that drop the option, and set the check's `dropped_by` to that item's id. A
decision that names a date, time or amount may change the check instead; then
replace it. A replaced or dropped check stays as history and is no longer
reported; never delete a check. Do not keep reporting an assumption the user
has already settled.

List the supporting item ids in each check's `refs`. Only those items' quotes
and the objective quote source the check; `done`, `rejected`, and replaced items
cannot source it. Missing or null `refs` falls back to all active items for legacy
records, while `refs: []` means only the objective. Include every supporting item
explicitly so unrelated numbers cannot accidentally make an assumption look sourced.

Add items and checks by editing the JSON directly, then run `validate`:

```json
{"id": "I3", "text": "Maker-space team only", "quote": "I think we should go with just the maker-space team for this workshop.",
 "ref": "E12", "status": "commitment", "scope": "this workshop only", "replaces": ["I6"]}
{"id": "C1", "kind": "fits_window", "label": "session schedule", "start": "09:45", "segments_min": [75, 20, 75], "end": "12:30", "refs": ["I1"]}
{"id": "C4", "kind": "within_budget", "label": "budget with the maker-space team", "amounts": [0, 200], "total_cap": 600,
 "refs": ["I3", "I5"], "replaces": ["C2"]}
{"id": "C5", "kind": "before", "label": "Dr. Okafor's payment deadline", "first": "03-12", "second": "04-01",
 "refs": ["I1", "I6"], "dropped_by": "I3"}
```

Every item carries the user's verbatim words in `quote`. A newer item or
check that supersedes an older one lists the older id in `replaces`; never
delete history.

## Times, dates and money

Whenever the record holds a schedule, a deadline relative to an event, or a
budget cap, add a check:

- `fits_window` — `start`, `end` as `HH:MM`, `segments_min` as a list of minutes.
  If the window runs past midnight ("9pm to 1am"), add `"end_next_day": true`.
- `before` — `first`, `second` as either both `MM-DD` or both `YYYY-MM-DD`.
- `within_budget` — `amounts`, `total_cap`, optional `item_cap`. For a price
  per unit ("$45 per person for 12", "$150 an hour for 4 hours") write the
  entry as `{"unit": 45, "quantity": 12}` and let the script multiply; never
  put a product you computed in `amounts`.

Run `check` before delivering any plan, schedule or summary. A FAIL line is a
conflict: resolve it, or state it plainly to the user with its values.

A value is sourced however the user wrote it: "March 20th", "20 March", "3/20"
or the end of "March 18–20" for `03-20`; "9am" or "noon" for `09:00` or `12:00`;
"2-hour", "two hours" or "1 hour 15 minutes" for minutes ("an hour and a
half" is 90, "half an hour" 30); "twenty-minute" for 20;
"$1.5k", "1.5 thousand" or "$1.5M" for 1500 or 1500000. Copy the user's numbers
exactly; do not convert them yourself. A bare "at 9" does not say morning or
evening: ask.

Write dates as MM-DD unless the user stated the year. Never add a year the
user did not say, in the record or in what you write: "March 12", not "March
12, 2027". If the dates cross a year boundary, you need the user's years. A
`before` failure that says "in the same year" is that case: ask the user.

## Tell the user

When an item becomes a commitment or is replaced, say it in one line:
"Treating as decided: ...". If the user corrects an item, fix the record
immediately; the user's correction always wins over the record. Describe items
and checks in the user's terms: ids such as I3 or C1 belong to the record, and
the user never sees it.

## Before writing

Before you write or edit a file, a hook may hold the write once to show you the
record's open problems (`CONFLICT` and `ASSUMPTION` lines, each with the action
to take) and the items the user has not decided (`NOT DECIDED` lines). Write
again with them in view: fix the plan only as the user agrees, or say the
problem plainly in what you write, and present each undecided item as open. The
same lines do not hold a write again. In a planning session with no record, the
first write is held once so you can start the record before the plan. After a
context compaction the record is shown again; trust it over the compacted summary.

In what you write, only `commitment` items are decided. Present a `draft`,
`preference`, `authorized`, `uncertain` or `deferred` item as open, a proposal
or something to confirm. A no to one option rules that option out; it does not
choose the others.

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
a new item that replaces the old one. A decision that drops a check counts too:
if the user takes it back, replace it, and the check comes back.

The gate reads the reply you are about to send. A conflict is stated when one
line of it names the values that conflict: the time the plan reaches and the
end it misses ("the sessions end at 12:35, after the 12:30 close", or "five
minutes past the close"), both dates with a word that orders them ("the March
20 deadline is after the March 12 workshop", with the years when they differ),
or the total and its cap ("$550, over the $500 budget", or "$50 over the
budget"). An assumed value is stated when its line, its section or the opening
of the reply calls it your assumption, estimate or proposal, or its line asks
the user about it; a block written as a time range ("9:20–10:35") names its
minutes. Once a reply has stated every assumed value of a check, a later
reply in the session states them with one line that calls one of them, or the
check's budget, schedule or dates, still your assumption ("9:00–12:30 is still
my assumption", "the budget figures are still my estimates"), until a value
changes. A conflict you have stated in full works the same way: a later line
that names one of its values as still a problem ("the 9:45 start still ends
at 12:35") states it, while the conflict stays the same. Stated problems do
not block.

If a repeat block lists problems you already told the user about, add
one line saying what is still open, in the user's terms rather than the
record's ids, instead of repeating the explanation.
Resolve each conflict or disclose it, update
the record, then finish. Never delete or weaken a check to get past the gate, and
copy quotes exactly from the user's messages or they will be reported as unverified.
For a decision made in a question dialog, the quote is the exact option label or typed answer.

A quote is also unverified when it starts just after a negation in the same
clause ("We don't have a venue yet, so let's book the library" does not verify
"let's book the library"). If the user did say it, quote the whole sentence.

## Authority boundary

The record never creates permission the user did not give. A summary field in
the record is not evidence of what the user said — the verbatim quote is.
