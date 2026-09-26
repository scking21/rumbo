# Rumbo: design and reference

## Why these pieces

Rumbo came out of experiments on why AI agents drift from what a person agreed to. Two failures kept recurring:

1. **Status flattening.** "Please draft the schedule" got stored as a decision ("Schedule is fixed"), so a later session treated a draft as settled. Rumbo gives every item an explicit status, and `draft` is distinct from `commitment`.
2. **Unchecked arithmetic.** Asked to "reconcile conflicts", an agent checked the wrong things: a 9:45 start plus 75 + 20 + 75 minutes ends at 12:35, after a 12:30 close, and a March 20 printer deadline falls after a March 12 event. Rumbo turns times, dates and amounts into typed checks that a script computes.

A third came from end-to-end runs with Rumbo itself: agents made failing checks pass by inventing inputs (shortening a stated break, adding a year the user never gave). Every value in a check must therefore come from the user's quoted words.

Principles: keep the user's verbatim words for every item, keep the objective separate from constraints on it, and let the user correct any interpretation. The record is a memory aid; it never grants permission the user did not give.

## Data shape: `.rumbo/record.json` in the user's project

```json
{
  "version": 1,
  "objective": {"text": "Plan a half-day workshop on March 12", "quote": "I'm organizing a half-day workshop on data visualization for our regional library association. It's the morning of March 12. The venue holds 40 people and we've budgeted $600 total.", "ref": "E1"},
  "items": [
    {"id": "I1", "text": "Schedule frame", "quote": "Please draft the schedule: 9:00 arrival, two 75-minute sessions with a 20-minute break, 12:30 close.", "ref": "E4", "status": "draft"},
    {"id": "I2", "text": "Maker-space session starts at 9:45", "quote": "The maker-space team just confirmed for the 9:45 session.", "ref": "E9", "status": "commitment"},
    {"id": "I3", "text": "Maker-space team only, for this workshop", "quote": "I think we should go with just the maker-space team for this workshop.", "ref": "E12", "status": "commitment", "scope": "this workshop only"},
    {"id": "I4", "text": "Budget caps", "quote": "Our budget review came back: the $600 total is firm, and no line item can exceed $300.", "ref": "E11", "status": "commitment"},
    {"id": "I5", "text": "Catering covered up to $200", "quote": "The library foundation said they'd cover catering up to $200 if registration is free.", "ref": "E3", "status": "commitment"},
    {"id": "I6", "text": "Printer deadline", "quote": "The printer needs final details by March 20: session titles, speaker names, and the schedule.", "ref": "E13", "status": "commitment"}
  ],
  "checks": [
    {"id": "C1", "kind": "fits_window", "label": "session schedule", "start": "09:45", "segments_min": [75, 20, 75], "end": "12:30", "refs": ["I1", "I2"]},
    {"id": "C2", "kind": "before", "label": "printer deadline precedes workshop", "first": "03-20", "second": "03-12", "refs": ["I6"]},
    {"id": "C3", "kind": "within_budget", "label": "budget", "amounts": [200], "total_cap": 600, "item_cap": 300, "refs": ["I4", "I5"]}
  ]
}
```

Running `check` on this record reports C1 and C2 as FAIL (the 12:35 overrun and a printer deadline after the event) and C3 as PASS, with no unsourced values: every number in a check appears in a quote.

Field rules:

