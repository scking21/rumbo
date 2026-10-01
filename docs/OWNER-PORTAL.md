# Browser owner workspace

Rumbo includes a separate, authenticated `/owner` browser workspace. A mapped account owner can create the initial contract, inspect the original request, constraints, acceptance criteria and recorded evidence, read the exact registered text artifact, revise a contract, and accept or reject a specific contract/artifact revision with a reason and an explicit confirmation checkbox.

This is an implemented, locally tested workflow. It is **not** proof of live OAuth-provider compatibility, public deployment, automatic signup, OpenAI submission or publication. Account creation and workspace provisioning remain operator-managed. OAuth authenticates an account; it does not prove physical-human presence. An agent using the owner's browser is still subject to the owner's confirmation policy.

## Install and configure

The engine, stdio transport and MCP service remain standard-library-only. The browser owner flow requires Python 3.10+ (tested 3.12) and the maintained Authlib OAuth client and Requests:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-owner.txt
```

Use the normal `mode: "oauth"` service configuration and add the following fields. These example domains and identities are illustrative, not a deployed service. Replace them with approved real values. Do not put secrets in JSON or commit them.

```json
{
  "owner_resource": "https://rumbo.example.com/owner",
  "issuer": "https://auth.example.com",
  "authorization_endpoint": "https://auth.example.com/authorize",
  "token_endpoint": "https://auth.example.com/token",
  "introspection_url": "https://auth.example.com/introspect",
  "owner_client_id": "operator-registered-owner-client",
  "owner_client_secret_env": "RUMBO_OWNER_OAUTH_SECRET",
  "owner_principals": [
    {
      "subject": "provider-verified-stable-subject",
      "actor": "owner",
      "root": "/srv/rumbo/projects/owner-workspace"
    }
  ]
}
```

The owner resource must be exactly the same HTTPS host as `public_url`, but use `/owner` rather than `/mcp`. All OAuth endpoints must be configured public HTTPS URLs without userinfo, query or fragment; localhost, private literal IPs, `.local` and `.invalid` hosts are rejected. The provider and endpoint configuration are trusted operator inputs, not browser parameters. DNS/network egress restrictions should prevent configured provider hosts resolving to private infrastructure. The backend does not trust arbitrary forwarded headers or ambient Requests proxy/netrc settings.

The operator must already have an appropriate authorization-server client, supply its existing secret using the named environment variable, and arrange the following provider behavior:

- Authorization-code flow, PKCE `S256`, and client authentication `client_secret_basic`
- Registered exact callback `https://YOUR-HOST/owner/callback`
- A dedicated resource audience `https://YOUR-HOST/owner` and dedicated scope `rumbo:owner`
- Authenticated introspection with the owner client's credentials
- Introspection JSON containing `active: true`, the exact configured `iss`, one exact owner audience (string or singleton array), the mapped `sub`, finite future `exp`, and `scope: "rumbo:owner"`; `nbf`, when supplied, must be finite and not in the future
- No combined owner/MCP audience or scope: credentials containing `rumbo:read` or `rumbo:write` cannot authorize the owner portal

The code does not create clients, credentials, accounts, consent grants or persistent provider access. It does not request `offline_access`, refresh a token or persist access/refresh tokens. Configure an owner client suitable for this narrow profile; arbitrary provider defaults, OIDC-only identity tokens and APIs with nonstandard introspection responses are not silently accepted. An optional callback `iss` is checked when present.

`owner_principals` accepts only `subject`, `actor` and `root`. The operator chooses an existing directory and valid host actor. The browser cannot choose its root, actor or role. Contract JSON can omit `decision_owner`; the server assigns the mapped actor. A conflicting supplied owner is rejected. Multiple subjects should not share a root unless that shared access is deliberate. Core rules still require the recorded decision owner for revisions and decisions.

Incomplete owner settings, absent dependencies or missing secret make `/owner` routes return 503. Invalid complete configuration fails startup. These failures do not offer a bearer-token, anonymous or development-mode owner fallback. Owner routes are enabled only by the production OAuth server mode.

## Browser workflow

