# Rumbo local plugin review candidate

This ZIP is for local review and testing, not public-directory submission. It contains the portable Agent Plugins 1.0 manifest, a stdio MCP server, workflow skills and an inline MCP Apps board. Current public review requires an authenticated public HTTPS MCP endpoint; none is configured or claimed here.

Python 3.9+ on Linux/macOS is required. Before launching this local plugin, the host must set RUMBO_PROJECT_ROOT to an existing approved project root, optionally RUMBO_ACTOR and RUMBO_ROLE (worker/reviewer/viewer). Initialize its contract through the trusted operator CLI from the source release. The launcher refuses to guess the project and never exposes human-authority tools.

A root mcp.json client must support the portable ${PLUGIN_ROOT} variable. Actual installation and UI rendering in ChatGPT/Codex remain separate QA gates; protocol and bridge fixtures are not a host certification.

The source release includes test commands, a deterministic synthetic demo, deployment configuration, security/privacy documentation, and a guarded public-package generator. No accounts, tokens or reviewer passwords are included.
