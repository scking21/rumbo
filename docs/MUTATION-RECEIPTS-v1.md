# Opt-in mutation receipts v1 (source candidate)

This new source-only experiment is based on `495e771c04e43ade126584efedf37b2545a02eff`. It is not a recovery of the unavailable October 14 compact-response candidate, a release, a deployment or a host/client update. The wire discriminator is independently versioned as `rumbo.mutation_receipt.v1`; existing component versions and default initialization remain unchanged.

## Optional adoption

Existing project mutations accept an optional `response_mode` with exactly two values:

- Omitted or `"snapshot"`: unchanged full project snapshot and short orientation text.
- `"receipt"`: an incomplete, single-task operation-time observation in `structuredContent`, with an explicit full-state recovery call. Errors keep their existing shape and meaning.

The option is available on Python's claim, submit-artifact, ingest-artifact, run-checks, submit-review and request-decision tools. Sites supports the same set except local submit-artifact, which it never exposed. Installed worker connections still exclude submit-review. `rumbo_state`, `rumbo_read_artifact`, `open_project_board`, listing, binding and opening-worker-session tools reject the option. It grants no scope, role, identity or external permission. `response_mode` stays optional in both catalogs, including the hosted required-field construction. Invalid modes are rejected before mutation. Client argument objects are not modified; transport options are removed from a copy before engine execution.

For example, on an already bound Python connection:

```json
{"name":"rumbo_request_decision","arguments":{"task_id":"export","question":"Please review this revision","response_mode":"receipt"}}
```

On Sites, keep the same authorized `project_key` and, where required, existing server-issued `worker_id` in the ordinary mutation arguments. A reviewer still needs the separately authenticated authorized reviewer account; receipt mode cannot acquire that role.

## Receipt fields and limits

A receipt identifies its operation, project ID, current contract revision and named task. `task_status` is the projected status observed in the operation response, while `human_decision_recorded` is always false: none of these MCP tools records human acceptance. An `accepted` task status can reflect an earlier owner's decision. Successful `run_checks` means the check operation was recorded, not that every check passed. Successful `submit_review` can record fail or uncertain. A request for a decision is never a decision.

`artifact` is null or the current recorded artifact's revision, contract revision and SHA-256. It is recorded identity, not proof of current byte freshness, repository/Git identity, test execution or readiness. An artifact can belong to an older contract, as its explicit contract revision shows. Local files can change after the observation; hosted uploads identify the received bytes and cannot detect edits to their local originals.

`ledger` contains the returned event count and head digest. This anchors the observed ledger; it is neither a durable operation token nor a cache-validity token. Lease expiry and changed/corrupt artifact bytes can change projected status without changing the ledger head. Replacing one task's artifact can invalidate downstream tasks that are not included in the receipt.

The receipt is explicitly `complete: false` and `observation: "operation_response_only"`. It omits the goal, original request, constraints, other tasks, lease actor/expiry, paths and provenance details, individual check results/evidence IDs, reviewer text, requests and all current/historical human decisions. Do not reconstruct these omitted facts from status or assume a stored full snapshot is current because its ledger head matches. Read full state when those facts are required, including before making a readiness judgment or deciding what to do with missing/stale context.

The fixed-field structured receipt does not grow with task or evidence/request history. Its validated fixed-width identifiers/hashes, counters and fixed notice fit below 2 KiB with ordinary compact/default JSON serialization; tests exercise conservative maximum field widths. This is not a universal RPC-envelope, transport, token or host-context bound: JSON-RPC IDs can be arbitrarily long, serializers can add whitespace and hosts add their own data. Full snapshots and error messages retain their existing behavior and can be much larger.

## Recovery and interrupted responses

The receipt's `recovery` is an explicit tool call:

- Python: `{"tool":"rumbo_state","arguments":{}}` on the same project-bound connection.
- Sites: `{"tool":"rumbo_state","arguments":{"project_key":"<the exact original hosted project key>"}}` under the same authorized account. Do not substitute the human-readable project ID/alias or open a new worker to recover state.

Recovery returns the full untruncated existing snapshot, including goal/constraints, all tasks, artifact identities, evidence, requests and current/historical decisions. `rumbo_read_artifact` remains the separate exact-byte read, using the current task and revision arguments from full state. Reads do not mint roles or worker identities.

If a response is lost, the mutation may already have committed. Use the saved project context to read `rumbo_state` before considering a retry. Do not rely on having received the receipt to know how to recover. None of these mutations becomes idempotent: repeating a request or upload can append another event or revision. When disconnected from an installed process, follow the existing registered-project connection rules; a restarted worker does not inherit an old lease.

## Boards and measurement

Boards and all existing clients keep requesting full snapshots by default. They have not opted in. Both existing board renderers reject a compact receipt as an unsupported snapshot, retain the last full view, show a warning, and allow normal full-state refresh; they never substitute its task status for project acceptance. Clients choosing receipt mode must handle the receipt discriminator rather than feed it into a snapshot renderer. Managed-host behavior remains unverified.

This implementation projects the response after the existing engine has already executed and computed full state. It is an output-size experiment, not a CPU, memory, storage or latency optimization. The existing full state is already present only in `structuredContent`; the previous text response was short, not a duplicate full snapshot. Any byte comparison must count the full-state reads needed for context. Fetching full state after every receipt can transfer more data than the default. No provider token count, cost, real-host latency or user benefit is established by source tests.

No engine/storage schema, default workflow, auth scope or external permission changes. Real existing-Claude review, actual installed/managed-host use, browser rendering and publication remain separate gates.
