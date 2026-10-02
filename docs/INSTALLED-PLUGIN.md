# Installed local plugin: registry-bound worker

The packaged OpenAI launcher is a worker-only adapter to the canonical Rumbo engine. It starts without a selected project and never uses legacy `RUMBO_PROJECT_ROOT`, `RUMBO_ROLE` or `RUMBO_ACTOR` to obtain a project or authority. The separate trusted CLI retains explicit operator-selected root/actor/role options.

## Owner setup

1. Initialize an approved contract with the documented human-owner CLI. The installed launcher cannot initialize a ledger or create a replacement project.
2. Choose the existing canonical private data directory supplied to this plugin by its host as `PLUGIN_DATA`. It must belong to the current OS user and not be group/other writable (mode `700` recommended). The registry must be an owner-owned nonsymlink regular file without group/other permissions (`600` is written by the registration command).
3. From the source release, the owner registers an approved existing project:

```sh
python3 -m rumbo.registry --plugin-data /absolute/plugin/data add export-project --root /absolute/project
```

Registration validates an already initialized ledger read-only and records the alias, expected project ID, and directory device/inode in `projects.json`. Owner registrations are serialized with a private `.projects.lock` so simultaneous setup commands cannot silently lose an alias. Runtime connections never create that lock or rewrite the registry. Provisioning is an owner-run local command, never an agent MCP tool. File access protections are local safeguards, not proof of a human identity; an unrestricted process under the same OS account is outside this boundary. The standard launcher runs as its own process. Embedding it concurrently with direct core `Engine` or raw SQLite connections in that same process is unsupported; use the separate trusted CLI/server process for those workflows. Installed connections coordinate their own SQLite operations and identity-handle cleanup.

## Agent connection

- `rumbo_list_projects {}` lists only provisioned choices
- `rumbo_connect_project {"alias":"export-project"}` selects one approved alias once per process
- Use existing state, artifact, check and decision-request tools after binding
- Paths, roles, actor overrides, arbitrary new aliases and rebinds are not accepted
- Registry changes or replacement of the pinned project directory invalidate the connection; restart and explicitly select a valid owner-provisioned alias

An absent `projects.json` lists no aliases, so the owner can provision one; a process must restart after registry provisioning or any subsequent registry change. The launcher verifies registry and project identity rather than guessing from its working directory. Missing, uninitialized or invalid ledger state is an error, not an invitation to create new state. Initial validation supports the engine’s default rollback-journal SQLite storage only. A WAL header or existing journal/WAL sidecar is rejected before SQLite opens the database, because even a read-only WAL connection can create sidecars. The owner must finish concurrent writes and explicitly checkpoint/switch journal mode through a trusted maintenance flow before retrying; the launcher never performs that maintenance.

## Per-process identity and leases

Each process gets a distinct worker actor. Concurrent sessions cannot silently share or steal another session's task lease. A lease lasts 30–3600 seconds. Restart creates a new actor; the old lease is not resumed, and the new process must wait for expiry before reclaiming that task. Choose a duration appropriate for the bounded work, and do not bypass conflict checks using the trusted CLI.

## Reviewer and human boundaries

The installed reviewer workflow is incomplete until a separately authorized reviewer connection is available. This worker-only launcher does not expose reviewer submission, configure a reviewer role, resume another actor, or accept/revise contracts. It can inspect exact bytes and explain evidence; reviewer assertions and human decisions require their separate authorized flows. Two model names do not establish separate trusted identities by themselves.

## Registry migration and provenance

The earlier local `0.3.1-local.1` candidate used `projects.json`, but its source archive and exact schema were unavailable during this reconstruction. This implementation preserves the filename, not an unverified compatibility claim. Unknown registry schemas fail closed with setup guidance. The owner must review existing configuration and explicitly re-register approved projects using the recognized schema; never silently overwrite unknown configuration.

New test evidence applies only to this reconstructed source and its exact revision. Earlier Mac/Luna/Sol reports are historical evidence for their own candidate. Unit, stdio, package and browser-fixture checks do not establish actual installed host UI behavior; that remains a separate QA gate.
