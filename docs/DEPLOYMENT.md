# Deployment and public review gates

This document describes the **Python remote deployment profile** and its final release checks. The separate [Sites candidate](../openai-sites/README.md) now has an owner-private deployment, with managed authentication/reviewer access unverified. The historical Python setup plan is not evidence that a Python service, provider account, verified domain/publisher or public-directory submission exists.

Local ZIP creation must not wait on portal-only checks. Use [Sites review-draft packaging](DRAFT-PACKAGING.md) to prepare the actual hosted candidate without marking those checks complete; upload, external verification, final review and publication are separate steps.

The repository now includes an optional [WorkOS Connect adapter](WORKOS.md), [deployment kit and operational checks](OPERATIONS.md), a separate [Render recipe](RENDER.md), and [SQLite-consistent backup/restore](BACKUP.md). Those locally testable components do not substitute for real deployment/provider approval and verification.

## Supported product shape

Rumbo supports **operator-provisioned workspaces**. The service operator assigns an existing OAuth subject to one project root, worker/reviewer role and actor. A separate owner mapping assigns an authenticated owner account to that root. Mapped owners can create/revise their contract, inspect exact artifact bytes and record exact-revision decisions through the separate browser owner portal. Automatic signup, organizations, invitations, workspace billing and multi-project selection are not implemented.

Agents can either register safe files already available in the root or upload explicitly authorized UTF-8 text using `rumbo_ingest_artifact`. Uploads have display-only filenames, 128 KiB/file and 64 MiB/project limits. `rumbo_read_artifact` returns exact current bytes for review. Receipts establish the identity of received or locally read bytes, not a remote checkout, Git commit, honest source provenance or test execution. No filesystem path on a user's laptop/Codex environment is magically shared with the server.

For server-mounted checkouts, arrange a separately authorized sync/mount process outside Rumbo. Do not expose arbitrary filesystem mounts, repositories, URLs or commands to clients. The bounded upload path makes ordinary text artifacts usable without a sync service.

## Runtime prerequisites

- POSIX host, Python 3.9+ (tested Linux/Python 3.12), persistent local filesystem and SQLite
- Restricted service account, trusted application installation, encrypted storage/backups as appropriate
- An approved HTTPS reverse proxy with request/rate limits and process supervision
- A real OAuth 2.1 authorization server supporting authorization-code + PKCE S256, a supported client-registration mode for MCP clients, resource audience binding and authenticated introspection
- Separate registered confidential browser-owner OAuth client with PKCE, exact `https://YOUR_APPROVED_HOST/owner/callback` redirect URI and owner-only audience/scope
- Existing credentials supplied out of band through an approved secret mechanism, never chat, ZIPs, source files or URL query parameters
- Python 3.10+ for optional browser-owner dependencies installed from `requirements-owner.txt`; core/stdio and agent MCP do not require them

Rumbo is the OAuth protected resource, not an authorization server. It publishes protected-resource metadata; the issuer must publish truthful authorization-server discovery. No issuer metadata, login, consent, client registration, TLS setup or callback registration is fabricated by this repository.

## Configuration shape

The following is a **non-runnable shape**, deliberately using reserved `.invalid` names and illustrative filesystem paths. The service rejects those endpoints. Replace with approved, verified values after setup authorization; do not make placeholder hosts public.

```json
{
  "mode": "oauth",
  "public_url": "https://rumbo-not-configured.invalid/mcp",
  "issuer": "https://auth-not-configured.invalid",
  "introspection_url": "https://auth-not-configured.invalid/introspect",
  "introspection_client_id": "existing-resource-client-id",
  "introspection_secret_env": "RUMBO_INTROSPECTION_SECRET",
  "principals": [
    {"subject":"verified-worker-subject", "actor":"maker", "role":"worker", "root":"/srv/rumbo/workspaces/project-a"},
    {"subject":"verified-reviewer-subject", "actor":"reviewer", "role":"reviewer", "root":"/srv/rumbo/workspaces/project-a"}
  ],
  "owner_resource": "https://rumbo-not-configured.invalid/owner",
  "authorization_endpoint": "https://auth-not-configured.invalid/authorize",
  "token_endpoint": "https://auth-not-configured.invalid/token",
  "owner_client_id": "existing-separate-owner-browser-client",
  "owner_client_secret_env": "RUMBO_OWNER_CLIENT_SECRET",
  "owner_principals": [
    {"subject":"verified-owner-subject", "actor":"owner", "root":"/srv/rumbo/workspaces/project-a"}
  ]
}
```

