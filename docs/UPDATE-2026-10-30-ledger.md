# October 30 verified-quotes ledger

This source candidate builds on main `144fcde527aaafeb6cc8ffbb14b2bd983e7875e1`. It changes how the Claude adapter's Stop gate handles `.rumbo/verified-quotes.json`. It does not change the Python engine, protocol versions, record format or tools.

## Prepared distribution identities

- The Claude adapter **0.3.8** carries the change below in `rumbo/scripts/record.py`, with `rumbo/SPEC.md` updated to match.
- Python engine/package **0.3.5** and the OpenAI portable and Codex local adapters **0.3.6** are unchanged.
- Isolated Sites candidate **0.1.3** and its board app **0.1.3** are unchanged, as is the local board app **0.1.2**.

## What changed

- A ledger that exists but cannot be used is `LEDGER_UNREADABLE`. That covers a truncated or empty file, bad bytes, a wrong shape, no read permission, a directory and a dangling link. The gate blocks and leaves the file as it is. Before, it read as empty and the gate replaced it, losing the fingerprints of earlier sessions with nothing naming the ledger.
- A ledger that cannot be saved is `LEDGER_UNWRITABLE`. The gate blocks and the earlier file stays whole. Before, the failure was ignored, and a write that failed part way left a temporary file in `.rumbo/`.
- Ledger problems have their own limit of 3 blocks per session. Other problems block as they would with a healthy ledger, so a damaged ledger cannot use up the blocks a later conflict needs. `UNVERIFIED` lines count as other problems, even when an unreadable ledger caused them, so a new quote blocks within the same limit as on a healthy ledger.

## Recovery

Restore the file from a copy. Without one, tell the user and move it aside, and the gate starts a new ledger from the current transcript. Do not delete it to get past the block. Quotes from earlier sessions then need to be said again, or they stay `UNVERIFIED`.

## Verification, packaging and rollback

Run the Claude-adapter suite from `rumbo/` on python3 and on Python 3.9, then the release identity checks from the repository root. One release identity test needs the `jsonschema` developer dependency.

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

The Claude directory reads the plugin from `rumbo/` on main. No OpenAI submission, approval or Sites deployment is claimed. To roll back, return to `144fcde527aaafeb6cc8ffbb14b2bd983e7875e1`. There is no data migration.
