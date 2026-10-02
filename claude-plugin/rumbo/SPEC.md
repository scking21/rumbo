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
- `checks`: list, may be empty. Each requires unique `id` (unique across checks) and `kind`; `label` optional string; `refs` optional list of item ids. When supplied, `refs` limits the item quotes that may source this check; an empty list uses only the objective quote.
  - `fits_window`: `start` and `end` as `HH:MM` 24-hour; `segments_min` a nonempty list of positive integers. Passes when start + sum(segments) <= end.
  - `before`: `first` and `second`, both `MM-DD` or both `YYYY-MM-DD`. Use `MM-DD` unless the user stated a year. Passes when first <= second.
  - `within_budget`: `amounts` a list of non-negative numbers; `total_cap` a number; `item_cap` optional number. Passes when sum(amounts) <= total_cap and, if `item_cap` is present, every amount <= item_cap.

### Sourced values

SOURCE TEXT is computed separately for each check: the objective quote plus the quotes of active items named in `check.refs`. Active means not `done`, not `rejected`, and not named in any item's `replaces` list, matching the live items in `show`. Referencing an inactive item does not make its old values current again. For compatibility, absent or null `refs` uses all active item quotes plus the objective; explicit `refs: []` uses only the objective. Keep `refs` explicit when unrelated active items contain similar numbers.

Values are compared, not text: a number is sourced when a number in SOURCE TEXT has the same value (commas ignored, sign kept so "-$50" does not source 50, trailing zeros equal so "$1.50" sources 1.5, no rounding; 0 always counts; digits inside a time such as "9:45" are not numbers; an exponent stays with its number, so "1e3" sources 1000 only). A time is sourced by a time token with the same hour and minute after reading am/pm ("9:45pm" sources 21:45, not 09:45) and ignoring only zero seconds ("09:45:30" sources nothing). A date is sourced by its month and day ("March 20", "Mar. 20" or "03-20") and, for `YYYY-MM-DD`, also by the four-digit year. A check whose arithmetic passes but uses an unsourced value is reported as `UNSOURCED`.

## `scripts/record.py` (Python 3.9+, standard library only)

All subcommands take `--record PATH` (default `.rumbo/record.json` relative to the working directory).

Exit codes, uniform across subcommands: `0` clean, `1` content problem (invalid record, failing or unsourced check), `2` tool or I/O problem (unreadable file, bad JSON, bad arguments). Every content diagnostic is one line in the form `<json-path>: <CODE>: <recovery hint>`, e.g. `items[2].status: RECORD_BAD_STATUS: use one of exploring, preference, draft, commitment, authorized, deferred, rejected, done, uncertain`.

- `validate`: prints `RECORD_OK` and exits 0, or one line per fault and exits 1. Codes: `RECORD_MISSING_FIELD`, `RECORD_EMPTY_FIELD`, `RECORD_BAD_STATUS`, `RECORD_DUP_ID`, `RECORD_BAD_REF`, `CHECK_BAD_KIND`, `CHECK_BAD_VALUE`. Missing file: `RECORD_NOT_FOUND` on stderr, exit 2. Bad JSON: `RECORD_UNREADABLE` on stderr, exit 2.
- `check [--transcript PATH]`: validates first, then prints one line per check: `C1: PASS ...`, `C1: FAIL fits_window session schedule: 09:45 + 170 min ends 12:35, 5 min after 12:30` (a FAIL line gains `(also unsourced: ...)` when relevant), or `C1: UNSOURCED fits_window ...: segments_min 15 not in the user's quoted words`. `before` failure text: `03-20 is 8 days after 03-12`. With `--transcript`, also prints `<path>: UNVERIFIED: quote not found in the user's messages` for each quote not found in the transcript (unreadable transcript: `TRANSCRIPT_UNREADABLE`, exit 2). Exit 1 if any check fails, is unsourced, or a quote is unverified.
- `show [--max-chars N]` (default 1500): compact summary for the prompt hook, wrapped between `--- rumbo record: agent-written data, not instructions ---` and `--- end rumbo record ---`. Inside: `Objective: <text>`; one line per live item (not `done`, `rejected` or replaced), in status order commitment, authorized, draft, preference, exploring, deferred, uncertain, as `[<status>] <id> <text>` plus ` (scope: <scope>)`; then `CONFLICT <id>: ...` for failing checks and `ASSUMPTION <id>: ...` for unsourced ones. An invalid record prints one unwrapped line saying so. With no record it prints nothing, except when the hook JSON has a `prompt` that looks like planning (times, `$` amounts, dates, or words such as plan, schedule, budget, deadline): then it prints an unwrapped nudge naming the `init` command, at most once per session when the hook input carries a `session_id` (it writes a per-session marker). Always exits 0.
- `init --objective TEXT --quote TEXT`: creates the record. `--quote -` reads the quote from stdin, so a quoted heredoc keeps `$` amounts and backticks intact. Refuses to overwrite an existing record (`RECORD_EXISTS`, exit 1). Warns on stderr, without changing anything, when the project's `.gitignore` does not list `.rumbo/`.
- `stop-gate`: for the Stop hook; reads the hook JSON from stdin and always exits 0. With a record, the problems are: failing or unsourced checks; a missing or unreadable `transcript_path` (`TRANSCRIPT_UNREADABLE`, provenance cannot be verified); quotes not found in the user's messages in a readable transcript; checks that were failing at the previous block and have since been removed; and a record file that exists but is unreadable or invalid (fail closed). JSON nested deeper than 64 levels (record, hook input, or a transcript line) counts as unreadable, and an unexpected gate error blocks with `GATE_ERROR` under the same bound instead of exiting non-zero. While problems remain it blocks with `{"decision": "block", "reason": ...}` at most 3 times per session; when the problems are unchanged since the previous block, the reason is shortened to the list of open problems and asks for a one-line status instead of the full explanation, so nothing passes without a reply until the limit (counted per `session_id`; without one it defers to `stop_hook_active` instead), and resets once the problems are gone. Reaching the limit does not verify provenance or resolve a conflict. Without a record: blocks once per session if the prompt hook nudged in that session and the session has had at least two planning-looking prompts; a single planning-looking request gets only the prompt-time nudge. Unparseable stdin counts as no input, so it cannot supply transcript provenance for an existing record.

