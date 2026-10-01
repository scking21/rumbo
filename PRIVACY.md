# Rumbo privacy information

This file describes the local 0.3 review candidate. A public hosted service needs its operator's reviewed policy, legal identity, contact, retention choices and approved URL before launch. This is not a claim that such a service exists.

## Data stored locally

The new engine stores versioned contracts, original request text, constraints, task claims, actor identifiers, timestamps, relative artifact paths, SHA-256 digests, acceptance criteria, reviewer assertions, decision questions and human decisions in the selected project's `.rumbo/state.sqlite3`. It reads registered project files to hash them and run explicitly configured checks without duplicating those files. When you explicitly upload text through `rumbo_ingest_artifact`, it stores the entire received UTF-8 content in `.rumbo/artifacts/` under a content-addressed filename. Uploads are limited to 128 KiB each and 64 MiB per project. `rumbo_read_artifact` returns up to 128 KiB of current artifact text to the authenticated connected host for review. Criteria or free-text comments may themselves contain sensitive text; do not include secrets.

The Claude adapter separately uses `.rumbo/record.json` and reads a host-provided compatible transcript for lexical quote verification. Per-session nudge/block markers live under `RUMBO_STATE_DIR` or the system temporary directory's `rumbo` folder. Neither format silently migrates to the other.

## Network and recipients

The deterministic local core, local CLI, demo and SQLite state have no telemetry and make no network requests. When the HTTP resource server is configured for OAuth, it sends the presented access token to its explicitly configured authorization server's HTTPS introspection endpoint, using an existing operator-supplied introspection credential. It validates the returned identity and scopes and maps them to a server-configured project. No model or analytics service is called by Rumbo.

If you connect an AI host, tool outputs, project text, criteria, summaries and UI data may be processed by that host under its own terms. The existing Claude hooks inject record summaries and Stop reasons into your Claude conversation. The remote MCP deployment operator can access its configured project roots and must supply a policy appropriate to that hosting.

## Owner browser login

The separate owner portal exchanges an authorization code and PKCE verifier with the configured issuer token endpoint, then introspects the returned access token using the configured existing owner-client credential. It sets Secure, HttpOnly, SameSite=Lax login/session cookies. Pending login state lasts at most 10 minutes; sessions last at most 30 minutes and never longer than the verified token expiry. Session/account mappings and CSRF data are held only in process memory. Access tokens, refresh tokens, authorization codes and secrets are not persisted in project state or default logs. Restart/sign-out clears the applicable session; provider-side revocation may take up to the remaining session lifetime to affect an already established owner session.

## Optional WorkOS profile, operations and backups

When explicitly configured, the WorkOS adapter fetches issuer public signing keys and sends presented access tokens to that issuer’s authenticated introspection endpoint. Owner login additionally verifies the returned ID token and its browser-bound nonce. Keys are cached for at most five minutes; active introspection is required for each access-token use. Optional MCP offline_access is a client/provider grant; Rumbo does not store or refresh its refresh tokens. Generic provider behavior remains available.

Opt-in structural request logs contain only route/method categories, status and duration. No query strings, bodies, IP addresses, project text, cookies or token values are logged by that path. Proxy rate-limit counters temporarily process IP addresses in memory while raw proxy request/error logs remain disabled.

Operator backup/restore is now available as an explicit local command. Archives contain the SQLite history and all history-referenced uploaded bytes, with integrity checks; external project files and credentials/configuration are excluded. Archives are sensitive and unencrypted. No automatic backup, external transfer, encryption-key creation, retention schedule or self-service deletion/export is enabled. Operators must choose approved access, encryption and retention for backup copies.

## Retention and control

Rumbo does not automatically delete, send, publish, replicate or back up project state. Local records remain until the operator removes them. Stop the service before deleting the chosen `.rumbo` directory, and preserve any records needed first. Removing it deletes coordination history and every uploaded artifact stored inside it. Registered project files outside `.rumbo` remain unchanged. Remove legacy temporary markers separately if desired. Files copied to hosts, backups or other services follow their retention rules.

Add `.rumbo/` to `.gitignore` before sharing a project. Do not publish live databases, server configuration containing credentials, private transcripts or reviewer account passwords. Release archives exclude live state and credentials; included demos are explicitly synthetic. No accounts, payment information, credentials or reviewer logins were created in preparing this candidate.
