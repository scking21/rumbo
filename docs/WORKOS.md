# Optional WorkOS AuthKit Connect profile

This is a tested adapter profile, not a configured WorkOS account or live integration. `oauth_provider: "generic"` remains the default. Set `oauth_provider: "workos"` only after separately approved WorkOS/client/resource setup. No client, account, secret, consent grant or domain is created by this code.

## Why a distinct profile

WorkOS Connect access tokens are signed JWTs. Their signed scope is authoritative only after signature and claim verification. The documented introspection response supplies active status and token identity but does not supply scope. Rumbo verifies both rather than accepting missing scope or copying unverified token text into the generic verifier. [WorkOS claims](https://workos.com/docs/authkit/connect/token-claims), [introspection reference](https://workos.com/docs/reference/workos-connect/introspection)

The WorkOS profile uses PyJWT with cryptography, fixed RS256, issuer-owned `/oauth2/jwks`, exact issuer/audience/client/user checks, numeric expiry/issued-at/not-before validation, user-consent/token identifiers and bounded key caching. Every access-token use also performs active introspection; returned identity, audience, client, dates and token identifiers must match the signed claims. Unknown algorithms, embedded/remote header keys, mixed audiences, duplicate key IDs, inactive tokens and conflicting claims fail closed. No stale key is accepted after its cache lifetime if refresh fails. [JWT verification](https://workos.com/docs/authkit/mcp), [PyJWT verification API](https://pyjwt.readthedocs.io/en/stable/usage.html)

## Two predefined clients and two resources

Provision these outside Rumbo after the operator approves the actual setup:

- MCP client: configured `introspection_client_id`, exact `/mcp` resource, required `rumbo:read`, optional `rumbo:write`, optional `offline_access`
- Owner browser client: a different `owner_client_id`, exact `/owner` resource on the same public origin, exactly `openid` plus `rumbo:owner`

`offline_access` adds no Rumbo action privilege. A read-only token with that scope remains read-only. Owner tokens cannot carry it or MCP scopes. The owner login remains non-refreshing; Rumbo does not retain refresh tokens or perform refresh grants. A connecting MCP client may manage an explicitly consented refresh grant, and every resulting access token still undergoes complete validation and active introspection. [WorkOS refresh grants](https://workos.com/docs/reference/workos-connect/token#refresh-token-grant)

Both applications must be predefined and correctly assigned scopes. This profile intentionally does not substitute WorkOS DCR/CIMD default scopes for Rumbo permissions. A live ChatGPT connection must support the approved predefined MCP client and request an acceptable scope set. Unexpected `openid`, `profile`, `email` or owner permissions in an MCP access token are not silently accepted; that live-client behavior is an explicit compatibility gate. WorkOS scopes do not automatically enforce the user's role, so Rumbo retains its own subject-to-project/actor/role mapping. [Scope configuration and user permissions](https://workos.com/docs/authkit/connect/token-claims)

## Exact configuration and credential handling

Start from `deploy/server-config.template.json`, which intentionally contains empty, invalid-until-filled fields. No production hostname, client ID or subject is guessed.

The configured issuer must be the exact canonical HTTPS origin without a trailing slash. Endpoints must equal that origin plus `/oauth2/authorize`, `/oauth2/token` and `/oauth2/introspection`; JWKS is fixed to `/oauth2/jwks`. WorkOS resource indicators must exactly match the approved public `/mcp` and `/owner` URLs. No environment-client-ID audience fallback or wildcard is accepted by Rumbo. [Resource indicators](https://workos.com/docs/authkit/mcp)

Existing MCP and owner secrets are referenced by their environment variable names. The container helper can load explicitly referenced, existing mounted secret files without printing them. Introspection and the owner code exchange use client credentials in the form body as documented by WorkOS. Redirects are refused, provider replies are bounded, TLS verification remains enabled, and client data cannot select another issuer/JWKS/introspection destination. [Introspection](https://workos.com/docs/reference/workos-connect/introspection), [token endpoint](https://workos.com/docs/reference/workos-connect/token)

Owner authorization adds a new random nonce alongside the existing state and PKCE challenge. Login requires a signature-verified ID token for the owner client, matching the verified access-token user and browser-bound nonce. The original state/session/CSRF protections remain unchanged. ID tokens cannot substitute for MCP access tokens. [Authorize](https://workos.com/docs/reference/workos-connect/authorize), [ID token claims](https://workos.com/docs/reference/workos-connect/token#id-token)

Install the optional dependencies with Python 3.10+:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-authkit.txt
```

## Verification and remaining gates

Tests generate ephemeral RSA fixture keys in memory, verify real signatures and use synthetic provider responses. They cover invalid signatures/algorithms/claims, active-token mismatch, key refresh failures, distinct scopes, nonce/ID-token binding, and the real local HTTP owner/MCP handler. They do not call WorkOS with real credentials or prove a live ChatGPT grant works.

Before production, verify actual issuer metadata/JWKS, exact registered callback, resources/scopes, predefined-client support in the target host, initial login/consent, access-token expiry, optional MCP refresh, revocation, isolated subject mappings and the reviewer-account flow. Do not relax verification to make a provider connection succeed. See [deployment](DEPLOYMENT.md) and [operations](OPERATIONS.md).
