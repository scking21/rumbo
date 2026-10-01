# Deployment kit and operator runbook

The deployment kit is prepared code/configuration, not a running service. No paid host, public endpoint, DNS record, account, persistent credential, TLS certificate or platform grant has been created. Real setup still needs the owner's explicit approvals. Use the actual approved hostname and existing credentials; do not invent them to make a package validate.

The two-container Compose setup is provider-neutral/self-managed. For Render, use the separate [Render recipe](RENDER.md); managed ingress, port/disk mapping and additional edge controls differ.

## Files and boundaries

- `deploy/Dockerfile`: Python 3.12 image with optional owner/AuthKit dependencies, UID/GID 10001, no baked credentials
- `deploy/compose.yml`: read-only app/proxy filesystems, capability drops, no-new-privileges, bounded processes/memory/CPU, persistent project bind mount and separate read-only config/TLS/challenge mounts
- `deploy/nginx.conf.template` and `render.py`: explicit approved-host rendering, TLS 1.2/1.3, fixed upstream Host, request/connection/body/time limits, private health routes
- `deploy/entrypoint.py`: requires OAuth mode and safe logging; reads only explicitly named existing secret-file references, refuses ambiguous env+file sources and symlink/special/oversize inputs
- `deploy/healthcheck.py`: status-only local readiness with the configured Host; it never sends auth data or probes the issuer
- `deploy/ci_smoke.py`: isolated CI image/start/restart/backup/restore/proxy-syntax smoke using synthetic data and one-day fixture TLS material, no public ports or provider access

Image tags are official vendor sources but are not immutable deployment locks. After authorized infrastructure selection, review and pin exact base-image digests before production. No Docker or nginx binary was available in the cloud development workspace; local source/behavior checks are separate from the included CI container smoke. Check the exact-commit CI result before claiming the kit executed successfully.

## Preflight requiring real operator decisions

1. Approve the host/provider, costs, persistent disk/backup policy, public hostname, DNS and TLS management
2. Approve/configure the real OAuth provider, separate MCP and owner clients/resources, callback and scopes; validate the optional WorkOS profile against [its exact requirements](WORKOS.md)
3. Provision dedicated project directories on persistent storage. They must be writable by UID/GID 10001 and inaccessible to unrelated host users. Never mount a home directory or credential/configuration tree as a project. Do not make production roots world-writable
4. Map each verified subject to its approved project/actor/role. `principals` allows worker/reviewer/viewer only; `owner_principals` is a separate owner mapping. No automatic signup or multi-project selector is implied
5. Fill the configuration template with actual approved values and `log_requests: true`. Keep `introspection_secret_env: "RUMBO_INTROSPECTION_SECRET"` and `owner_client_secret_env: "RUMBO_OWNER_CLIENT_SECRET"` when using the supplied Compose secret-file wiring
6. Provide existing MCP and owner secret files outside the build context, readable only in the approved secret-management arrangement. Provide existing valid TLS `fullchain.pem` and `privkey.pem`, readable by proxy UID101. Do not change file/network/security permissions automatically just to make startup pass
7. Render the proxy using only the approved public DNS name:

```sh
python3 deploy/render.py --hostname "$APPROVED_PUBLIC_HOSTNAME" --output /path/to/new-reviewed-nginx.conf
```

The renderer refuses placeholder/local/malformed names and refuses overwrite. It does not change DNS or start services. TLS is not generated or configured by this command. HSTS is enabled in the production template; review that commitment for the chosen hostname before deployment.

## Mount/settings contract

Compose requires explicit existing paths through these variables; the values are filenames/directories, never credential contents:

- `RUMBO_CONFIG_FILE`: reviewed JSON configuration file
- `RUMBO_PROJECTS_DIR`: persistent host directory containing provisioned project roots
- `RUMBO_NGINX_CONFIG`: newly rendered and reviewed nginx configuration
- `RUMBO_TLS_DIR`: existing approved certificate/key directory
- `RUMBO_CHALLENGE_DIR`: directory for the exact platform-requested domain challenge, if provided
- `RUMBO_MCP_SECRET_FILE`, `RUMBO_OWNER_SECRET_FILE`: existing approved client-secret files

The app sees projects only under `/var/lib/rumbo/projects`. The backend has no published host port. The proxy publishes HTTPS 443 and uses a separate private backend network; provider egress is available only through the configured container network. Add infrastructure-level egress restrictions after approval if required by the operating environment.

Review `docker compose -f deploy/compose.yml config` after supplying approved path variables. Starting it (`up --build -d`) creates services, mounts secrets and exposes HTTPS; **that is a separate authorized deployment action, not something the local build performed**.

## Logging and health

Application logging is opt-in and emits only an event label, bounded method category, route category, status and duration. It excludes raw paths/queries, IP addresses, user/project identifiers, request/response bodies, authorization codes, cookies, tokens and secrets. The proxy disables request logs and discards its raw request-bearing error log; use safe app health/status metrics instead of enabling debug logging. Proxy IP counters are transient in-memory rate-limit state.

- `/health/live`: process responder status only
- `/health/ready`: local configured secrets/dependencies and ledger integrity; returns only `ok` or `unavailable`

The proxy denies external `/health/` access. For a managed-ingress service, an optional `public_challenge_file` can serve only the separately approved plain-text domain-proof token at its fixed well-known path; it is absent by default, bounded to4KiB and never populated automatically. Readiness never contacts the identity provider and does not certify issuer availability, DNS/TLS, disk capacity, permission sufficiency, host integration or semantic project correctness. Monitor those separately without logging sensitive data. A failed project ledger makes readiness fail closed; investigate/restore rather than rewriting history.

The starter proxy limits average per-IP traffic to 5 requests/second (burst10), total service traffic to30/second (burst20), owner login to6/minute (burst3), and simultaneous service connections to32. Request bodies are limited to1MiB; headers/body timeouts10seconds, upstream connect5seconds, upstream read30seconds. These are conservative starting limits that require capacity/host testing, not a scalability promise. [nginx request limiting](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html), [proxy behavior](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)

## Backups, restart and recovery

Use the operator-only [backup/restore module](BACKUP.md). It invokes SQLite's online-backup API and copies every historical uploaded digest with checksums. Backups are sensitive and unencrypted; no automatic schedule, key generation, external upload or retention policy is configured. Store them outside source/build directories under the approved encryption/access/retention system.

Restore into a new absent/empty directory, inspect its history/upload checks, then deliberately switch the operator mapping or storage mount only after approval. External registered project files are not backed up automatically and may be stale until separately restored. Do not overwrite a running workspace. Container restarts preserve the mounted database/uploads but intentionally clear in-memory owner login/session state.

The CI smoke's temporary permissive directory and synthetic secrets/certificate exist only for cross-UID fixture access and are deleted. They are not production recommendations. Real deployment must retain restrictive ownership and genuine credentials/TLS. Docker secret mounts are documented by [Docker Compose](https://docs.docker.com/compose/how-tos/use-secrets/).
