# Rumbo 0.3.7 local plugin review candidate

The OpenAI adapter is versioned independently at 0.3.7; the canonical shared engine remains 0.3.5. This ZIP is for local review and testing, not public-directory submission. It contains the portable Agent Plugins 1.0 manifest, a stdio MCP server, workflow skills and an inline MCP Apps board. Current public review requires an authenticated public HTTPS MCP endpoint; none is configured or claimed here.

Python 3.9+ on Linux/macOS is required. The installed launcher starts unbound. The human operator first initializes the approved project through the trusted source-release CLI, then registers an alias using `python3 -m rumbo.registry --plugin-data /absolute/plugin/data add project-alias --root /absolute/project`. The host supplies that same private directory as `PLUGIN_DATA`; aliases live in `projects.json`. The agent calls `rumbo_list_projects`, then `rumbo_connect_project` with only the approved alias. It cannot supply paths or roles or reconnect within that process.

Each installed process gets a unique worker identity. Its task leases last 30–3600 seconds; a restart does not inherit an old process's lease and must wait for expiry before reclaiming. Legacy RUMBO_PROJECT_ROOT, RUMBO_ROLE and RUMBO_ACTOR variables are ignored. The separate trusted CLI remains available for operator-configured workflows.

Installed reviewer workflow is incomplete until a separately authorized reviewer connection is implemented/configured outside this worker-only launcher. This package does not offer reviewer impersonation, lease resumption or human-authority tools. Existing registry schemas are not assumed compatible; unknown configuration fails closed and requires explicit owner review and re-registration.

A root mcp.json client must support the portable ${PLUGIN_ROOT} variable. Actual installation and UI rendering in ChatGPT/Codex remain separate QA gates; protocol and bridge fixtures are not a host certification.

The source release includes test commands, a deterministic synthetic demo, deployment configuration, security/privacy documentation, and a guarded public-package generator. No accounts, tokens or reviewer passwords are included.

## Codex-local commitments (adapter 0.3.7 candidate)

The local package adds `skills/commitments/SKILL.md` and
`scripts/commitments.py`. This explicit workflow provides `init`, `validate`,
`check` and `show`, each requiring an authorized `--record` path. It packages
the exact canonical `rumbo/scripts/record.py` bytes at build time as
`scripts/_commitments_record.py`; no independently maintained parser fork is
introduced. Build the local ZIP before running the wrapper; a missing or symlinked bundled runtime fails closed. The wrapper does not search ancestor directories for another runtime.

Use Python 3.9+ and an absolute helper path. `--quote -` accepts exact words on
stdin without shell interpolation. The adapter deliberately exposes no Claude
hooks, private transcript option, automatic stop gate, model call, or additional
MCP permission. Its arithmetic/source checks are not proof of user-message
provenance or complete natural-language understanding. Hosted and Sites packages
exclude this local-only skill and helper. Existing worker/reviewer boundaries
remain unchanged. Local package tests do not verify installation, discovery or
a live session in Codex. Retain the previous reviewed package for rollback; do
not overwrite active installed files or user records during activation.
