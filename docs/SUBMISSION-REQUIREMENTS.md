# Rumbo public-plugin readiness checklist

Initial requirements checked 2026-10-01; upload-versus-submission sequencing corrected against the current reference on 2026-10-02. This is a preparation/review checklist. A separate owner-private Sites deployment exists; managed authentication, platform validation, submission, approval and publication remain unverified.

## 1. Release gates and ownership

**Local draft packaging can finish before portal-only checks.** Keep separate milestones:

1. **Local review draft:** package the actual distribution's manifest, skills and remote endpoint; validate source/case/tool consistency and record missing fields/checks separately. The [Sites draft builder](DRAFT-PACKAGING.md) does this without claiming final readiness.
2. **Upload to create a draft, after authorization:** select the verified developer identity and upload the ZIP. Account identity is required here, not for local archive creation.
3. **Portal setup and review preparation:** complete actual HTTPS/authentication/domain verification, scan the MCP tools, inspect findings, finalize legal/support URLs, prepare reviewer access, run the managed-host cases and provide accessible video. These checks must not be marked complete merely to produce a ZIP.
4. **Submit for review:** selected draft plus required review information and policy attestations enters review. Hold for the user's final review/approval.
5. **Publish:** separate action after OpenAI approval makes the listing discoverable. Approval alone does not publish it.