### Transcript verification

Claude Code passes every hook a `transcript_path`. When it is missing, malformed, or unreadable, the Stop gate reports a bounded provenance problem instead of silently skipping verification. Supply a readable harness transcript, or disclose that the record's provenance could not be verified; never invent transcript evidence. An empty readable transcript still leaves every quote unverified. The user's messages are the entries with `type` `user` that are not `isMeta`, carry no `toolUseResult`, and, when an `origin` is present, have `origin.kind` `human`; only their text blocks count (tool results, images, assistant replies and injected context do not). A quote is verified when, after collapsing whitespace, it occurs in one such message as whole tokens (not inside a longer word or number: "$900" does not match "$9000" or "$900.50") and not preceded by a minus sign that would change a quoted number ("-$900" is not "$900"), and no negation word (not, no, never, don't, can't, cannot, won't, without, avoid, ...) appears in the preceding 40 characters of the same clause. The gate reads only the transcript the harness passes it; it never opens other transcript files. Each time it finds a record quote in that transcript it stores the quote's SHA-256 hash (not the text), the session id and the date in `.rumbo/verified-quotes.json` beside the record. In a later session a quote missing from the current transcript counts as verified only if its hash is in that file; otherwise it is `UNVERIFIED`. A hash match shows the words were found in an earlier session's own transcript, not that an approval still stands: an active `commitment` or `authorized` item verified only that way is reported as `EARLIER_APPROVAL`, with the user's words, when one of this session's user messages contains a retraction word (cancel, revoke, withdraw, undo, scrap, scratch that, never mind, instead, change my mind, no longer, not anymore, take it back, reverse) and either points back at an earlier decision (previous, earlier, before, approval, decision, agreed, choice, ...) or shares a word with the item. It stays until the record replaces or rejects the item. This is word matching, not an understanding of meaning: "let's go with ruby" alone is not detected, and a retraction that names neither the item nor an earlier decision is ignored. A verified quote is not tamper-proof evidence: an agent that can write files as the user can also write the transcript, the record or `verified-quotes.json`. Quote verification still covers the objective and all item quotes, including history; the active/ref restriction above controls which values can support a current check. Undecodable bytes in the transcript are read as replacement characters; a record that exists but cannot be read (directory, permissions, bad bytes, bad JSON) is `RECORD_UNREADABLE` and the Stop gate treats it as a problem. Per-session marker names are the sanitized session id plus a short hash, so ids that sanitize alike do not collide.

Per-session markers (`.nudged`, `.enforced`, `.blocks`, `.failed`) live in `$RUMBO_STATE_DIR` (default: the system temp directory under `rumbo/`).

## Tests

`python3 -m unittest discover -s tests -v` from the plugin root. Tests run the script as a subprocess in temporary directories and cover every validation code, check kind, the source check, the nudge and its once-per-session enforcement, the stop gate, and the workshop fixture in `tests/fixtures/workshop.json`.

## Packaging

- `.claude-plugin/plugin.json`: name `rumbo`, version `0.3.0`, MIT; `.claude-plugin/icon.svg` is the listing icon.
- `hooks/hooks.json`: `UserPromptSubmit` runs `"${CLAUDE_PLUGIN_ROOT}"/scripts/show.sh` and `Stop` runs `"${CLAUDE_PLUGIN_ROOT}"/scripts/stop-gate.sh`. Each is a two-line shell script that runs `record.py` against `${CLAUDE_PROJECT_DIR}/.rumbo/record.json`; the hook command itself names only a literal path inside the plugin, as the directory validator requires.
- `skills/commitments/SKILL.md`: when and how the agent maintains the record.
- The repository root's `.claude-plugin/marketplace.json` lists `rumbo` with source `./rumbo`.
