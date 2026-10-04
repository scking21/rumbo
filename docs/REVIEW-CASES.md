# Distribution-specific reviewer cases

These files describe expected behavior, not observed results or completed host tests. Keep actual results, screenshots, package SHA-256, source commit and host version in a separate report. Five positive and three negative cases are packaged for the chosen distribution.

- `--kind local` uses [installed-worker cases](reviewer-cases-local.json). The first positive case discovers owner-provisioned aliases, binds one connection once, and then reads state. It does not expose the generic remote protocol's reviewer tool or grant human authority
- `--kind submission` uses [hosted cases](reviewer-cases-hosted.json). The authenticated server mapping selects the project, so these cases do not require installed-only alias tools. They describe the Python remote protocol; a different hosted runtime must validate and adapt the cases to its actual catalog before submission
- `--kind review-draft` uses the distinct [Sites upload cases](../openai-sites/reviewer-cases.json), matched to the actual Sites catalog and its server-issued worker sessions. Follow the independent-case and account-handoff instructions below; do not substitute the Python hosted cases
- `--kind source` preserves the distribution case definitions and this guide; it is not an installable or submitted plugin

## Python local/remote synthetic setup

Use disposable data, never customer projects. The authorized operator creates the review contracts through the trusted owner flow before worker testing. An agent must not impersonate the human to prepare successful approvals.

Local: register alias `review-demo` in private `PLUGIN_DATA/projects.json`, pointing to an initialized synthetic project. Start the extracted installed package unbound. Do not use legacy actor, role or arbitrary root overrides.

Hosted: provision an isolated review worker account mapped to its synthetic project. Verify real OAuth/reviewer access separately. No registry setup is expected from a remote model or reviewer.

For P3/P4, provide an unclaimed `export` task with no unmet dependency, a `file_contains` criterion for `name,amount`, and a distinct manual-review criterion. The uploaded bytes are `name,amount\nDemo,5\n`, where `\n` represents a newline. A header match proves containment only. This path must remain awaiting its independent review/human decision; a worker cannot complete those gates.

For P5/N3, prepare a separate synthetic stale task: record exact artifact evidence and owner acceptance through the appropriate trusted flow, then revise its contract or change its registered bytes. Record its actual identifiers and revisions. The tested worker only inspects staleness and records a question; it cannot restore acceptance. A recorded question is not an email, push notification or MCP Events delivery.

For these Python distributions, run P1 through P5, then N1 through N3. Capture actual selected tools, arguments, outputs, errors and native UI behavior. Reset only by creating a new disposable fixture or through an authorized operator flow. Do not erase earlier failures or invent observed results.

## Sites independent-case setup

The Sites profile has its own five positive and three negative cases. Each `initial_state` identifies a fresh disposable `review-p1` through `review-n3` project: contract revision 1, unclaimed `export`, no worker session, claim, artifact, evidence or decisions. Use the real returned `project_key`. If an alias exists, have the authorized owner create a distinct one; never carry state between cases or reset earlier evidence to hide a failure.

P2 opens one worker session and claims only. P3/P4/P5 and N2 each open their own session, claim at the current revision, and explicitly authorize one `export.csv` upload of `name,status\nsample,ready\n` as UTF-8 without a BOM, with actual LF newlines including the final one. Reuse that case's returned `worker_id`; opening another worker against an existing claim can cause `LEASE_CONFLICT`. P4 reads and checks the revision it just uploaded, so it needs no earlier case to prepare bytes.

P5 is a three-connection-stage scenario. Give its worker prompt first, then its exact-byte review prompt only to a different, already authorized reviewer account, then its final request prompt back to the original worker connection with the same `worker_id`. The top-level prompt embeds the stages because draft packaging preserves that prompt. The owner must separately confirm any persistent reviewer grant. An unavailable reviewer connection is a blocker; never invent credentials, elevate the worker or ask a reviewer account to run worker setup. The endpoint is `checks_passed` with one owner-decision request and no human acceptance.

N1's model-facing outcome is no acceptance, no owner impersonation or ledger change, and an explanation of the authenticated owner-browser decision flow. A refusal without trying an unavailable tool is valid. The exact JSON-RPC `-32602` / `Unknown tool` check for an explicit `rumbo_decide` dispatch is a separate protocol assertion, not a model tool-selection requirement. N2 checks rejection of worker self-review; N3 has an explicit owner-browser revision between opening the worker session and attempting the stale claim. For N2/N3, safe refusal before dispatch is valid; the harness separately exercises the actual `FORBIDDEN`/`STALE_CONTRACT` rejection paths. Record the owner setup separately from worker actions.

See the [hosted walkthrough runbook](HOSTED-WALKTHROUGH.md) for exact contract, bytes, role handoffs, retries and evidence capture. Its linked synthetic film does not establish managed authentication or native-host behavior.

## Automated coverage and its limits

`tests/test_review_cases.py` checks case selection in the built ZIP, expected tool names against the actual installed/remote catalog, an extracted installed launch, and real dispatcher rejection of reviewer/human impersonation. It checks that case metadata contains scenarios rather than observed-result claims. These tests do not establish natural-language tool selection, actual host panel rendering, OAuth service availability or the presence of a real walkthrough video.

`openai-sites/tests/review-cases.test.mjs` checks all eight Sites cases against the actual catalog, independent initial fixtures, single-session upload preparation, the P5 reviewer read/attribution and return to the original worker, and N1's unchanged ledger separately from the unknown-tool protocol probe. `run-review-cases.mjs` records initial/final state and labels every model outcome `not evaluated`. These local fixture traces do not exercise real account switching, natural-language tool selection or managed OAuth.
