# November 24 Claude adapter 0.3.13: quote verification inside the hook timeout

This builds on [Claude adapter 0.3.12](UPDATE-2026-11-24-check-replaces.md). It changes only how fast the Claude adapter's Stop gate verifies quotes; what it reports is unchanged.

## Distribution identities

- The Claude adapter is **0.3.13**.
- The Python engine/package **0.3.5**, the OpenAI portable and Codex local adapters **0.3.7** and the Sites candidate **0.1.3** are unchanged. As with 0.3.11 and 0.3.12, the Codex local package bundles `rumbo/scripts/record.py`, so a package built from here carries this code; the Codex adapter never reads transcripts, so its behaviour is unchanged.

## What changed

The Stop gate checks every record quote against every user message of the session. It ran a regular expression for each pair, escaped the quote again for each message, folded every message again for each unverified quote, and scanned each match's whole message prefix for a negative sign and a clause. The time grew with quotes times messages:

| Record and session | 0.3.12 | 0.3.13 |
| --- | --- | --- |
| 60 items, 20 checks, 200 messages, five 20 KB pasted documents | 1.17 s | 0.19 s |
| 300 items, 80 checks, 800 messages, five 50 KB documents | 17.0 s | 0.77 s |
| 1,000 items, 200 checks, 2,000 messages, five 100 KB documents | 137 s | 3.4 s |

The hook's timeout is 10 s, and a Stop hook that times out lets the turn end unchecked, so on 0.3.12 a long-lived record in a long session was silently not checked. Now a message that does not contain the quote's folded text is rejected by a substring test before any pattern runs (the pattern can only match where that text occurs), each quote's pattern is compiled once, messages are folded once, and each match reads only the 4 characters before it for a sign (the `$` anchor also matches before a final newline, so 3 would not be exact) and the 40 before it for its clause.

The other hooks (`show`, `pre-write`, `validate`, `check`) stayed under 0.4 s on the largest record. Stop gate output was byte-identical between 0.3.12 and 0.3.13 on these sessions, as was `check --transcript`, and the old and new quote matching agreed on 880,000 fuzzed pairs, including signs, negations, clause breaks and trailing newlines.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

`rumbo/tests/test_gate_scale.py` keeps the shortcuts exact and fails if a 400-quote record in a 1,200-message session takes 3 s or more; 0.3.12 took about 16 s there. To roll back, return to the 0.3.12 merge on main. There is no data migration.
