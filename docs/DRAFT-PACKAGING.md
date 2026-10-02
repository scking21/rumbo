# Sites review-draft packaging

The official flow is **prepare ZIP → upload to create draft → configure/verify domain and OAuth, scan tools → complete review details → owner-reviewed submission → publication after approval**. Local archive creation cannot depend on checks that only happen after upload. See the [current submission reference](https://developers.openai.com/plugins/deploy/submission) (checked 2026-10-02).

## Prepare the current candidate

```sh
python3 scripts/package_release.py --kind review-draft \
  --mcp-url https://rumbo-review-candidate.aggie-king21.chatgpt.site/mcp \
  --output dist/rumbo-sites-review-draft.zip
```

Python 3.9+, Node.js 24+ and the `jsonschema` developer dependency are required. No network, login, credential creation, portal upload, submission, deployment or public sharing is performed by this command.

The endpoint above belongs to the owner-private Sites candidate. The command validates its URL syntax, not its reachability or managed authentication. The exact deployed source remains separate from the GitHub packaging commit; changes to packaging do not redeploy the runtime.

## What is validated and packaged

- Portable plugin/MCP manifests against the pinned repository schemas; basic listing text limits and packaged icon references
- Only allowlisted plugin assets, LICENSE and two Sites-specific workflow skills; no local launcher, compatibility manifest, Python engine, hooks or credentials
- Actual `toolDefinitions()` from `openai-sites/worker/protocol.js` using Node, rather than the different Python/local catalog
- Positive review-case tool names against that catalog, and skill tool references against available tools
- Actual `openai-sites/reviewer-cases.json` prompts and expected behavior transformed into portable review metadata; negative cases retain their refusal/fallback expectations in `description`
- Deterministic ZIP structure and a SHA-256 checksum, with a separate `.readiness.json` report

The Sites skills use authorized `project_key` values, server-issued `worker_id` sessions and explicit UTF-8 upload authorization. They do not tell the hosted service to inspect a laptop path or use the local-only connection/registration tools. Synthetic handler/browser test results are not authenticated managed-host test runs.

## Missing information remains missing

The draft omits `author` and `interface.developerName` because source authorship is not the selected verified developer/legal publisher. The report lists those publisher fields as pending. It also lists missing website, support, privacy, terms and video fields by their exact manifest names. No country targeting, jurisdiction, operational retention promise, placeholder URL, reviewer credential or legal identity is invented.

Optional approved URLs can be supplied using `--production-config /path/to/draft-config.json` instead of `--mcp-url`. This draft configuration requires only `mcp_url`; it may also contain `website_url`, `support_url`, `privacy_url`, `terms_url`, `video_url`, and an `attestations` object containing any subset of the documented boolean gates. Unknown fields, placeholder URLs and non-boolean attestations are rejected. Omitted gates are false; supplied values are preserved, never promoted automatically. They are operator claims, not checks performed by the packager. Never include credentials or private reviewer sign-in instructions in this configuration or package.

All four listing URLs and the video are required for MCP review, but optional in the upload ZIP where the schema permits. Partial test lists are accepted at upload; initial MCP review requires five positive and three negative cases, run with the real test account. The current source supplies all eight scenarios, but their inclusion does not claim those managed runs have occurred. Reviewer access details belong in the secure portal, outside the archive.

## Readiness is separate

The sidecar is an evidence/readiness note for the owner, not a plugin manifest and not something to upload with the ZIP. Its status is always `review-draft-not-submission-ready`. It records the archive hash, relevant source hashes, actual tool names, explicit operator attestations, unresolved fields and portal steps the command did not perform.

A verified portal developer identity is required to upload, not to generate this local ZIP. Upload validation may reveal additional requirements. Required setup errors, actual domain/OAuth checks, tool scans/findings, approved legal/support copy, test-account access, managed-host cases, video and the owner's final review still need completion before submission. The directory selects the public publisher from the verified developer identity. A successful upload would not itself establish submission readiness or approval.

The existing `--kind submission` / `build_submission` remains a final-gated **Python remote-profile** generator requiring every original external verification gate. It intentionally cannot be used as evidence that a Sites draft is ready; its tools/cases differ. Preparing the Sites draft does not set those gates, submit anything or grant authority for a later upload.
