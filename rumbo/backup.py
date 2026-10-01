"""Bounded local-operator backup/restore; deliberately absent from agent tools.

Archives contain sensitive coordination history and uploaded text. They are not
signed or encrypted. Use only trusted archives and operator-controlled paths.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import struct
import sys
import tempfile
import time
import zipfile

from .core import Engine, RumboError, MAX_EVENTS, MAX_INGEST, MAX_LEDGER_BYTES, MAX_UPLOAD_TOTAL

MAX_DATABASE_BYTES = MAX_LEDGER_BYTES + MAX_EVENTS * 1024 + 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_DATABASE_BYTES + MAX_UPLOAD_TOTAL + MAX_MANIFEST_BYTES + 8 * 1024 * 1024
BACKUP_TIMEOUT_SECONDS = 30
DATABASE = '.rumbo/state.sqlite3'
MANIFEST = 'manifest.json'
BLOB_PREFIX = '.rumbo/artifacts/'
DIGEST = re.compile(r'[a-f0-9]{64}\Z')
NOTICE = ('Sensitive, unencrypted operator backup. Includes coordination history and referenced uploaded text only. '
          'External registered project files and credentials/configuration are excluded; external-file references '
          'may be stale until the matching files are separately restored. Checksums detect corruption, not authenticity.')


def _fail(code, message):
    raise RumboError(code, message)


def _path(value):
    """Reject symlinks in every existing component, without resolving through them."""
    path = Path(os.path.abspath(os.fspath(value)))
    for component in reversed((path,) + tuple(path.parents)):
        try:
            if stat.S_ISLNK(component.lstat().st_mode):
                _fail('PATH_UNSAFE', 'Backup and restore paths must not contain symlinks')
        except FileNotFoundError:
            continue
    return path


@contextmanager
def _regular(path, limit):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            _fail('PATH_UNSAFE', 'Expected a regular file')
        if info.st_size > limit:
            _fail('BACKUP_LIMIT', 'File exceeds the bounded backup size')
        yield handle


def _read(path, limit):
    with _regular(_path(path), limit) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        _fail('BACKUP_LIMIT', 'File exceeds the bounded backup size')
    return data


def _write(path, data):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _sync_directory(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _readonly(path):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', timeout=1, uri=True)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA trusted_schema=OFF')
    return db


def _snapshot(source, target):
    """Dedicated read-only connection: never call backup inside a write transaction."""
    with _regular(source, MAX_DATABASE_BYTES):
        pass
    deadline = time.monotonic() + BACKUP_TIMEOUT_SECONDS
    def progress(status, remaining, total):
        if total * page_size > MAX_DATABASE_BYTES:
            _fail('BACKUP_LIMIT', 'Snapshot database exceeds the backup bound')
        if time.monotonic() > deadline:
            _fail('BACKUP_BUSY', 'Snapshot timed out; retry when the project is less busy')
    _write(target, b'')
    source_db = _readonly(source)
    target_db = sqlite3.connect(str(target))
    try:
        page_size = source_db.execute('PRAGMA page_size').fetchone()[0]
        if source_db.execute('PRAGMA page_count').fetchone()[0] * page_size > MAX_DATABASE_BYTES:
            _fail('BACKUP_LIMIT', 'Source database exceeds the backup bound')
        source_db.backup(target_db, pages=256, progress=progress, sleep=0.01)
        # A restore must not require a source WAL/journal or include deleted-page residue.
        target_db.execute('PRAGMA journal_mode=DELETE')
        target_db.execute('VACUUM')
    finally:
        target_db.close()
        source_db.close()
    if target.stat().st_size > MAX_DATABASE_BYTES:
        _fail('BACKUP_LIMIT', 'Snapshot database exceeds the backup bound')


def _database_info(root):
    """Bound the database before replay; collect references from ALL history."""
    path = root / DATABASE
    with _regular(path, MAX_DATABASE_BYTES):
        pass
    db = _readonly(path)
    try:
        objects = db.execute("SELECT type,name FROM sqlite_master").fetchall()
        if objects != [('table', 'events')]:
            _fail('BACKUP_INVALID', 'Only the Rumbo events table is supported')
        columns = db.execute('PRAGMA table_info(events)').fetchall()
        expected = [(0, 'seq', 'INTEGER', 0, None, 1), (1, 'payload', 'TEXT', 1, None, 0),
                    (2, 'previous', 'TEXT', 1, None, 0), (3, 'digest', 'TEXT', 1, None, 0)]
        if columns != expected:
            _fail('BACKUP_INVALID', 'Unexpected ledger schema')
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            _fail('LEDGER_CORRUPT', 'SQLite integrity check failed')
        count, size = db.execute('SELECT COUNT(*),COALESCE(SUM(length(CAST(payload AS BLOB))),0) FROM events').fetchone()
        if count > MAX_EVENTS or size > MAX_LEDGER_BYTES:
            _fail('BACKUP_LIMIT', 'Ledger exceeds event or payload limits')
        rows = db.execute('SELECT payload FROM events ORDER BY seq').fetchall()
    finally:
        db.close()
    # Engine verifies the canonical hash-linked history; missing external files simply become stale.
    try:
        state = Engine(root, 'backup-operator', 'viewer').snapshot()
        uploads, external = {}, set()
        for (raw,) in rows:
            event = json.loads(raw)
            if event['action'] not in ('ingest_artifact', 'submit_artifact'):
                continue
            artifact = event['data']['artifact']
            if artifact.get('source') == 'uploaded_text':
                digest, size = artifact['sha256'], artifact['size']
                if not isinstance(digest, str) or not DIGEST.fullmatch(digest) or type(size) is not int or not 0 <= size <= MAX_INGEST:
                    _fail('BACKUP_INVALID', 'Invalid uploaded artifact reference')
                if digest in uploads and uploads[digest] != size:
                    _fail('BACKUP_INVALID', 'Conflicting uploaded artifact sizes')
                uploads[digest] = size
            else:
                if not isinstance(artifact['path'], str) or len(artifact['path']) > 512:
                    _fail('BACKUP_INVALID', 'Invalid external artifact reference')
                external.add(artifact['path'])
        if len(uploads) > MAX_EVENTS or sum(uploads.values()) > MAX_UPLOAD_TOTAL:
            _fail('BACKUP_LIMIT', 'Referenced uploads exceed the project limit')
    except (KeyError, TypeError, ValueError, StopIteration, RecursionError):
        _fail('LEDGER_CORRUPT', 'Invalid ledger event data')
    summary = {key: state[key] for key in ('project_id', 'events_count', 'ledger_head')}
    summary.update(uploaded_blobs=len(uploads), external_file_references=sorted(external), notice=NOTICE)
    return summary, uploads


def _record(data):
    return {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail('BACKUP_INVALID', 'Duplicate manifest field')
            result[key] = value
        return result
    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: _fail('BACKUP_INVALID', 'Invalid JSON number'))


def _entry(name, data):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.compress_type = zipfile.ZIP_STORED
    return info, data


def backup_project(root, destination):
    """Return a JSON-compatible summary; publish a new archive without overwriting."""
    staging = None
    try:
        root, destination = _path(root), _path(destination)
        if not root.is_dir() or not destination.parent.is_dir():
            _fail('PATH_INVALID', 'Source root and output parent must already exist')
        if destination.exists():
            _fail('DESTINATION_EXISTS', 'Backup output must not already exist')
        source = _path(root / DATABASE)
        staging = Path(tempfile.mkdtemp(prefix='.rumbo-backup-', dir=str(destination.parent)))
        snapshot_root = staging / 'project'; snapshot_root.mkdir(mode=0o700)
        state_dir = snapshot_root / '.rumbo'; state_dir.mkdir(mode=0o700)
        _snapshot(source, state_dir / 'state.sqlite3')
        summary, uploads = _database_info(snapshot_root)
        files = {}
        archive_path = staging / 'archive.zip'
        _write(archive_path, b'')
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
            data = _read(snapshot_root / DATABASE, MAX_DATABASE_BYTES)
            files[DATABASE] = _record(data)
            archive.writestr(*_entry(DATABASE, data))
            for digest, size in sorted(uploads.items()):
                data = _read(root / BLOB_PREFIX / digest, MAX_INGEST)
                if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                    _fail('ARTIFACT_CORRUPT', 'Uploaded bytes do not match the historical digest')
                name = BLOB_PREFIX + digest
                files[name] = _record(data)
                archive.writestr(*_entry(name, data))
            manifest = dict(format='rumbo-backup', version=1, summary=summary, files=files)
            data = json.dumps(manifest, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
            if len(data) > MAX_MANIFEST_BYTES:
                _fail('BACKUP_LIMIT', 'Manifest exceeds the backup bound')
            archive.writestr(*_entry(MANIFEST, data))
        if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
            _fail('BACKUP_LIMIT', 'Archive exceeds the backup bound')
        with archive_path.open('rb') as handle:
            os.fsync(handle.fileno())
        # A hard link is an atomic no-clobber publication, unlike os.replace.
        os.link(str(archive_path), str(destination), follow_symlinks=False)
        _sync_directory(destination.parent)
        return dict(summary, archive=str(destination))
    except RumboError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError, zipfile.BadZipFile, zipfile.LargeZipFile):
        _fail('BACKUP_FAILED', 'Backup failed safely; verify paths, storage, ledger and uploaded blobs')
    finally:
        if staging is not None:
            shutil.rmtree(staging)


def _preflight_zip(handle):
    """Bound central-directory allocation before ZipFile reads untrusted entries."""
    handle.seek(0, os.SEEK_END)
    length = handle.tell()
    if length < 22 or length > MAX_ARCHIVE_BYTES:
        _fail('BACKUP_LIMIT', 'Archive exceeds the backup bound or is truncated')
    # This format has no archive comment and does not use ZIP64 or multiple disks.
    handle.seek(-22, os.SEEK_END)
    end = handle.read(22)
    signature, disk, central_disk, disk_count, count, central_size, offset, comment = struct.unpack('<4s4H2LH', end)
    if signature != b'PK\x05\x06' or disk or central_disk or disk_count != count or comment:
        _fail('BACKUP_INVALID', 'Unsupported ZIP archive structure')
    if not 2 <= count <= MAX_EVENTS + 2 or central_size > count * 1024 or offset + central_size != length - 22:
        _fail('BACKUP_LIMIT', 'Archive directory exceeds format bounds')
    handle.seek(0)


def _validate_archive(archive):
    entries, total = {}, 0
    for info in archive.infolist():
        name = info.filename
        if name in entries:
            _fail('BACKUP_INVALID', 'Duplicate archive entry')
        allowed = name in (MANIFEST, DATABASE) or (name.startswith(BLOB_PREFIX) and DIGEST.fullmatch(name[len(BLOB_PREFIX):]))
        mode = info.external_attr >> 16
        if not allowed or info.is_dir() or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
            _fail('BACKUP_INVALID', 'Unexpected or unsafe archive entry')
        if info.compress_type != zipfile.ZIP_STORED or info.flag_bits & ~0x800 or info.extra or info.comment:
            _fail('BACKUP_INVALID', 'Only plain, uncompressed backup entries are accepted')
        bound = MAX_MANIFEST_BYTES if name == MANIFEST else MAX_DATABASE_BYTES if name == DATABASE else MAX_INGEST
        if info.file_size > bound or info.compress_size != info.file_size:
            _fail('BACKUP_LIMIT', 'Archive entry exceeds format bounds')
        total += info.file_size
        if total > MAX_DATABASE_BYTES + MAX_UPLOAD_TOTAL + MAX_MANIFEST_BYTES:
            _fail('BACKUP_LIMIT', 'Archive contents exceed format bounds')
        entries[name] = info
    if MANIFEST not in entries or DATABASE not in entries:
        _fail('BACKUP_INVALID', 'Missing manifest or database')
    manifest = _json(archive.read(entries[MANIFEST]))
    if not isinstance(manifest, dict) or set(manifest) != {'format', 'version', 'summary', 'files'} or manifest['format'] != 'rumbo-backup' or type(manifest['version']) is not int or manifest['version'] != 1:
        _fail('BACKUP_INVALID', 'Unsupported backup manifest')
    files = manifest['files']
    if not isinstance(files, dict) or set(files) != set(entries) - {MANIFEST}:
        _fail('BACKUP_INVALID', 'Manifest does not match archive entries')
    upload_total = 0
    for name, record in files.items():
        if not isinstance(record, dict) or set(record) != {'size', 'sha256'}:
            _fail('BACKUP_INVALID', 'Invalid manifest checksum record')
        if type(record['size']) is not int or record['size'] != entries[name].file_size or not isinstance(record['sha256'], str) or not DIGEST.fullmatch(record['sha256']):
            _fail('BACKUP_INVALID', 'Invalid manifest checksum or size')
        if name.startswith(BLOB_PREFIX):
            if record['sha256'] != name[len(BLOB_PREFIX):]:
                _fail('BACKUP_INVALID', 'Uploaded filename does not match its digest')
            upload_total += record['size']
    if upload_total > MAX_UPLOAD_TOTAL:
        _fail('BACKUP_LIMIT', 'Uploaded bytes exceed the project bound')
    return manifest, entries


def restore_project(archive, destination):
    """Validate privately, then atomically publish to an absent or empty directory."""
    staging = None
    try:
        archive, destination = _path(archive), _path(destination)
        if not destination.parent.is_dir():
            _fail('PATH_INVALID', 'Restore parent must already exist')
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            _fail('DESTINATION_EXISTS', 'Restore requires an absent or empty destination')
        with _regular(archive, MAX_ARCHIVE_BYTES) as handle:
            _preflight_zip(handle)
            with zipfile.ZipFile(handle, 'r') as source:
                manifest, entries = _validate_archive(source)
                staging = Path(tempfile.mkdtemp(prefix='.rumbo-restore-', dir=str(destination.parent)))
                project = staging / 'project'; project.mkdir(mode=0o700)
                state_dir = project / '.rumbo'; state_dir.mkdir(mode=0o700)
                if len(entries) > 2:
                    (state_dir / 'artifacts').mkdir(mode=0o700)
                for name, record in manifest['files'].items():
                    data = source.read(entries[name])
                    if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                        _fail('BACKUP_INVALID', 'Archive checksum mismatch')
                    _write(project / name, data)
                summary, uploads = _database_info(project)
                if summary != manifest['summary']:
                    _fail('BACKUP_INVALID', 'Manifest summary does not match verified history')
                expected = {DATABASE} | {BLOB_PREFIX + digest for digest in uploads}
                if set(manifest['files']) != expected:
                    _fail('BACKUP_INVALID', 'Archive does not contain exactly the history-referenced uploads')
                for digest, size in uploads.items():
                    if manifest['files'][BLOB_PREFIX + digest]['size'] != size:
                        _fail('BACKUP_INVALID', 'Uploaded size does not match history')
                if uploads:
                    _sync_directory(state_dir / 'artifacts')
                _sync_directory(state_dir); _sync_directory(project)
                # POSIX rename refuses an occupied directory and does not follow a destination symlink.
                # Recheck for ordinary concurrent changes immediately before publication.
                _path(destination)
                if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
                    _fail('DESTINATION_EXISTS', 'Restore destination is no longer empty')
                os.rename(str(project), str(destination))
                _sync_directory(destination.parent)
        return dict(summary, destination=str(destination))
    except RumboError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError, zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, RuntimeError):
        _fail('BACKUP_INVALID', 'Restore failed safely; use a trusted, complete Rumbo archive and a fresh destination')
    finally:
        if staging is not None:
            shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local operator-only, sensitive Rumbo backup/restore')
    commands = parser.add_subparsers(dest='command', required=True)
    backup = commands.add_parser('backup', help='Create a new unencrypted archive')
    backup.add_argument('--root', required=True)
    backup.add_argument('--destination', required=True)
    restore = commands.add_parser('restore', help='Restore into an absent or empty directory')
    restore.add_argument('--archive', required=True)
    restore.add_argument('--destination', required=True)
    args = parser.parse_args(argv)
    try:
        result = backup_project(args.root, args.destination) if args.command == 'backup' else restore_project(args.archive, args.destination)
    except RumboError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
