# Hosted walkthrough recording plan

**Plan only. No video, authenticated hosted run, native-host rendering or managed OAuth proof is supplied by this document.** Use this after an owner authorizes the recording target and test actions. Follow [draft packaging](DRAFT-PACKAGING.md) and [submission requirements](SUBMISSION-REQUIREMENTS.md) for release sequencing; this guide does not resolve private Sites-to-public-directory eligibility.

## 1. Pin the target before recording

- Record the approved Site/MCP URL, deployed version and source commit, recording date, client/host and the review-draft ZIP hash. Verify that the deployed catalog and owner UI match this guide before any write. Stop and reconcile differences rather than describing undeployed behavior as live
- The current owner-private deployment differs from draft PR7. New local/CI fixes are not live-host evidence. Record and verify the actual deployed version/source in the operator evidence before execution
- Use disposable synthetic projects. Keep actual reviewer access instructions in the secure review portal, outside the ZIP and recording. Do not capture passwords, tokens, login codes, unrelated projects or private account details
- Use real authenticated account sessions through the approved hosted connection. Never substitute the local harness's injected identity headers, fixture owner/reviewer subjects or direct storage calls

## 2. Prepare the owner and synthetic contract

In the signed-in **Owner review** browser, copy the displayed **Owner ID** into `decision_owner`; never guess or derive it, and do not substitute the separately displayed **Site user ID**. Expand **Create or revise a contract**, review the entire JSON, choose **Create contract**, then have the actual owner review and **Confirm**. A UI dialog alone is not evidence of a human decision.

Create a fresh project for each source case, using `review-p1` through `review-p5` and `review-n1` through `review-n3`. If an alias already exists, use a distinct owner-approved alias and record it; do not overwrite or reuse prior case state. This is the fixture contract from [`run-review-cases.mjs`](../openai-sites/scripts/run-review-cases.mjs), with only the case alias and copied owner identity substituted:

```json
{
  "project_id": "review-p1",
  "goal": "Verify the exact synthetic export",
  "original_request": "Synthetic QA only. No real project data.",
  "decision_owner": "<copied Owner ID>",
  "constraints": ["No external actions"],
  "tasks": [{
    "id": "export", "title": "Synthetic export", "dependencies": [],
    "acceptance": [
      {"id": "csv", "kind": "file_contains", "value": "name,status\nsample,ready\n"},
      {"id": "quality", "kind": "manual_review", "prompt": "Inspect exact synthetic bytes"}
    ]
  }]
}
```

Copy the real authorized `project_key` returned by the owner flow or `rumbo_list_projects`. The alias is not a tool `project_key`. Open a distinct server-issued `worker_id` per worker/case; a label does not create an identity or reviewer role.

For P5, use a **different, actually signed-in reviewer account** that already has authorized Site access and has no worker history in this project. The reviewer supplies their own displayed **Site user ID**. The owner selects the P5 project, opens **Manage a project's reviewer or worker access**, enters that verified ID, selects **Reviewer**, then uses **Review access grant**. The actual owner must confirm the recipient, role and persistent access to project records/uploaded bytes. Do not grant access as part of preparing this document or impersonate a reviewer with a worker session. Confirm the reviewer can read this project under their own connection before the assertion.

## 3. Keep bytes, revisions and retries exact

The authorized upload is `export.csv`, UTF-8, no BOM, with two LF newlines including the final newline: the JSON string `"name,status\nsample,ready\n"` represents **25 bytes**, not literal backslash characters. Expected SHA-256:

`1154d5cc4194d7614404f110f8f36fc5c3581fa1bd2c710bd3a85b9c0e19d47a`

Record the actual upload authorization before sending those bytes. A digest identifies received bytes; the `file_contains` criterion proves containment only. Neither establishes a Git commit, local-file provenance, executed tests or permission for other actions.

