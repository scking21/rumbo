# Operator backup and restore

Rumbo provides bounded, local-only backup and restore commands using the Python
standard library. They are not MCP tools, HTTP endpoints, or owner-portal actions.
Only an operator who can read the project storage and write the output directory
should run them. This does not create a security boundary against other processes
running as the same operating-system user.

## What is included

- A consistent snapshot of `.rumbo/state.sqlite3`, produced with SQLite's online
  backup API, followed by hash-chain verification
- Every immutable uploaded-text blob referenced anywhere in that snapshot's
  history, including superseded revisions and removed tasks
- A versioned manifest containing file sizes, SHA-256 checksums, the verified event
  count and ledger head, and the names of externally registered project files

External registered project files, unreferenced uploaded blobs, configuration,
credentials, and other project files are not copied. A database containing tables,
views, indexes, or triggers other than the expected events table is refused.
Database free pages are compacted out of the snapshot.

The event history and uploaded text themselves may contain confidential or
sensitive material. This is not secret scanning or redaction. The archive is
unencrypted and unsigned. Keep it in operator-controlled storage and apply your
organization's approved encryption and retention process separately. No keys are
generated and no files are sent over the network. Do not put archives or their JSON
summaries in public build artifacts or logs.

Checksums and the ledger hash chain detect corruption and accidental changes;
they do not prove authenticity against someone who can rewrite the archive and
recompute every hash. Restore only backups from a trusted source. Compare the
returned ledger head with an independently retained trusted checkpoint when one
is available.

## Make a backup

The project root and destination's parent directory must already exist. The output
file must not exist, including as a symlink.

```sh
python -m rumbo.backup backup \
  --root /srv/rumbo/projects/example \
  --destination /srv/private-backups/example-2026-10-01.zip
```

The successful command prints a JSON object and exits 0. It includes `project_id`,
`events_count`, `ledger_head`, `uploaded_blobs`, `external_file_references`, a scope
notice, and the output `archive` path. A failure prints an error to stderr and exits
2. Existing output files are never replaced.

Writers may remain active during backup. A dedicated read-only SQLite connection
uses `Connection.backup`, rather than copying the live database, WAL, or journal.
It does not run the backup API inside a write transaction. SQLite retries concurrent
page changes to produce one consistent committed snapshot. The ledger is then
verified and its historical blob references are copied and hashed. This ordering
is safe because successful uploads are committed only after their immutable blobs
have been written, and Rumbo does not delete or replace those blobs. Do not run
manual deletion, retention, or storage-rewrite operations during backup.

Committed WAL-only pages are included. The archive database is standalone and does
not depend on a source WAL, SHM file, or rollback journal. A busy backup has a
30-second progress deadline and fails without publishing a partial archive; retry
at a quieter time if needed. Filesystem failures and operating-system I/O stalls
are outside that progress deadline.

## Restore into a fresh destination

Use an absent or completely empty destination directory whose parent exists.
Restore never merges into a working project and refuses an existing `.rumbo`
directory, other files, or a symlink. Do not restore onto the live service's root.

```sh
python -m rumbo.backup restore \
  --archive /srv/private-backups/example-2026-10-01.zip \
  --destination /srv/rumbo/restored/example

python -m rumbo --root /srv/rumbo/restored/example verify
python -m rumbo --root /srv/rumbo/restored/example state
```

Restore verifies the archive structure, exact entry allowlist, manifest checksums,
SQLite structure, event chain, and exact historical upload set before publishing
anything. It never uses ZIP extraction helpers or archive-supplied permissions.
The successful JSON summary has the same checkpoint fields and a `destination`
path. A new `Engine` instance can immediately open the restored project.

Registered external-file references are restored only as historical metadata.
Their task status can be `stale` until the matching files are separately restored
at their original project-relative paths. Restore those files through your normal
trusted source-control or project backup process, then check state again. A
backup does not renew expired leases or override changed dependencies, contracts,
or human decisions.

After verifying the restored checkpoint, independently restoring needed external
files, and reviewing state, stop the old service before changing its configured
project root to the restored directory. Authentication/provider configuration and
credentials must be provisioned separately through the approved deployment
process. This command does not alter service configuration or start a service.

## Bounds and safe publication

The version-1 format is an uncompressed, single-disk, non-ZIP64 ZIP with no archive
comment. Accepted files are exactly `manifest.json`, `.rumbo/state.sqlite3`, and
`.rumbo/artifacts/<lowercase-sha256>` for each history-referenced upload. Repacking
with compression, extra ZIP metadata, duplicate entries, directory entries,
symlinks, unsupported files, or missing blobs makes an archive unacceptable.

Limits are checked before allocation where applicable:

| Resource | Limit |
| --- | --- |
| Ledger event count | 10,000 |
| Event payloads | 16 MiB total |
| One uploaded-text blob | 128 KiB |
| All referenced uploads | 64 MiB total |
| SQLite snapshot file | 28,065,792 bytes (about 26.77 MiB) |
| Manifest | 4 MiB |
| Complete archive | 107,757,568 bytes (about 102.77 MiB) |
| Archive entries | 10,002 |

The database allowance includes SQLite page/index overhead in addition to ledger
payloads. A source database above this bound is refused even if much of its space
is free. The ZIP central directory is bounded before Python's ZIP parser loads its
entries. Only uncompressed entries are accepted, preventing decompression bombs.

Private staging is created beside the destination, with directories mode `0700`
and files mode `0600`. Backup publishes with an atomic no-clobber hard link.
Restore publishes with a same-filesystem directory rename that cannot replace an
occupied directory. A pre-existing empty destination directory may be replaced
with the private restored directory. This requires POSIX filesystem semantics and
hard-link support; there is no unsafe cross-filesystem/copy fallback.

Ordinary failures clean staging and leave no partial published backup or restored
project. A failure after the final atomic publish, such as a directory `fsync`
error, can leave a complete result while reporting failure: inspect the destination
and verify its checkpoint before retrying. A forced process kill or power loss can
leave private `.rumbo-backup-*` or `.rumbo-restore-*` staging directories beside
the destination. Confirm no backup/restore process is using one before an operator
removes it. Never promote an unfinished staging directory manually.

Symlink leaves, arbitrary symlink ancestors, parent traversal and nonregular files are refused. On macOS only, the root-owned system ancestors `/var` → `/private/var` and `/tmp` → `/private/tmp` are canonicalized when their exact target is a root-owned real directory; all remaining components are still checked without following links. This supports macOS temporary paths without accepting user-controlled aliases. This is designed for trusted,
operator-controlled local paths, not a sandbox against a local adversary replacing
parent directories during an operation. Keep source and destination parents
private to the service operator.

## Python API

```python
from rumbo.backup import backup_project, restore_project

checkpoint = backup_project(project_root, new_archive_path)
restored = restore_project(trusted_archive_path, fresh_project_root)
```

Both functions return JSON-compatible dictionaries and raise `RumboError` on
normal validation/storage failures. They do not take role or actor claims from an
agent, and must not be exposed as remotely callable tools. Use the operator CLI
for deployment runbooks and scheduled jobs only under approved storage, retention,
and access controls.
