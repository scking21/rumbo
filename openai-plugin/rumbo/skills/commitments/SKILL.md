---
name: commitments
description: Preserve user decisions and explicitly check sourced dates, durations, budgets and plan drift in a local Codex project.
---

# Codex-local commitments

This is an explicit workflow, not automatic enforcement. Invoke it when the user asks to track commitments, check a plan, or recover agreed decisions. Claude lifecycle hooks are not installed here. Remote-only/hosted MCP cannot execute this skill's local helper; use its supported coordination tools instead.

Resolve `../../scripts/commitments.py` relative to this installed SKILL.md directory. Use an absolute resolved helper path and the authorized project's explicit record path. Do not guess a plugin environment variable, use the current directory as proof of project ownership, or read private session directories. Python 3.9+ and the bundled stdlib-only runtime are required; missing dependencies are not authority to install them.

## Recover and preserve

Read the authorized project's `.rumbo/record.json` before changing it. If it exists, preserve all decisions, quote references, statuses and replacement history. Use only accessible conversation evidence supplied by the user or an authorized export. Record requested/planned work separately from verified completion. No transcript verification is provided by this adapter: matching a recorded quote to a value does not prove that quote came from the user.

When a new record is authorized, run `python3 /absolute/plugin/scripts/commitments.py init --record /absolute/project/.rumbo/record.json --objective 'Objective' --quote -` and supply the exact quote over stdin. In a shell, use a quoted heredoc delimiter such as `<<'QUOTE'` so dollar signs and backticks remain literal. Never overwrite an existing record to initialize again.

After initialization inspect the record's actual schema before editing. Preserve the objective's `quote`, each item's verbatim `quote`, stable `id`, optional source `ref`, and `replaces` list. Each check's `refs` lists its supporting item IDs; `refs: []` sources only the objective. Missing or null `refs` retains the legacy all-active-items behavior. Done, rejected and replaced items cannot source checks. Preserve explicit statuses: exploring, preference, draft, commitment, authorized, deferred, rejected, done, uncertain. Retain superseded items with their replacement link. Do not promote a preference into authorization or a plan into completion.

## Check bounded units

Run `validate --record PATH` after an authorized record edit. Run `check --record PATH` before using a plan, schedule or budget in an answer, and `show --record PATH --max-chars 3000` to recover context after a break. Use the same absolute helper prefix for each command.

Supported deterministic checks include `fits_window` (explicit `end_next_day: true` for an overnight window), `before` with real dates, and `within_budget` with exact decimal amounts or `unit * quantity`. Populate a check only when its values, units and quote references are supported. Inspect the validator's diagnostics rather than inventing schema fields. Tests of numeric consistency are not independent proof of the underlying facts or a complete natural-language interpretation.

On a conflict or unknown result, preserve the failing record, explain the exact uncertainty, and fix only from evidence or ask the smallest necessary question. Never delete a commitment, change its status, weaken a check or invent a quote merely to get a pass. Review the full record if the compact view is truncated. Before a final answer, confirm the actual check output and unresolved issues; command completion alone is not task completion.

This helper exposes only init, validate, check and show. It has no Claude Stop/PreToolUse hook, no background listener, no transcript path option, no model invocation and no additional MCP authority. Use the separate coordination/review skills for project aliases, task claims, artifact evidence and reviewer roles.