Read `rumbo_state` before a write and after a relevant change. Use the current integer `contract_revision` and returned `artifact.revision`, never a guessed `1`. Fresh fixture projects normally start at contract revision 1 and their first upload at artifact revision 1. Keep the matching digest, maker, evidence IDs and decision history in the evidence record. A board is a snapshot: refresh after changes; an old screenshot or passing receipt does not prove current acceptance.

Use `lease_seconds: 300`. Show the returned worker attribution and `lease.expires_at`; a claim grants coordination ownership only. If recording delays exhaust the lease, reread state and deliberately claim again at the current contract revision before upload, recording the extra call. Do not silently replace a conflicting worker or carry a lease across a contract revision. Response lease status reflects a sampled projection and may expire before it is viewed; a fresh read is needed. See [lease timing](../openai-sites/OPERATIONS.md#runtime-and-authority).

**Lost response or timeout:** stop writes and inspect current state first. Compare the contract/artifact revisions, digest, evidence, requests and decisions before deciding what remains. Do not blindly repeat worker creation, uploads, checks, review assertions, decision requests or owner actions: write tools are not advertised as idempotent. A repeated upload can create another artifact revision even for the same bytes. Preserve drafts, refresh the owner browser after a timeout, and seek operator help if the result cannot be established. Never invent a lost `worker_id`.

### Tool input reference

These are input field sets from [`toolDefinitions()`](../openai-sites/worker/protocol.js), not literal runnable placeholder arguments. `K` means the copied authorized project key; `W` the returned worker ID; `C` the current contract revision; `A` the current artifact revision. Use only these fields, with `C`/`A` as integers.

| Tool | Input fields and values |
| --- | --- |
| `rumbo_list_projects` | `{}` |
| `rumbo_state` | `project_key: K` |
| `rumbo_open_worker` | `project_key: K`, `label: "Synthetic P2"` (use the current case ID) |
| `rumbo_claim_task` | `project_key: K`, `worker_id: W`, `task_id: "export"`, `contract_revision: C`, `lease_seconds: 300` |
| `rumbo_ingest_artifact` | `project_key: K`, `worker_id: W`, `task_id: "export"`, `contract_revision: C`, `filename: "export.csv"`, `content: "name,status\nsample,ready\n"` |
| `rumbo_read_artifact` | `project_key: K`, `task_id: "export"`, `contract_revision: C`, `artifact_revision: A` |
| `rumbo_run_checks` | `project_key: K`, `worker_id: W`, `task_id: "export"`, `contract_revision: C`, `artifact_revision: A` |
| `rumbo_submit_review` | `project_key: K`, `task_id: "export"`, `contract_revision: C`, `artifact_revision: A`, `check_id: "quality"`, `outcome: "pass"`, `detail: <truthful exact-byte review and limits>` |
| `rumbo_request_decision` | `project_key: K`, `worker_id: W`, `task_id: "export"`, `question: "Please inspect the exact bytes and decide"` |
| `open_project_board` | `{}` for authorized project selection, or `project_key: K` |

`rumbo_submit_review` has **no `worker_id`**: the separately authenticated reviewer connection supplies its authority. The deliberately invalid N1 call is `rumbo_decide` with `project_key: K`, `task_id: "export"`, `outcome: "accepted"`; it is absent from the catalog, not an owner tool to enable.

## 4. Record the exact five positive and three negative cases

Use each prompt **verbatim** from [`reviewer-cases.json`](../openai-sites/reviewer-cases.json), in its own fresh project. The chains below reproduce the source harness. Capture each actual call, arguments, result/error and subsequent state; setup reads are allowed and should remain visible. Do not combine P2–P5 into one advancing project and call that eight independent case runs.

| Case | Sequence and pass evidence |
| --- | --- |
| P1 | `rumbo_list_projects` → `rumbo_state`. Only authorized projects appear; exact synthetic goal, contract revision and task state are returned. The selected project's `events_count` and `ledger_head` stay unchanged |
| P2 | `rumbo_open_worker` → `rumbo_claim_task`. Real server-issued session; task becomes `claimed`, with attributed 300-second lease; no reviewer or owner authority |
| P3 | Open worker → claim → `rumbo_ingest_artifact`. Exactly one upload receipt: filename `export.csv`, 25 bytes, digest above, current contract revision and returned artifact revision |
| P4 | Open worker → claim → upload → `rumbo_read_artifact` → `rumbo_run_checks`. Readback matches all 25 bytes; `csv` has a passing deterministic receipt. `quality` still lacks a reviewer assertion: status is `produced`, not accepted |
| P5 | Open worker → claim → upload → checks; switch to the authorized reviewer account, inspect the exact revision, then `rumbo_submit_review`; switch back to the worker for `rumbo_request_decision`. Reviewer attribution is separate; status is `checks_passed`, one owner request is recorded and `decisions` remains empty |
| N1 | Attempt the absent `rumbo_decide`. Expected server response: JSON-RPC `-32602`, `Unknown tool`; no ledger change. If the host blocks an unavailable tool before dispatch, record that as host refusal, not an observed server response |
| N2 | Open worker → claim → upload; attempt `rumbo_submit_review` through the same owner/worker account, without a reviewer grant. Expect tool error `FORBIDDEN`, no reviewer assertion and no ledger change from that attempt |
| N3 | Open worker; save the current revision as `C_old`. In the actual owner browser, paste this project's full fixture contract, enter a revision reason, choose **Revise selected contract**, review the expected revision and have the owner **Confirm**. The harness resaves the same contract body to advance its revision. Read back the newer revision. Attempt `rumbo_claim_task` with `contract_revision: C_old` and `lease_seconds: 300`: expect `STALE_CONTRACT` and no ledger change from the failed claim. Inspect current scope; do not silently claim against the new revision |

### Supplemental UI and owner scene (outside the eight cases)

Only after preserving the unaccepted P5 result, optionally record the owner inspecting **Exact uploaded artifact** and **Evidence and decision history**, entering a real decision reason, choosing **Accept this revision** or **Reject this revision**, and personally confirming the exact contract/artifact revisions. Refresh and capture the saved decision. Do not script a fake owner click or count this as P5, whose endpoint is explicitly unaccepted work.

For a native-panel scene, call `open_project_board` in the actual connected host and capture its render/refresh if available. The owner's **Open read-only board** browser link is a separate HTTP board, not proof of native MCP Apps rendering. Record missing host capabilities or failures as unresolved rather than replacing them with local screenshots.

## 5. Evidence and remaining owner actions

- [ ] Capture target/version/commit and ZIP hash; real account/connection context without credentials; owner confirmation for project creation, reviewer grant and N3 revision
- [ ] Preserve all P1–P5/N1–N3 prompts, tool arguments, structured results/errors, before/after revisions and ledger heads; label deviations and failures honestly
- [ ] Show exact byte count/digest/readback, lease expiry, deterministic receipt, separate reviewer assertion, owner request and unaccepted P5 state; keep any later owner decision separate
- [ ] Save the actual recording and check that its approved review URL is accessible to the intended reviewers; a plan, local trace or screenshot montage is not a completed walkthrough
- [ ] Owner still needs to authorize/verify the deployed target and managed authentication, resolve publisher/domain/private-Sites eligibility and portal checks, arrange real reviewer access, approve outstanding listing/legal/support material, and review the finished candidate before submission. This runbook performs none of those steps

Local rehearsal only, requiring Node 24 and no network/browser/runtime server:

```sh
cd openai-sites
node scripts/run-review-cases.mjs /tmp/rumbo-local-review-traces.json
node --test tests/review-cases.test.mjs
```

These use synthetic handler calls with in-memory SQLite/R2 fixtures. A local 8/8 result checks the prepared scenarios against source; it is not an authenticated managed-host run, model-inference evaluation, native-host test, OAuth validation or submission approval.