1. Open `/owner` on the production HTTPS host, then choose **Sign in**
2. Complete the configured provider's normal login and consent
3. If the mapped workspace has no contract, fill the complete contract JSON form and explicitly confirm creation
4. Review the original request, goal, constraints, criteria, artifact metadata, deterministic receipts and reviewer assertions
5. Use **Inspect these exact artifact bytes** to view the current registered UTF-8 text in an escaped, inert page. The server accepts only task ID and exact numeric revisions, revalidates the digest, and caps inline content at 128 KiB; it never accepts an arbitrary file path or URL. Stale or changed bytes fail closed
6. For a decision, set `outcome` to `accepted` or `rejected`, enter a nonempty `reason`, verify the exact contract/artifact revisions, and check the explicit confirmation control. Acceptance requires all current acceptance evidence to pass
7. To change scope, edit the full contract JSON, preserve the project ID, add a nonempty reason and confirm. The expected revision prevents an old form overwriting a newer contract. Previous evidence remains recorded and becomes stale when appropriate
8. **Sign out** revokes the current local browser session

Errors return bounded, generic authentication errors or core validation codes. On an expired/stale form, reopen the workspace and review current state before retrying. There are no destructive owner operations, arbitrary commands, external model calls, embedded active artifacts, or automatic acceptance. The MCP Apps project board stays read-only and has no access to browser session cookies, CSRF tokens or owner OAuth credentials.

## Security and deployment boundary

- Login state and PKCE verifier are in memory for at most 10 minutes, bound to a separate random browser cookie. The state is consumed atomically before code exchange; bad/missing binding, expired state and replay cannot exchange a code
- Successful login creates a new random server-side session and CSRF token and invalidates the existing session presented in that browser. Cookies use `__Host-` names, `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/` and no Domain. Duplicate cookie values and security-sensitive headers are rejected
- Sessions last at most the earlier of 30 minutes and the verified token's expiry. They do not slide or refresh. Logout, expiry and process restart invalidate them. **Provider-side token/account revocation is not rechecked during an existing session**, so revocation can take up to that remaining lifetime to affect an established owner session
- Pending logins and sessions are each capped at 1,024; new sign-ins fail closed when full. Deploy one process, or sticky routing to one process, unless replacing this storage with a correctly isolated shared session service. Restart signs owners out
- Every mutation, including logout, requires the exact configured Origin, a live session and its constant-time-compared CSRF token. Action forms require explicit confirmation. Expiry/logout are rechecked under the session lock before executing a mutation
- Only exact owner routes are accepted. Host is matched to configured HTTPS authority. Form bodies are capped at 256,000 encoded bytes, callback/HTTP paths at 8,192 characters, and provider responses at 64 KiB. Token/introspection HTTP calls use 5-second timeouts and refuse redirects
- All project and artifact content is HTML-escaped; no script, frame or external resource is loaded. Pages set no-store, no-referrer, nosniff and deny-framing policy. Default server logs do not record bodies, authorization codes, cookies or tokens
- A TLS reverse proxy is required. Preserve the configured public Host, prevent direct backend exposure, apply request/rate limits and ensure proxy/provider logging redacts callback query strings, cookies and secrets. Provider endpoints must be operator-approved. Do not change TLS/security settings to make a provider connection work
- The process owner, deployment configuration and mapped filesystem roots remain trusted. The portal is not a sandbox against an administrator or an agent already allowed to alter server configuration, executable code or the local database

## Verification and limits

Run the complete local suite in the virtual environment, including owner-provider fixtures:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Owner HTTP tests use real local HTTP requests and Authlib's real authorization/PKCE/token construction, with an explicitly synthetic external-provider transport. They cover state/browser binding, replay, expiry, session fixation/rotation, scope/audience/subject rejection, CSRF, Host and header validation, token expiry, session/login bounds, provider redirects/oversize/duplicate JSON, actor spoofing, exact-revision decisions and escaped artifact preview. A full `create_server` test exercises the actual owner handler integration and verifies that owner cookies cannot authorize `/mcp`. Without optional dependencies, owner OAuth tests are explicitly skipped; core/MCP tests and the unavailable-route test still run.

Before public release, separately verify the real provider and browser login/consent/cookie round trip over HTTPS, account revocation policy, production proxy restrictions, isolated owner mapping, accessible desktop/mobile rendering, real sample reviewer account and in-host MCP behavior. Local mocked-provider tests do not establish those outcomes.

Protocol reference: [Authlib OAuth HTTP client, including PKCE](https://docs.authlib.org/en/stable/oauth2/client/http/index.html).