- `objective`: required object with nonempty `text` and nonempty `quote` (the user's own words, verbatim). `ref` optional string.
- `items`: list, may be empty. Each item requires `id` (unique across items), nonempty `text`, nonempty `quote`, and `status`. `ref`, `scope` (empty string means unspecified, not unlimited) and `replaces` (list of item ids) are optional.
- `status` is one of: `exploring`, `preference`, `draft`, `commitment`, `authorized`, `deferred`, `rejected`, `done`, `uncertain`.
- `checks`: list, may be empty. Each requires unique `id` (unique across checks) and `kind`; `label` optional string; `refs` optional list of item ids.
  - `fits_window`: `start` and `end` as `HH:MM` 24-hour; `segments_min` a nonempty list of positive integers. Passes when start + sum(segments) <= end.
  - `before`: `first` and `second`, both `MM-DD` or both `YYYY-MM-DD`. Use `MM-DD` unless the user stated a year. Passes when first <= second.
  - `within_budget`: `amounts` a list of non-negative numbers; `total_cap` a number; `item_cap` optional number. Passes when sum(amounts) <= total_cap and, if `item_cap` is present, every amount <= item_cap.

### Sourced values

SOURCE TEXT is the objective quote plus every item quote. A check value is sourced when it appears there: numbers as standalone numbers (commas ignored; 0 always counts), times as `HH:MM` or `H:MM`, dates by month and day ("March 20", "Mar. 20" or "03-20") and, for `YYYY-MM-DD`, also the four-digit year. A check whose arithmetic passes but uses an unsourced value is reported as `UNSOURCED`.

## `scripts/record.py` (Python 3.9+, standard library only)

All subcommands take `--record PATH` (default `.rumbo/record.json` relative to the working directory).

Exit codes, uniform across subcommands: `0` clean, `1` content problem (invalid record, failing or unsourced check), `2` tool or I/O problem (unreadable file, bad JSON, bad arguments). Every content diagnostic is one line in the form `<json-path>: <CODE>: <recovery hint>`, e.g. `items[2].status: RECORD_BAD_STATUS: use one of exploring, preference, draft, commitment, authorized, deferred, rejected, done, uncertain`.

- `validate`: prints `RECORD_OK` and exits 0, or one line per fault and exits 1. Codes: `RECORD_MISSING_FIELD`, `RECORD_EMPTY_FIELD`, `RECORD_BAD_STATUS`, `RECORD_DUP_ID`, `RECORD_BAD_REF`, `CHECK_BAD_KIND`, `CHECK_BAD_VALUE`. Missing file: `RECORD_NOT_FOUND` on stderr, exit 2. Bad JSON: `RECORD_UNREADABLE` on stderr, exit 2.
- `check`: validates first, then prints one line per check: `C1: PASS ...`, `C1: FAIL fits_window session schedule: 09:45 + 170 min ends 12:35, 5 min after 12:30` (a FAIL line gains `(also unsourced: ...)` when relevant), or `C1: UNSOURCED fits_window ...: segments_min 15 not in the user's quoted words`. `before` failure text: `03-20 is 8 days after 03-12`. Exit 1 if any check fails or is unsourced.
- `show [--max-chars N]` (default 1500): compact summary for the prompt hook. Prints `Objective: <text>`; then one line per live item (not `done`, `rejected` or replaced), in status order commitment, authorized, draft, preference, exploring, deferred, uncertain, as `[<status>] <id> <text>` plus ` (scope: <scope>)`; then `CONFLICT <id>: ...` for failing checks and `ASSUMPTION <id>: ...` for unsourced ones. If the record is invalid it prints one line saying so. If there is no record it prints nothing, except when the hook JSON on stdin has a `prompt` that looks like planning (times, `$` amounts, dates, or words such as plan, schedule, budget, deadline): then it prints a nudge naming the `init` command and, when the hook input carries a `session_id`, writes a per-session marker. Always exits 0.
- `init --objective TEXT --quote TEXT`: creates the record. `--quote -` reads the quote from stdin, so a quoted heredoc keeps `$` amounts and backticks intact. Refuses to overwrite an existing record (`RECORD_EXISTS`, exit 1).
- `stop-gate`: for the Stop hook; reads the hook JSON from stdin and never blocks twice in a row (`stop_hook_active`). With a record: blocks once, with `{"decision": "block", "reason": ...}`, when any check fails or is unsourced; the reason asks the agent to resolve or disclose each conflict and name its assumptions. Without a record: blocks once per session if the prompt hook nudged in that session, asking the agent to start a record or say in one line why the work does not need one. Otherwise silent. Unparseable stdin counts as no input.

Per-session markers live in `$RUMBO_STATE_DIR` (default: the system temp directory under `rumbo/`).

## Tests

`python3 -m unittest discover -s tests -v` from the plugin root. Tests run the script as a subprocess in temporary directories and cover every validation code, check kind, the source check, the nudge and its once-per-session enforcement, the stop gate, and the workshop fixture in `tests/fixtures/workshop.json`.

## Packaging

- `.claude-plugin/plugin.json`: name `rumbo`, version `0.1.0`, MIT.
- `hooks/hooks.json`: `UserPromptSubmit` runs `record.py show`; `Stop` runs `record.py stop-gate`; both against `${CLAUDE_PROJECT_DIR}/.rumbo/record.json`.
- `skills/commitments/SKILL.md`: when and how the agent maintains the record.
- The repository root's `.claude-plugin/marketplace.json` lists `rumbo` with source `./rumbo`.
