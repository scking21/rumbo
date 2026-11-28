# November 28 Claude adapter 0.3.27: outcome handoffs, zero factors and spoken signs

[PR #52](https://github.com/scking21/rumbo/pull/52) changed the Claude adapter without a new version, so a plugin on 0.3.26 had no sign of them. This release gives those changes a version, documents them, and adds two small fixes. It builds on [Claude adapter 0.3.26](UPDATE-2026-11-26-money-reading.md).

## Distribution identities

- The Claude adapter is **0.3.27**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** keep their versions here. PR #52 also changed them, and their releases are left to that work. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own version.

## From PR #52

- **An outcome ledger.** For multi-deliverable or delegated work, a record can name a `target` and keep one `outcomes` row per requested result. Each row has an owner, an acceptance test and a status:
  - `runnable` rows need a `next_action`;
  - `blocked` rows need a `blocker` and a `restart_trigger`;
  - `verified` rows need `evidence`, and can bind local files by SHA-256 under `artifacts`.
  
  A row can also list `required_checks` that must pass. `validate` checks the rows, and `show` lists them.
- **`handoff --root PROJECT`.** The new command prints the record's SHA-256, the target and every row with the current state of each bound file, then `CONTINUE`, `BOUNDED` or `COMPLETE`. A verified row whose file changed, or whose required check fails, is unsourced or is missing, goes back to runnable. The standard `.rumbo/record.json` must sit in the given root.
- **The Stop gate holds while an outcome is runnable** or its bound evidence is stale. Hashing in the hook stops at 16 MiB a file. A blocked row does not hold the stop, and a record without outcomes behaves as before.
- **Zero factors.** In a price-per-unit entry, a zero price needs "free", "at no charge" or an explicit zero amount in the same clause as its quantity. A zero quantity needs "0", "zero" or "no" before a count noun that matches the unit of a stated rate. Before, a 0 was always sourced, so a made-up zero factor could turn a line's cost into 0 without anyone saying so. Other amounts and caps of 0 still count as sourced.
- **Spoken signs.** "minus two hours" and "negative an hour" no longer source a positive duration, and "an hours" no longer reads as one hour.

## Fixes in this release

- **`handoff --reviewed-record-sha256 DIGEST`.** The command already compared the record with a reviewed digest, but only the OpenAI adapter's command line offered the flag. The Claude command now offers it too: a record whose bytes changed since review exits 2 with `HANDOFF_RECORD_CHANGED`.
- **Repeat blocks name outcomes in words.** At a later turn's stop, the short repeat block named a check by its label but an outcome only as `OUTCOME O2`. It now adds the outcome's text, as in "OUTCOME O2 (Index saved and read back)", so the agent can tell the user what is open without the record's ids.

## Evidence

- `rumbo/tests/test_outcome_handoff.py` gains tests for the pinned handoff and the repeat wording. The suite already covers the ledger, the handoff states and the Stop gate.
- PR #52 leaves the saved data unchanged. Across the 496 live checks in the 206 final records saved since November 24, no value is sourced differently, and no record's validation changes. No saved record uses outcomes. The Stop-block replay reads the same 35 of 64 blocks as stated.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.26 merge on main (f668e89). A record that uses `target` and `outcomes` then fails validation, so remove those fields first.
