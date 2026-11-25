# November 24 Claude adapter 0.3.12: checks that replace obsolete checks

This builds on [Claude adapter 0.3.11](UPDATE-2026-11-24.md). It changes only the Claude adapter in `rumbo/` and adds one optional field to the record format: `replaces` on a check.

## Distribution identities

- The Claude adapter is **0.3.12**.
- The Python engine/package **0.3.5**, the OpenAI portable and Codex local adapters **0.3.7** and the Sites candidate **0.1.3** are unchanged.
- As with 0.3.11, the Codex local package (`--kind local`) bundles `rumbo/scripts/record.py`. A package built from here also validates `replaces` on checks and prints a replaced check as `REPLACED` in `check`. Give the OpenAI adapters a new version before distributing a package built from here.

## What changed

- **A newer check can replace an obsolete one.** A check may list older checks in `replaces`, as items do. A replaced check stays in the record as history: `check` prints it as `<id>: REPLACED <kind>[ <label>] by <ids>` and leaves it out of the exit code, and `show`, `pre-write` and the Stop gate no longer treat it as an open problem. The newer check is checked as usual, so a conflict carried into it stays open. The ids must name other checks of the same kind, and a cycle is refused (`RECORD_BAD_REF`), since it would leave every check in it replaced. Deleting a replaced check that was failing at the previous block is still reported.
- **The commitments skill retires obsolete checks this way:** when the user's own values replace an assumption, or a decision drops the option a check was about, the agent adds the current check with `replaces` instead of keeping, editing or deleting the old one.
- **Two corrections to the 0.3.11 reply reader**, from review: a cap of 0 now has to be written in the reply (the source check counts 0 as always sourced, so "Catering costs $350. All set!" read as stating a $350 overrun of a $0 budget), and a word such as "estimate" after "you" or "your" no longer counts when up to two words come between ("your earlier estimate", "as you originally suggested"), since it gives the value to the user.
- **`scripts/claude_multiturn_eval.py`** runs the bundled eval cases one paragraph per turn with `claude -p --resume` and reports Stop blocks, replies that name record ids, cost and, with `--grade`, the case's graders. It spends model usage on the caller's account, runs one session at a time by default, stops a session at its first failed turn, and refuses to start without `--allow-shell`, because the agent under test runs shell commands without asking.

## Why

In the live sessions behind 0.3.11, 3 of 10 sessions had a check that the user's decisions had made obsolete and no way to retire it. The Stop gate reports a deleted failing check, so agents kept such a check and reported it reply after reply (12 replies in one session), deleted it, were blocked and restored it labelled "(moot)", or told the user "I've left them in the record rather than delete them".

## Live sessions

Four 15-turn sessions on this adapter (two of `01-workshop-full`, two of `02-launch-full`, sonnet) were cut off after turns 10 to 12 by the account's usage limit, before the final plans, so they were not graded. Up to that point the agents retired obsolete checks with `replaces` without being asked: 24 of the 37 checks they wrote ended as replaced history, for example a budget with Dr. Okafor replaced by one with the maker-space team. Every check id the agents used was still in the final records, and no reply named a record id. There were 3 Stop blocks in the 44 completed turns, all on a draft schedule the agent had assumed before the user gave one. This shows the field is used as intended; it is not a measured improvement in outcomes.

A later complete 15-turn `01-workshop-full` session on 0.3.13, run with `scripts/claude_multiturn_eval.py --grade`, passed all 6 graders with no Stop block and no record id in any reply, for $0.88. After the user chose the maker-space team, the agent replaced its budget check for Dr. Okafor with one for the maker-space team instead of keeping or deleting it. Of its 12 checks, 7 ended as replaced history; the 2 still failing were the real conflicts, the 9:45 start running past the 12:30 close and the printer deadline after the workshop, and every reply stated both, so the gate had nothing to block. One session is an example, not a measurement.

## Compatibility, verification and rollback

Version 0.3.11 and earlier ignore `replaces` on a check, even a malformed one: they read the record and check the replaced check again, so after a rollback it is reported as before. Records without the field read the same in every version.

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.11 merge on main.