Use only worker/reviewer/viewer roles in `principals`; human roles are rejected. Host-owned mappings cannot be supplied through tools or forms. Incomplete owner setup makes `/owner` fail closed with 503 while MCP remains independent. The owner and MCP resources must share the configured public origin and remain distinct paths/audiences.

After installing optional owner requirements into the approved environment and supplying approved configuration/secret values, run:

```sh
python3 -m rumbo serve --config /path/to/approved-server.json --host 127.0.0.1 --port 8765
```

Terminate TLS at the approved proxy. Preserve the configured public Host header. Do not expose the backend directly, disable TLS verification, bypass certificate warnings or let clients inject trusted proxy headers. This is a single-process local-storage design, not a horizontally scaled cluster. Provision dedicated clean project roots or upload-only empty workspaces rather than home/configuration directories; a filename denylist cannot identify secrets in arbitrary files. Use one supervised process per configuration; owner sessions are intentionally in memory, so a restart signs owners out. Use SQLite-consistent backups while stopped or through its backup API.

## Authentication checks to complete with the actual issuer

Agent access-token introspection must return active=true, exact issuer, /mcp audience, configured subject, finite future exp, permitted nbf and `rumbo:read` (plus `rumbo:write` for mutations). Read-only scope downgrades the principal to viewer. The authorization server validates any token signature during introspection; Rumbo does not invent a JWT verifier.

Owner login uses the separate browser client, code exchange and PKCE verifier, state bound to a secure browser cookie, and owner-only /owner audience + `rumbo:owner`. An agent bearer token is never exchanged/upgraded into an owner session. Owner cookies are Secure, HttpOnly, SameSite=Lax; mutating forms require same-origin CSRF validation and explicit confirmation. Session expiry is bounded by both 30 minutes and token expiry. No refresh token is persisted. OAuth identifies an account; it cannot prove a physical human clicked. Browser-using agents still require user authorization.

Verify real provider scopes/audiences, consent, callback registration, cookie behavior under HTTPS, logout, revoked access, expired tokens and inaccessible project subjects. Local fixture tests are not a substitute for those checks. Inspect [owner portal details](OWNER-PORTAL.md).

## Final-gated Python package configuration

The legacy `--kind submission` Python-profile generator retains these final release requirements. They are not prerequisites for `--kind review-draft` or a statement of the portal upload sequence:

- `mcp_url`, `website_url`, `support_url`, `privacy_url`, `terms_url`, `video_url`: actual approved public HTTPS DNS URLs
- `attestations`: every named gate below is literally true only after its real verification

Required gates: `https_endpoint_verified`, `oauth_verified`, `domain_verified`, `publisher_verified`, `reviewer_account_verified`, `host_qa_verified`, `legal_pages_reviewed`, `video_access_verified`.

These are explicit operator attestations, not network checks performed by the packager. They must not be set merely to get a ZIP. IP literals, localhost, malformed/numeric hostnames and reserved placeholder domains are rejected. The generator never uploads or submits anything. The Sites draft uses a different tool contract; do not point this Python-profile package at the Sites endpoint.

## Python final release checks still to finish

1. Approve and deploy the real HTTPS service and persistent storage with separately configured issuer/owner client
2. Provision safe demo/reviewer subjects and an isolated sample-data workspace; no MFA/email/SMS/magic-link dependence for review access
3. Verify publisher identity, organization permissions, residency eligibility and exact domain-ownership challenge
4. Review actual product/support/privacy/terms pages and approve their public URLs
5. Exercise five positive and three negative cases in a fresh real ChatGPT/Codex host, including owner creation → upload → exact-byte review → evidence → acceptance → changed artifact invalidation
6. Check desktop/mobile layout, keyboard flow, owner login/CSRF, panel global/thread entrypoints and refresh without browser console errors
7. Record a walkthrough on an accessible approved URL using only synthetic data
8. Generate the public review ZIP from verified values; inspect its contents, then obtain final owner review before any upload/submission
9. Upload/scan, submit for review and eventually publish are separate external actions. None is performed by the build script

The source includes tests, security rationale, privacy text and draft case metadata. Listing legal text/identity must be reviewed for the actual operating service; the local policy file alone is not a live-service legal commitment.
