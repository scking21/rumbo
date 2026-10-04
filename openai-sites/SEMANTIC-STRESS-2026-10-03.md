# Offline semantic parity and state-size verification

This is functional evidence for the isolated Sites implementation against the canonical Python engine. It is not a security review, managed-host test, deployment, browser test, or release clearance. All identities, bytes, histories, and failures are synthetic. The Claude adapter remains independent and unchanged.

## Reproduce

From `openai-sites`, without npm setup, servers, Miniflare, or network:

```sh
node --test tests/codec.test.mjs tests/engine.test.mjs tests/artifact-byte-codec.test.mjs tests/semantic-*.test.mjs
node scripts/run-semantic-stress.mjs --seeds 512 --steps 128 --start 1831565813 --report /tmp/rumbo-semantic-stress.json
node scripts/measure-state-size.mjs /tmp/rumbo-state-size.json
```

The examples keep generated raw evidence outside the repository. The scripts need Node 24+ and local Python. Canonical policy regressions run from the repository root with:

```sh
python3 -m unittest discover -s tests -p test_artifact_json_policy.py -v
```

## Bounded generated traces

The main run uses xorshift32, starting at `0x6d2b79f5`; scenario `i` has seed `(start + i * 0x9e3779b9) mod 2^32`. The report records every exact seed. Each scenario completes a generated 1–5-task DAG through worker production, deterministic checks, independent review where required, and human acceptance before 128 randomized operations. The generator asserts that this initial workflow really completed, avoiding falsely reassuring traces that only reject invalid contracts.

On the revised source, **512 scenarios / 82,488 operations** matched every Python result/error digest. The run exercised all eight mutations plus state/artifact reads, replacements, repeated operations, integer and fractional lease clocks, dependency invalidation, authority failures, typed numbers, Unicode, and invalid attempts. Independent invariants check exact current evidence and upstream decisions for acceptance, owner authority, expired leases, one-event successful writes, and unchanged ledgers for failures/reads. This is bounded scenario coverage, not exhaustive proof.

The earlier scoped parser-policy verification: **67/67 pure JavaScript tests, 38/38 canonical core tests, and 8/8 canonical policy tests passed**, with no skips in these scoped runs. The full repository/runtime/browser suites were deliberately not run in this task. The vendored canonical oracle matched the updated source byte-for-byte.

Additional fixtures cover:

- 400 combinations of typed JSON expected/actual values; large integers, signed float zero, Boolean/null/string distinctions, nested values, Unicode keys
- Exact UTF-8 upload, filename, codepoint, integer-field and shared artifact parser boundaries
- Interrupted upload before/after stored bytes, successful retry, compare-and-swap conflict budgets 0/1/7/8, and a committed upload whose response is lost
- Full historical receipts surviving policy changes until an explicit new check
- BOM/endian detection, strict Unicode-scalar decoding, malformed encodings, duplicate keys and unused nonfinite values
- Standalone Sites test fixtures falling back to the exact vendored canonical source when the repository package is absent

## Reproduced discrepancies and scoped policy

Before the patch:

1. A `json_equals` check for `ok=true` passed in canonical Python but failed in Sites when a ~2 KiB artifact had an unused branch containing 990 nested arrays
2. NUL-separated ASCII bytes autodetected as UTF-16LE/BE or UTF-32LE/BE passed the canonical check but failed the Sites UTF-8-only decoder
3. An unused 4,301-digit integer passed Sites but failed canonical Python's default integer conversion limit; changing the interpreter setting changed Python's outcome

Each needs only create, claim, upload, and check to reproduce. Independent review additionally found raw surrogate-decoding differences and reachable UTF-16/UTF-32 key collisions through valid UTF-8 uploads. The shared artifact-only policy now requires strict Unicode scalar decoding and validates every JSON string/key before duplicate collapse. Proper non-BMP characters and escaped pairs remain supported; lone escaped surrogates in otherwise valid UTF-8 JSON, raw unpaired encodings and mixed literal/escaped forms now fail consistently. Generic codec/transport and normal upload validation are unchanged. New red/green fixtures cover 12 UTF-16 upload cases, both UTF-32 collision directions, discarded invalid duplicate values, BOM/endian variants, and preservation of historical receipts until explicit recheck. Recorded policy regressions failed before implementation (7 JavaScript cases and 5 Python subcases) and passed afterward. The shared artifact-only policy is documented in [CONTRACTS.md](../docs/CONTRACTS.md#artifact-json-parsing-and-compatibility): 512 open containers, 4,300 integer digits, strict scalar strings, and preserved byte detection/valid duplicate/nonfinite behavior. Depth-65 compatibility remains; transport depth and canonical serialization bounds are unchanged. Selected expected values at nesting 1/30/55/110 retain engine-level parity; 110 is direct-engine coverage, not a claim that a 64-level transport accepts it.

## State response size

The size script constructs legal canonical request-decision history, verifies its complete replay against Python by state hash and bytes, and performs a real append attempt. It uses the actual direct MCP dispatcher with an in-memory engine. There is no server or remote request. The state is never truncated.

| Boundary | Events | Event payload bytes | Full state bytes | MCP response bytes | Next append |
| --- | ---: | ---: | ---: | ---: | --- |
| One below event cap | 9,999 | 1,708,977 | 939,339 | 939,829 | succeeds to 10,000 |
| Event cap | 10,000 | 1,709,149 | 939,435 | 939,925 | `LEDGER_LIMIT` |
| One byte below payload cap | 4,025 | 16,777,215 | 16,467,575 | 16,468,065 | `LEDGER_LIMIT` |
| Exact room for next event | 4,025 | 16,777,045 | 16,467,405 | 16,467,895 | succeeds, fills 16,777,216 payload bytes |
| Payload cap | 4,025 | 16,777,216 | 16,467,576 | 16,468,066 | `LEDGER_LIMIT` |

A request-heavy legal history can therefore return about 16.47 MB through the existing state response. These are measured supported cases, not a proven maximum. Client/managed-host response capacity is unverified. No new summary/truncation API or live capacity claim was added. Rejected appends preserve the exact full history.
