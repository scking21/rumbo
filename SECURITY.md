# Rumbo 0.3 security and trust model

## Supported deployment boundary

The core targets Python 3.9+ POSIX hosts, tested Linux/Python 3.12. The optional owner portal requires Python 3.10+ maintained Authlib/Requests dependencies. The local project root and service configuration are trusted operator inputs. MCP arguments cannot select a root, actor, role, issuer, URL, arbitrary command, human decision or scope change. The separate `/owner` browser portal supports human-owner operations after a distinct OAuth authorization-code/PKCE login, owner-only audience/scope and server-owned subject mapping. No MCP token or tool can perform these operations.

Workers and reviewers may be untrusted with respect to their evidence claims. Remote tenants are isolated by server-owned OAuth subject → root/actor/role mappings; no project selector is accepted from a client. A reviewer cannot mark the maker's own work as an independent assertion. Attribution alone does not establish real independence.

The local account, filesystem owner, service administrator and program installation remain trusted. They can run Python, impersonate an actor, alter artifacts or replace the database/verifier. Interactive operator confirmation prevents accidental noninteractive use but is not an identity/authentication boundary. Host policy must prevent an agent from using that path as human. The implemented browser owner flow has local fixture-based security tests; real issuer, TLS, cookie and browser verification still gate deployment. OAuth account identity is not proof that a physical human clicked.

## Evidence, not universal enforcement

Only named checks are evaluated. No commands or code from an artifact are executed. Check hashes/receipts do not prove sufficient tests, truthful source quotes, complete action capture, general semantic correctness or authorization. No model service is part of the deterministic referee.

SQLite transactions serialize claims and mutations. Every read replays and verifies the contiguous hash-linked event chain. Artifact bytes, contract revisions, evidence IDs and dependency decision IDs bind acceptance. Changes invalidate green status. Without a preserved independent checkpoint, same-account replacement of the entire ledger is not detectable. No signing, blockchain, external witness or adversarial isolation is claimed.

## HTTP/OAuth profile

Production mode is an OAuth protected resource; the external authorization server owns login, consent, authorization-code+PKCE, client registration and token issuance. Introspection is authenticated using an operator-supplied existing credential from an environment variable; credentials are never generated. In the generic profile, introspection must return `active`, `iss`, `aud`, `sub`, `scope`, and `exp`; Rumbo also checks `nbf` when present. The WorkOS profile instead obtains scope only from a signature-verified JWT and requires independently matching active introspection. Audience must match the configured /mcp resource. For the generic opaque-token profile, token signature checks, if applicable, belong to the trusted authorization server during introspection. The default generic profile does not locally validate JWTs or accept unsigned client claims. The optional WorkOS profile additionally verifies RS256 JWT signatures/claims against fixed issuer JWKS, requires matching active introspection, and verifies the owner ID-token nonce with a separate predefined client/resource. It never treats unsigned scope or default DCR scopes as Rumbo permission.

Only configured HTTPS introspection URLs are used, redirects refused, response capped at 64 KiB, timeout 5 seconds. No client URL influences that request. Host and Origin are checked, duplicate security-sensitive headers rejected, request bodies capped at 1 MiB, thread concurrency at 32, socket timeout at 10 seconds. Shared JSON parsing rejects more than 64 nested containers before decoding, independently of Python's recursion behavior; quoted/escaped brackets do not count as structure. This covers MCP HTTP/stdio, owner action forms and provider responses. Ledger payloads are capped at 16 MiB and 10,000 events per project. Static bearer mode is loopback-only development. Anonymous standalone UI is loopback-only, synthetic-demo-only and rechecks the current demo flag before returning data. Production uses authenticated MCP Apps UI delivery.

Run behind an approved TLS reverse proxy with request/rate limits, access controls, process supervision, backups and restricted filesystem permissions. Preserve the configured public Host, and do not expose the backend directly or trust arbitrary forwarded headers. Real OAuth provider compatibility and live deployment have not been tested here.

## Input and privacy controls

Strict action fields reject identity injection. Unknown MCP tools/resources cannot dispatch arbitrary engine actions or read arbitrary files. Path traversal, symlinks, special files, known secret locations and oversize artifacts are refused. Artifact text is not stored in the ledger, but authorized uploaded text is stored separately under `.rumbo/artifacts/` and may be returned by the exact-revision artifact-read tool. Hashes, relative/display paths, original request, criteria and reviewer/decision text are stored in the ledger. Uploads use generated digest-only filenames, no-follow directory descriptors, existing-byte verification, per-file limits and a project quota; rejected authorization/lease checks create no files. Avoid putting secrets into any of those fields. This path denylist is a risk reduction, not a complete secret detector.

The board uses DOM text rendering for all project content; no HTML injection sink. Embedded messages require the parent source and established origin. Read-only controls cannot write business state. Default server logs omit request bodies, tokens and project text.

## Reporting

Use the repository owner's established security contact or GitHub security reporting if enabled. Do not post credentials or private project records in a public issue. No new reporting endpoint or security account was configured by this release.

## Operational additions

The deployment kit keeps the backend unpublished, drops capabilities and runs nonroot with read-only code/config and explicit persistent project roots. Health responses expose only status. Opt-in request logs exclude raw URI/query/header/body/identity data. Proxy limits and image/runtime configuration require actual deployment validation; they are not a substitute for infrastructure isolation.

Operator backups use SQLite’s online-backup API and verify historical upload digests. They are sensitive, unencrypted and not signed; checksums and hash chains cannot authenticate an archive against an attacker able to replace the entire history. Restore requires a fresh destination and bounds/validates paths, schema, entry counts and sizes. External registered files are not implicitly included.
