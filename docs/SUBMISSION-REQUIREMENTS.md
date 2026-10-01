# Rumbo public-plugin readiness checklist

Verified 2026-10-01 against current OpenAI plugin documentation after DevDay, not the retired 2023 plugins model. This is an implementation/review checklist, not a claim of deployment, platform validation, submission, approval, or publication.

## 1. Release gates and ownership

**Local development can finish without accounts or deployment. Public review cannot.** Keep separate milestones:

1. **Local review candidate:** implemented engine, transports, native UI resource, skills, fixtures, reproducible tests, deployment instructions, and an honest readiness report.
2. **Production preparation, after authorization:** stable public HTTPS service; real authentication and storage; approved public legal/support pages; account/domain setup; safe reviewer account; real host QA and accessible video.
3. **Upload/scan:** uploads information to OpenAI and creates a draft. This is an external action, distinct from local packaging.
4. **Submit for review:** selected draft plus policy attestations enters review. Hold for the user's final review/approval.
5. **Publish:** separate action after OpenAI approval makes the listing discoverable. Approval alone does not publish it.

Do not relabel localhost, a development tunnel, bearer-token fixtures, example domains, unrun test prompts, or a private Site as production readiness. A release packager should fail closed until real required values are supplied. Build local/demo packages separately from the submission ZIP.

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

In `extensions.com.openai.interface`, require display name and subtitle ≤30 characters each; description ≤4000; developer name ≤80; category matching dashboard. Add `websiteURL`, `supportURL`, `privacyPolicyURL`, `termsOfServiceURL`, `logo`, `composerIcon`. Include referenced assets. Optional starters: ≤3, ≤128 characters each, no plugin @mentions. Icons: square ≥48px, ≤5 MiB; PNG/JPEG/WebP/SVG; raster ≤4096px. ZIP: ≤100 MB compressed, ≤512 MiB expanded, ≤5000 entries, ≤20 path segments; one plugin root; no symlinks, encrypted files, traversal, collisions, or secrets. [Submission validation reference](https://developers.openai.com/plugins/deploy/submission-errors)

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

UI is optional for directory eligibility, but Rumbo's requested panel needs a real MCP Apps resource. A standalone HTTP board is not evidence of host integration. New UI uses shared MCP Apps `ui/*` JSON-RPC over `postMessage`; feature-detect optional `window.openai` extensions. Tools must remain useful without UI. Prefer separate data tools and a board-opening/render tool. [MCP UI](https://developers.openai.com/plugins/build/chatgpt-ui)

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

Sites can host stateless HTTP MCP with managed OAuth and site-scoped authenticated identities; its automatic plugin is private. Existing documentation does not establish a supported public-directory promotion route or exemption from public endpoint/domain-verification/reviewer requirements. A public Site audience alone does not publish a directory listing. Do not create another plugin or replace managed OAuth speculatively. Sites also requires a Workers-compatible deployment; current Python/SQLite local implementation would need an explicit compatible adapter/storage plan. No Site was created or deployed for this research. [Sites](https://learn.chatgpt.com/docs/sites), [Public plugin publishing](https://developers.openai.com/plugins/deploy/submission)

## Current blockers before claiming submission-ready

- Approved production hostname/hosting and deployment have not been established
- End-user OAuth provider/integration and secure human decision path need production verification
- Publisher identity/permissions/project residency and domain ownership challenge remain unverified
- Public product/support/privacy/terms pages need real approved URLs
- Dedicated safe reviewer account, actual in-host evidence, and accessible walkthrough recording remain to be supplied
- User must review the finished candidate before submission; no upload, attestations, submission, or publication was performed
