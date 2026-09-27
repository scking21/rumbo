# Rumbo

Keeps a Claude Code agent on the course you actually agreed to.

*Rumbo* is Spanish for a ship's course or heading.

## What it does

- records decisions in the user's exact words with a status (draft, preference, commitment, authorized, deferred, rejected, done, uncertain)
- computes schedule, deadline and budget checks with a script
- flags any number in a check the user never said
- a prompt hook suggests starting a record when a message looks like planning; the nudge appears at most once per session
- a Stop hook checks each quote in the record against the user's real messages in Claude Code's transcript and blocks (up to three times per session) while a check fails, a value is unsourced, a quote is unverified, a check that was failing was deleted, or the record file is unreadable or invalid

## Install

```
/plugin marketplace add scking21/rumbo
/plugin install rumbo@rumbo
```

Needs Python 3.9+ and nothing else. To pin a version, add the marketplace at a tag or commit you have reviewed.

## How it works

The record lives at `.rumbo/record.json` in your project. Example:
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

`scripts/record.py` subcommands:

- `validate`: checks the record for correctness
- `check`: validates and runs schedule/deadline/budget checks
- `show`: prints a compact summary for hook injection
- `init`: creates a new record with objective and quote
- `stop-gate`: Stop hook gate that blocks on conflicts or unsourced values

## Evidence

In a 20-run comparison on two synthetic planning conversations (Nemotron as the agent, with 3 of its calls in 2 runs served by a DeepSeek fallback; Kimi K3 grading against fixed rubrics), runs with Rumbo met 0.933 of required outcomes against 0.833 without, with 1.50 against 2.20 drift events, at about twice the wall time. It did not reduce invented facts: on one of the two conversations, runs with Rumbo invented a detail in 5 of 5 runs against 3 of 5 without, three of them a year forced by the date format this release no longer requires. The clearest effect: a schedule conflict (a 9:45 start that no longer fit a 12:30 close) was resolved or flagged in 3 of 5 runs with Rumbo and 0 of 5 without. Five runs per condition are too few to establish a reliable general effect; treat this as early evidence. Measured on 0.1.0 before dates without a year were allowed; that version made the agent invent a year in 3 of 5 runs, which the current `before` check no longer requires.

## Threat model

Rumbo is a memory aid against drift, not a sandbox against an agent that is trying to cheat. Quotes are verified against the transcript the harness writes, which the agent could still edit if it went out of its way to. Verification is lexical, not semantic: a quote must appear in one of the user's messages as whole words ("$900" does not match "$9000" or "$900.50") must not drop a minus sign in front of a number ("$900" does not match "Refund -$900"), and must not sit under a negation in the same clause ("spend $900" does not match "Do not spend $900"); it cannot tell whether the user meant it as a decision. record.json and the plugin's own files are editable by the agent. The Stop gate stops blocking after three attempts per session so it cannot trap a session, and anything still unresolved is visible in the conversation. The injected summary is marked as agent-written data, not instructions. `.rumbo/` holds the user's verbatim words, so add it to `.gitignore` before sharing a project.

## Limits

The record is a memory aid and never grants permission the user did not give; the agent can still ignore it outside the Stop hook; checks cover only times, dates and budgets.

## Privacy

Rumbo runs locally and makes no direct network requests or telemetry submissions. Its hook output (the record summary, including your quoted words, and Stop reasons) enters your Claude conversation and is processed by the Claude service you use. See [PRIVACY.md](PRIVACY.md) for what it stores, what it reads and how to remove it.

## License

MIT, Copyright (c) 2026 Corby King.