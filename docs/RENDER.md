# Render-specific recipe: approval-gated

This is a minimal Render Docker-service recipe, not a deployment or a claim that the self-managed Compose bundle runs unchanged on Render. No paid plan, disk, domain, secret or service has been created. `deploy/render.yaml.template` is intentionally incomplete and is not named `render.yaml`; do not submit it until the owner approves the actual fields and costs.

## Render mapping

- Runtime: Docker, using `deploy/Dockerfile`
- HTTP listener: `0.0.0.0:$PORT`, with template `PORT=10000`. The container entrypoint and local health helper both honor this bounded unprivileged port
- Public TLS: Render terminates HTTPS and forwards HTTP internally; do not mount the Compose TLS certificate files or run its separate TLS proxy as if Render were a Compose host. [Web-service ports and TLS](https://render.com/docs/web-services)
- Persistent disk: mount at `/var/lib/rumbo/projects/default`. For the first operator-provisioned project, use that exact root in approved worker/reviewer/owner mappings. Verify runtime UID10001 can write the mounted directory; do not change ownership/permissions without approval
- Configuration/credentials: supply the reviewed JSON and two existing client-secret files through Render's secure file facility at the template paths under `/etc/secrets`. Never put secret contents in source, a Blueprint, build arguments or logs. [Docker services](https://render.com/docs/docker)
- Health check: `/health/ready`. Use the exact approved public hostname in `public_url` and verify Render's health-check Host matches it; the application does not broaden trusted hosts automatically
- Auto deploy: off; one instance only. A persistent disk is runtime-only, single-instance storage and prevents zero-downtime replacement. Build/predeploy commands cannot initialize it. Preserve the separate SQLite-consistent backup plan. [Persistent-disk behavior](https://render.com/docs/disks)

## Required decisions and checks

1. Approve the actual paid compute plan, disk size/current total price, region and Git branch/commit; a disk-backed service is not the free tier
2. Obtain the real assigned service hostname, then set exact `/mcp` and `/owner` URLs, issuer/client/resource settings, callback and subject mappings. Do not guess the onrender.com name before service creation
3. Review how the new runtime disk is provisioned and made writable by the fixed nonroot user. Keep only coordination data in this mount; no home directory or credentials
4. Validate real health, Host/Origin handling, HTTPS cookies, WorkOS or generic OAuth consent/refresh, restart persistence and uploaded-byte backup/restore
5. Confirm the platform's request/connection protections and any additional approved gateway rate controls. The included nginx rate-limit template is for the separate self-managed Compose path; this direct Render recipe does not silently inherit those nginx limits. The app retains its body/time/concurrency/ledger/upload bounds and privacy-safe logs
6. After the owner approves the exact platform-provided public challenge token, store it as a separate existing plain-text file and set `public_challenge_file` to its absolute path. The optional Python route serves only that explicitly configured ≤4KiB regular file at `/.well-known/openai-apps-challenge`; it is absent by default and refuses a configured credential-file path. Verify the exact response over the approved hostname. No token is generated or configured by this template
7. Re-run live-host reviewer cases and the final submission gates before declaring the production endpoint ready

This explicit recipe does not change the generic provider option or weaken token checks to fit a provider. If the chosen Render settings cannot satisfy these gates, stop and resolve that deployment decision rather than silently exposing the backend differently. Blueprint field semantics are documented in [Render's reference](https://render.com/docs/blueprint-spec).
