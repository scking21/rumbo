# Distribution-specific reviewer cases

These files describe expected behavior, not observed results or completed host tests. Keep actual results, screenshots, package SHA-256, source commit and host version in a separate report. Five positive and three negative cases are packaged for the chosen distribution.

- `--kind local` uses [installed-worker cases](reviewer-cases-local.json). The first positive case discovers owner-provisioned aliases, binds one connection once, and then reads state. It does not expose the generic remote protocol's reviewer tool or grant human authority
- `--kind submission` uses [hosted cases](reviewer-cases-hosted.json). The authenticated server mapping selects the project, so these cases do not require installed-only alias tools. They describe the Python remote protocol; a different hosted runtime must validate and adapt the cases to its actual catalog before submission
- `--kind source` preserves both case definitions and this guide; it is not an installable or submitted plugin

## Synthetic setup

Use disposable data, never customer projects. The authorized operator creates the review contracts through the trusted owner flow before worker testing. An agent must not impersonate the human to prepare successful approvals.

Local: register alias `review-demo` in private `PLUGIN_DATA/projects.json`, pointing to an initialized synthetic project. Start the extracted installed package unbound. Do not use legacy actor, role or arbitrary root overrides.

Hosted: provision an isolated review worker account mapped to its synthetic project. Verify real OAuth/reviewer access separately. No registry setup is expected from a remote model or reviewer.

For P3/P4, provide an unclaimed `export` task with no unmet dependency, a `file_contains` criterion for `name,amount`, and a distinct manual-review criterion. The uploaded bytes are `name,amount\nDemo,5\n`, where `\n` represents a newline. A header match proves containment only. This path must remain awaiting its independent review/human decision; a worker cannot complete those gates.

For P5/N3, prepare a separate synthetic stale task: record exact artifact evidence and owner acceptance through the appropriate trusted flow, then revise its contract or change its registered bytes. Record its actual identifiers and revisions. The tested worker only inspects staleness and records a question; it cannot restore acceptance. A recorded question is not an email, push notification or MCP Events delivery.

Run P1 through P5, then N1 through N3. Capture actual selected tools, arguments, outputs, errors and native UI behavior. Reset only by creating a new disposable fixture or through an authorized operator flow. Do not erase earlier failures or invent observed results.

## Automated coverage and its limits

`tests/test_review_cases.py` checks case selection in the built ZIP, expected tool names against the actual installed/remote catalog, an extracted installed launch, and real dispatcher rejection of reviewer/human impersonation. It checks that case metadata contains scenarios rather than observed-result claims. These tests do not establish natural-language tool selection, actual host panel rendering, OAuth service availability or the presence of a real walkthrough video.