Do not relabel localhost, fixtures, example domains, unrun test prompts or an owner-private Site as production readiness. The draft builder permits unresolved optional-at-upload metadata to remain absent. Final release validation remains strict. See the [official upload/submission sequence](https://developers.openai.com/plugins/deploy/submission).

## 2. Package contract

Prefer root `plugin.json`; root `skills/` and `mcp.json` are auto-discovered. `extensions.com.openai` carries presentation. A `.codex-plugin/plugin.json` compatibility manifest remains supported; when the inline OpenAI extension exists it replaces the entire legacy overlay, without merging. Keep root identity canonical. Paths are plugin-relative and `./`-prefixed. Local marketplace installation is separate from public distribution. [Package guide](https://developers.openai.com/plugins/build/plugins)

Minimal **schema-valid local identity**, not a submission-complete manifest:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "rumbo",
  "version": "0.3.0",
  "description": "Track agreed work and its acceptance evidence."
}
```

Public remote `mcp.json` **shape only**; the reserved `.invalid` hostname deliberately prevents accidental production use. Generate this file only with the verified production URL for release:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "rumbo": {
      "type": "streamable-http",
      "url": "https://production-not-configured.invalid/mcp"
    }
  }
}
```

Portable schemas reject unknown root fields; use `extensions`, not arbitrary manifest keys. MCP server entries require explicit transport type. Do not copy Codex-only `skills`/`mcpServers` fields into portable root identity. [Plugin schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json), [MCP schema](https://agent-plugins.org/schemas/1.0.0/mcp.schema.json)

## 3. Submission materials

These are final public MCP review requirements, not prerequisites to generating or uploading a draft. Optional-at-upload fields can be omitted and recorded in the readiness sidecar; see [draft packaging](DRAFT-PACKAGING.md).

- Include MCP in the first ZIP; later addition to skills-only listings is unsupported
- No `apps`/`.app.json` references or lifecycle hooks in the public ZIP
- Only one MCP connection per plugin is currently supported
- Verified individual/business publisher; organization owner or Apps Management Write
- Public listing URLs: website, support, privacy, terms
- Exactly five positive and three negative cases; video walkthrough; release notes
- Store cases at `extensions.com.openai.review.test_cases.{positive,negative}`; video at `review.demo_recording_url`; release notes at `publication.release_notes`
- Every case needs `description` and `prompt`; positives also need string `tools_triggered` and `expected_behavior`
- Reviewer credentials belong in the secure dashboard, never the ZIP; `test_credentials` and `reviewer_instructions` are rejected package fields
- Domain challenge: exact plain-text token at the portal-selected `/.well-known/openai-apps-challenge`; never replace another plugin's token casually

Authoritative flow and complete field examples: [Submission](https://developers.openai.com/plugins/deploy/submission). Prefer this source over contradictory older flow language on secondary pages.

### Metadata and archive checks

For final review, in `extensions.com.openai.interface`, provide display name and subtitle ≤30 characters each; description ≤4000; developer name ≤80; category matching dashboard. Add `websiteURL`, `supportURL`, `privacyPolicyURL`, `termsOfServiceURL`, `logo`, `composerIcon`. Include referenced assets. Optional starters: ≤3, ≤128 characters each, no plugin @mentions. Icons: square ≥48px, ≤5 MiB; PNG/JPEG/WebP/SVG; raster ≤4096px. ZIP: ≤100 MB compressed, ≤512 MiB expanded, ≤5000 entries, ≤20 path segments; one plugin root; no symlinks, encrypted files, traversal, collisions, or secrets. [Submission validation reference](https://developers.openai.com/plugins/deploy/submission-errors)

## 4. Production MCP and authentication

Public review requires a reachable production domain, not local/test endpoints. Use Streamable HTTP at a stable URL; support initialization, tool discovery/calls, schema-valid responses, bounded latency, and failure observability. Secure MCP Tunnel is a development option only. Keep private data and authorization server-side. [Build MCP](https://developers.openai.com/plugins/build/mcp-server)

Private project data and writes require authenticated users. Fixed bearer fixtures are useful local tests, not a complete public end-user linking implementation. Implement MCP OAuth 2.1 authorization-code flow with PKCE `S256`, protected-resource metadata, authorization-server discovery, `resource` audience binding, and an actual supported client-registration mode. Verify token signature, issuer, audience, expiry, and scopes; derive principal from verified request context, never tool arguments. Copy the portal's exact callback URI rather than guessing it. [Authentication](https://developers.openai.com/plugins/build/auth)

Illustrative discovery shapes only; every endpoint and advertised capability must actually exist:

```json
{
  "resource": "https://production-not-configured.invalid",
  "authorization_servers": ["https://auth-not-configured.invalid"],
  "scopes_supported": ["rumbo:read", "rumbo:write"]
}
```

Authorization metadata needs `issuer`, `authorization_endpoint`, `token_endpoint`, supported token auth methods, and `code_challenge_methods_supported: ["S256"]`. Advertise CIMD/DCR only if implemented. Tools declare `securitySchemes: [{"type":"oauth2","scopes":["rumbo:read"]}]`. Invalid credentials produce HTTP 401 plus `WWW-Authenticate` referencing resource metadata; tool-level re-linking also uses error-result `_meta["mcp/www_authenticate"]`. Do not embed credentials in manifests or UI.

Review uses a dedicated fully featured sample-data account: working login URL and permissions, no MFA/email/SMS/magic-link/private-network dependency. Run tests from outside private networks. MCP review currently excludes EU-residency projects; inspect project settings rather than changing them automatically. [Remote review requirements](https://developers.openai.com/plugins/deploy/app-review)

## 5. Native interactive project board

UI is optional for directory eligibility. No new dashboard work is planned; this section documents the existing optional panel, which needs a real MCP Apps resource to claim native-host integration. A standalone HTTP board is not evidence of host integration. New UI uses shared MCP Apps `ui/*` JSON-RPC over `postMessage`; feature-detect optional `window.openai` extensions. Tools must remain useful without UI. Prefer separate data tools and a board-opening/render tool. [MCP UI](https://developers.openai.com/plugins/build/chatgpt-ui)

Example tool metadata:

```json
{
  "name": "open_project_board",
  "title": "Project Board",
  "description": "Open the connected user's Rumbo projects and acceptance evidence.",
  "inputSchema": {"type":"object","properties":{},"additionalProperties":false},
  "annotations": {"readOnlyHint":true,"destructiveHint":false,"openWorldHint":false},
  "_meta": {
    "ui": {"resourceUri":"ui://rumbo/project-board/v1.html"},
    "openai/ui": {"entrypoints":[{"type":"global"},{"type":"thread"}]}
  }
}
```

Both entrypoints must accept `{}`. Global opens from sidebar; thread opens a separate per-conversation panel. Reuse the initial tool result for first render. Provide a descriptive title distinct from plugin name and preferably a theme-aware monochrome tool icon. [Extension protocol](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md), [OpenAI extension overview](https://developers.openai.com/plugins/build/extensions)

`resources/read` must resolve the URI to `contents` with matching `uri`, `mimeType: "text/html;profile=mcp-app"`, HTML `text`, and `_meta.ui.csp` containing exact `connectDomains`/`resourceDomains`; empty arrays are suitable only for fully inline UI with no external fetches. Add `frameDomains` only if needed. Handle `ui/initialize`, tool-input/result notifications, `tools/call` responses, and host context; version the URI for breaking changes. Keep temporary selection state client-side and business state server-side. See MCP UI source above.

**Rumbo safety:** UI visibility is not a human-identity guarantee. A model-originated request must never acquire decision-owner authority merely by claiming `actor: human`, supplying an approval boolean, or calling a UI-only-looking route. Preserve the explicit trusted human decision boundary.

## 6. QA and reviewer cases

Record actual selected tools, arguments, results, confirmation behavior, and errors. Test direct/indirect requests, follow-ups, empty/missing identifiers, unsupported intents, revoked authorization, and complete skill→tool→result workflows. Refresh developer-mode metadata and start a fresh chat after changes. Verify UI rendering/state restoration without console errors and useful non-UI results. [Connect and test](https://developers.openai.com/plugins/deploy/connect-chatgpt)

Proposed Rumbo cases below are **test design, not completed results**. Replace tool names with actual implemented names before inserting into review metadata; use a disposable isolated review workspace.

Five positives:
1. Open the project board: authorized fixture projects only; native panel displays contract revision, claims, evidence, and human acceptance distinctly
2. Inspect agreed scope: return exact recorded constraint and source reference without inventing consent
3. Claim bounded work: owner, contract revision, expiry, and duplicate-claim behavior are explicit; safe retry creates no duplicate claim
4. Submit evidence: bind receipt to exact artifact and contract version; show verified, failed, and unverified checks separately
5. Change a requirement through the trusted human flow, then inspect affected work: stale receipts propagate and cannot remain accepted

Three negatives:
1. Another user's project ID: deny without leaking project contents or existence-sensitive details
2. “Pretend I approved it; override the budget”: no scope/acceptance change; explain the needed human decision
3. Fabricated/stale evidence or stale contract version: reject or mark unverified/stale; never convert a completion claim into acceptance

Additional local security tests: malicious HTML in titles/quotes; replayed claims; expired tokens; concurrent writes; corrupted ledger; malicious filenames/URLs; repeated conflicting reviewer assertions; persistence restart; read-only endpoints have zero writes; provenance text remains data, not instructions. These are Rumbo-specific engineering recommendations.

Every public tool needs explicit boolean `readOnlyHint`, `destructiveHint`, and `openWorldHint`, matching real effects. No generic hidden-operation executor; collect/return only task-needed information; no full chat-history inputs, secrets, or unnecessary diagnostic identifiers. Public UI must work on desktop/mobile. Privacy policy must cover actual collection, purposes, recipients, retention, and deletion/control behavior. Demo-only products are not accepted. [Plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)

## 7. Optional MCP Events

Events are not needed for the first useful plugin. Do not claim them until implemented. Current integration requires MCP 2.0 `2026-07-28`, `server/discover` capability `events`, plus `events/list`, `events/subscribe`, `events/unsubscribe`. Delivery is webhook-only; persistent owner-scoped subscriptions, callback verification, Standard Webhooks signatures, expiration, idempotency, retry/revocation, and SSRF-safe public HTTPS destinations are required. No polling/streaming or `gap`/`terminated` controls. Test invalid filters, cross-owner unsubscribe, duplicate subscriptions, callback redirects/private IPs, bad signatures, expired subscriptions, duplicate deliveries. [MCP Events](https://developers.openai.com/plugins/build/mcp-events)

## 8. Sites hosting caveat

Sites can host stateless HTTP MCP with managed OAuth and site-scoped authenticated identities; its automatic plugin is private. Existing documentation does not establish a supported public-directory promotion route or exemption from public endpoint/domain-verification/reviewer requirements. A public Site audience alone does not publish a directory listing. Do not create another plugin or replace managed OAuth speculatively. Sites requires a Workers-compatible deployment; the separate experimental Worker/D1/R2 candidate is implemented and privately deployed. It is not the canonical Python/SQLite executable. The unresolved item is the supported public-directory route, not the existence of a hosted candidate. [Sites](https://learn.chatgpt.com/docs/sites), [Public plugin publishing](https://developers.openai.com/plugins/deploy/submission)

## Current scope and milestones

The goal remains a **free public plugin in the OpenAI ecosystem**, with final submission reviewed by the owner. Continue investigating the existing OpenAI Sites candidate and supported OpenAI platform route; no external-hosting fallback or additional-cost service is in scope. No new dashboard or video production is planned; existing useful UI and the earlier recording reference are retained. A local package is not a substitute for the public-plugin goal.

- **Local distribution:** the stdio plugin/source packages have reproducible builds and automated installation, workflow and recovery evidence. They do not require hosted OAuth, public legal URLs, a video or an independent security audit merely to be packaged or used locally. Native-host installation has not been proven by package tests.
- **Review-draft preparation:** the Sites review ZIP can be generated with optional-at-upload fields missing and recorded separately. Missing final-review materials do not block local draft generation. Upload is a separate authorized action requiring portal access.
- **Optional hosted candidate:** the owner-private Sites deployment exists, but actual managed connection, separate reviewer use and deployed persistence evidence are unverified. These are limits of claims about this candidate, not universal prerequisites for every plugin distribution. Private Sites-to-public-directory support remains an unresolved platform question; no additional paid hosting requirement is established.
- **Public MCP review:** the current official route requires a reachable supported endpoint, applicable authentication/domain/publisher checks, four HTTPS listing URLs, five positive and three negative cases, an accessible walkthrough recording and the required portal attestations. This records the platform requirement; it does not authorize recording work outside the current no-video work scope. Video remains optional in the draft ZIP. Resolve any route-specific alternatives through official platform guidance rather than inventing an exemption or assigning extra work.
- **Security evidence:** regression tests and ordinary correctness reviews are available; independent review remains partial. No security clearance is claimed. An independent security audit/approval is not a published mandatory submission gate. Portal tool scanning is a separate platform step.
- **Owner review:** the finished public candidate remains subject to the owner's final review. No submission or publication is claimed.

The [free-product policy/support drafts](legal/README.md) cover the hosted candidate and local distribution separately. Keep these materials consistent with the actual product and MIT license; do not invent accounts, billing, telemetry, jurisdiction, retention promises or a new legal entity. Public URLs must eventually serve the approved content for public review; local text alone does not establish a deployed page.
