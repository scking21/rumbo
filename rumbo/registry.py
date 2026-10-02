"""Owner-provisioned aliases for the installed worker-only launcher.

This registry is local configuration, not proof of human identity or an OS
sandbox. Its owner must protect the executable, registry, and project together.
Registration validates existing storage read-only; it never initializes a ledger.
"""
import argparse
from contextlib import closing, contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import time
import threading
import weakref

from .core import (ACTION_FIELDS, Engine, MAX_EVENTS, MAX_LEDGER_BYTES, RumboError,
                   fail, fields, identifier, integer, validate_contract)
from .protocol import safe_json

REGISTRY_NAME = 'projects.json'
MAX_REGISTRY_BYTES = 128 * 1024
MAX_PROJECTS = 100
REGISTRY_GUIDANCE = ('Unsupported or invalid projects.json. The owner must preserve the old file, '
                     'review/migrate its aliases, and re-register initialized projects with '
                     'python -m rumbo.registry; no configuration was overwritten.')


# Installed engines share a process-local SQLite coordination boundary. Closing
# an ordinary descriptor for a SQLite inode can release this process's POSIX
# locks, including a sibling connection's locks. Serialize installed database
# contexts and defer pin closure until every active context has closed SQLite.
# The trusted core CLI runs in a separate process; concurrent direct Engine or
# raw sqlite3 use in the installed launcher's process is unsupported.
_PIN_LOCK = threading.RLock()
_ACTIVE_DATABASES = 0
_PENDING_PIN_CLOSES = []


def _drain_pin_closes():
    if not _ACTIVE_DATABASES:
        while _PENDING_PIN_CLOSES:
            descriptor = _PENDING_PIN_CLOSES.pop()
            try:
                os.close(descriptor)
            except OSError:
                pass


def _release_pins(descriptors):
    with _PIN_LOCK:
        _PENDING_PIN_CLOSES.extend(descriptors)
        descriptors.clear()
        _drain_pin_closes()


def _identity(info):
    return info.st_dev, info.st_ino


def _safe_directory(path, code, private=False):
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or path.resolve() != path:
            fail(code, 'Use an existing canonical directory, without symlink components')
        if private and (info.st_uid != os.getuid() or info.st_mode & 0o022):
            fail(code, 'PLUGIN_DATA must be owned by this OS user and not writable by other users (0700 recommended)')
        return info
    except OSError:
        fail(code, 'Directory is missing or inaccessible')


def _absolute_directory(value, code, private=False):
    try:
        path = Path(value)
    except (TypeError, ValueError):
        fail(code, 'Use an absolute canonical directory')
    if not path.is_absolute() or '..' in path.parts:
        fail(code, 'Use an absolute canonical directory')
    _safe_directory(path, code, private)
    return path


def _validate_document(document):
    try:
        fields(document, {'version', 'projects'})
        if type(document['version']) is not int or document['version'] != 1:
            raise ValueError('Unsupported registry version')
        projects = document['projects']
        if not isinstance(projects, dict) or len(projects) > MAX_PROJECTS:
            raise ValueError('Invalid projects')
        for alias, entry in projects.items():
            identifier(alias, 'project alias')
            fields(entry, {'root', 'project_id', 'device', 'inode'})
            identifier(entry['project_id'], 'project id')
            root = entry['root']
            if not isinstance(root, str) or not root or '\x00' in root or len(root) > 4096:
                raise ValueError('Invalid root')
            path = Path(root)
            if not path.is_absolute() or '..' in path.parts or str(path) != root:
                raise ValueError('Invalid root')
            for key in ('device', 'inode'):
                if type(entry[key]) is not int or entry[key] < 0:
                    raise ValueError('Invalid directory identity')
    except (RumboError, TypeError, ValueError, KeyError):
        fail('REGISTRY_INVALID', REGISTRY_GUIDANCE)
    return document


class ProjectRegistry:
    """Read-only process snapshot; any on-disk registry change requires restart."""
    def __init__(self, plugin_data):
        self.directory = _absolute_directory(plugin_data, 'REGISTRY_UNSAFE', private=True)
        self.path = self.directory / REGISTRY_NAME
        self.document, self.identity = self._read()

    def _read(self):
        directory_info = _safe_directory(self.directory, 'REGISTRY_UNSAFE', private=True)
        directory_fd = None
        try:
            directory_fd = os.open(str(self.directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if _identity(os.fstat(directory_fd)) != _identity(directory_info):
                fail('REGISTRY_CHANGED', 'PLUGIN_DATA changed; ask the owner to inspect it and restart this connection')
            try:
                fd = os.open(REGISTRY_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            except FileNotFoundError:
                return dict(version=1, projects={}), (_identity(directory_info), None)
            with os.fdopen(fd, 'rb') as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                    fail('REGISTRY_UNSAFE', 'projects.json must be a private, owner-owned regular file (0600), without symlinks or hard links')
                raw = handle.read(MAX_REGISTRY_BYTES + 1)
                after = os.fstat(handle.fileno())
                if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    fail('REGISTRY_CHANGED', 'Registry changed during reading; restart after owner review')
            if len(raw) > MAX_REGISTRY_BYTES:
                fail('REGISTRY_INVALID', REGISTRY_GUIDANCE)
            try:
                document = _validate_document(safe_json(raw))
            except (ValueError, UnicodeError, RecursionError):
                fail('REGISTRY_INVALID', REGISTRY_GUIDANCE)
            identity = (_identity(directory_info), _identity(info), hashlib.sha256(raw).hexdigest())
            return document, identity
        except OSError:
            fail('REGISTRY_UNSAFE', 'projects.json must be safely readable, private, and not a symlink')
        finally:
            if directory_fd is not None:
                os.close(directory_fd)

    def verify(self):
        try:
            _, identity = self._read()
        except RumboError:
            fail('REGISTRY_CHANGED', 'Registry became unsafe or invalid; ask the owner to inspect it and restart this connection')
        if identity != self.identity:
            fail('REGISTRY_CHANGED', 'Registry changed; restart this connection after the owner reviews the configuration')

    def list_projects(self):
        self.verify()
        return [dict(alias=alias, project_id=entry['project_id']) for alias, entry in sorted(self.document['projects'].items())]

    def resolve(self, alias):
        self.verify()
        identifier(alias, 'project alias')
        entry = self.document['projects'].get(alias)
        if entry is None:
            fail('UNKNOWN_PROJECT', 'Choose an owner-registered alias from rumbo_list_projects')
        return copy.deepcopy(entry)


class ExistingProjectEngine(Engine):
    """Engine adapter for pre-existing storage with pinned filesystem identities.

    It intentionally bypasses Engine.__init__, whose trusted CLI contract creates
    storage. Path checks before each operation detect replacement; they are not
    protection from a hostile same-user process racing filesystem operations.
    """
    def __init__(self, root, actor, expected=None, guard=None, clock=None):
        self._pin_fds = []
        self._pin_finalizer = weakref.finalize(self, _release_pins, self._pin_fds)
        try:
            with _PIN_LOCK:
                self.root = _absolute_directory(root, 'PROJECT_CHANGED')
                self.actor = identifier(actor, 'host actor')
                self.role = 'worker'
                self.clock = clock or time.time
                self.guard = guard
                self.db_path = self.root / '.rumbo' / 'state.sqlite3'
                self._readonly = True
                self._pins = self._identities('PROJECT_UNINITIALIZED')
                self._acquire_pins()
                if expected and self._pins[0] != (expected['device'], expected['inode']):
                    fail('PROJECT_CHANGED', 'Registered project directory was replaced; owner re-registration is required')
                with self._db() as db:
                    self._validate_schema(db)
                    state = self._replay(db)
                    if not state.get('project_id') or not state.get('contract_revision'):
                        fail('PROJECT_UNINITIALIZED', 'The owner must initialize and approve a contract with the trusted operator CLI first')
                    try:
                        contract = {key: state[key] for key in ACTION_FIELDS['create_contract'][0]}
                        contract['tasks'] = [{key: task[key] for key in ('id', 'title', 'dependencies', 'acceptance')} for task in state['tasks']]
                        validate_contract(contract, state['decision_owner'])
                        integer(state['contract_revision'], 'contract_revision')
                    except (RumboError, KeyError, TypeError, ValueError):
                        fail('LEDGER_CORRUPT', 'Existing ledger does not contain a valid initialized contract')
                    if expected and state['project_id'] != expected['project_id']:
                        fail('PROJECT_ID_MISMATCH', 'Ledger project identity differs from its owner-registered alias')
                    self.project_id = state['project_id']
                    self.contract_revision = state['contract_revision']
                self._readonly = False
        except BaseException:
            self.close()
            raise

    def _acquire_pins(self):
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            self._pin_fds.append(os.open(str(self.root), flags | os.O_DIRECTORY))
            self._pin_fds.append(os.open('.rumbo', flags | os.O_DIRECTORY, dir_fd=self._pin_fds[0]))
            self._pin_fds.append(os.open('state.sqlite3', flags, dir_fd=self._pin_fds[1]))
            self.verify()
        except OSError:
            fail('PROJECT_CHANGED', 'Project or ledger changed while acquiring read-only identity pins')

    def close(self):
        """Invalidate this engine; release pins safely after active SQLite work."""
        self._pin_finalizer()

    def _identities(self, code='PROJECT_CHANGED'):
        root = _safe_directory(self.root, code)
        state = _safe_directory(self.root / '.rumbo', code)
        try:
            database = self.db_path.lstat()
            if not stat.S_ISREG(database.st_mode) or database.st_nlink != 1:
                fail(code, 'Existing ledger must be a regular, nonsymlink file without hard links')
        except OSError:
            fail(code, 'Owner-initialized ledger is missing or inaccessible; no storage was created')
        return _identity(root), _identity(state), _identity(database)

    def verify(self):
        if not self._pin_finalizer.alive:
            fail('PROJECT_CHANGED', 'This project connection is closed; start a new installed connection')
        if self.guard:
            self.guard()
        try:
            pinned = tuple(os.fstat(fd) for fd in self._pin_fds)
        except OSError:
            fail('PROJECT_CHANGED', 'A project identity pin is no longer valid')
        if (len(pinned) != 3 or tuple(_identity(info) for info in pinned) != self._pins
                or any(info.st_nlink < 1 for info in pinned[:2]) or pinned[2].st_nlink != 1
                or self._identities() != self._pins):
            fail('PROJECT_CHANGED', 'Project or ledger was replaced; restart after owner inspection and re-registration')

    @staticmethod
    def _validate_schema(db):
        objects = db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        columns = [(r[1], r[2].upper(), r[3], r[5]) for r in db.execute('PRAGMA table_info(events)')]
        if objects != [('table', 'events')] or columns != [('seq', 'INTEGER', 0, 1), ('payload', 'TEXT', 1, 0), ('previous', 'TEXT', 1, 0), ('digest', 'TEXT', 1, 0)]:
            fail('LEDGER_INVALID', 'Existing database is not a supported Rumbo event ledger')
        count, total = db.execute('SELECT COUNT(*), COALESCE(SUM(length(payload)),0) FROM events').fetchone()
        if count > MAX_EVENTS or total > MAX_LEDGER_BYTES:
            fail('LEDGER_LIMIT', 'Existing ledger exceeds supported event or payload limits')
        if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
            fail('LEDGER_CORRUPT', 'Existing ledger failed SQLite integrity validation')

    def _replay(self, db):
        state = super()._replay(db)
        if hasattr(self, 'project_id') and state.get('project_id') != self.project_id:
            fail('PROJECT_ID_MISMATCH', 'Bound ledger project identity changed; owner inspection is required')
        return state

    def _validate_readonly_storage(self):
        # SQLite mode=ro can still create -wal/-shm files for a WAL database.
        # The trusted CLI creates rollback-journal storage, so fail closed on
        # WAL or recovery state rather than mutate storage during validation.
        for suffix in ('-wal', '-shm', '-journal'):
            try:
                self.db_path.with_name(self.db_path.name + suffix).lstat()
            except FileNotFoundError:
                continue
            fail('LEDGER_STORAGE_UNSUPPORTED', 'Read-only validation requires a quiescent rollback-journal ledger; ask the owner to finish active writes and inspect journal storage')
        # Read through the retained pin. Opening and closing a temporary DB
        # descriptor here could discard a sibling SQLite transaction's locks.
        self.verify()
        header = os.pread(self._pin_fds[2], 20, 0)
        if header[:16] == b'SQLite format 3\x00' and header[18:20] != b'\x01\x01':
            fail('LEDGER_STORAGE_UNSUPPORTED', 'Read-only validation does not support WAL storage; the owner must checkpoint and switch the ledger to DELETE journal mode before registering or connecting')

    @contextmanager
    def _db(self):
        global _ACTIVE_DATABASES
        with _PIN_LOCK:
            self.verify()
            if self._readonly:
                self._validate_readonly_storage()
            db = None
            _ACTIVE_DATABASES += 1
            try:
                # mode=rw never creates missing databases; validation uses ro.
                mode = 'ro' if self._readonly else 'rw'
                db = sqlite3.connect(self.db_path.as_uri() + '?mode=' + mode, uri=True, timeout=15)
                db.execute('PRAGMA busy_timeout=15000')
                db.execute('PRAGMA trusted_schema=OFF')
                if self._readonly:
                    db.execute('PRAGMA query_only=ON')
                self.verify()
                with db:
                    yield db
                    self.verify()
            except sqlite3.DatabaseError:
                fail('LEDGER_UNREADABLE', 'Existing ledger could not be read safely; ask its owner to inspect storage')
            except (KeyError, TypeError, ValueError, IndexError, StopIteration, RecursionError):
                fail('LEDGER_CORRUPT', 'Existing ledger contains an invalid event')
            finally:
                try:
                    if db is not None:
                        db.close()
                finally:
                    _ACTIVE_DATABASES -= 1
                    _drain_pin_closes()

    def _artifact_bytes(self, relative):
        self.verify()
        return super()._artifact_bytes(relative)

    def _upload_dir(self, create=False):
        self.verify()
        return super()._upload_dir(create)


@contextmanager
def _registration_lock(plugin_data):
    """Serialize trusted owner setup only; runtime registry reads never lock/write."""
    directory = _absolute_directory(plugin_data, 'REGISTRY_UNSAFE', private=True)
    directory_fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_fd = None
    try:
        lock_fd = os.open('.projects.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory_fd)
        info = os.fstat(lock_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            fail('REGISTRY_UNSAFE', 'Owner registration lock must be a private regular file (0600), without symlinks or hard links')
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if (_identity(os.stat('.projects.lock', dir_fd=directory_fd, follow_symlinks=False)) != _identity(info)
                or _identity(directory.lstat()) != _identity(os.fstat(directory_fd))):
            fail('REGISTRY_CHANGED', 'Owner registration lock or data directory changed; inspect configuration before retrying')
        yield
    except OSError:
        fail('REGISTRY_UNSAFE', 'Could not safely acquire the owner registration lock')
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(directory_fd)


def register_project(plugin_data, alias, root):
    """Trusted owner CLI helper, deliberately never exposed as an MCP tool."""
    identifier(alias, 'project alias')
    with _registration_lock(plugin_data):
        return _register_project_locked(plugin_data, alias, root)


def _register_project_locked(plugin_data, alias, root):
    registry = ProjectRegistry(plugin_data)
    if alias in registry.document['projects']:
        fail('ALIAS_EXISTS', 'Alias already exists; owner must review existing configuration rather than silently replace it')
    if len(registry.document['projects']) >= MAX_PROJECTS:
        fail('REGISTRY_LIMIT', 'At most 100 projects can be registered')
    with closing(ExistingProjectEngine(root, 'registry-validator')) as engine:
        info = engine.root.stat()
        entry = dict(root=str(engine.root), project_id=engine.project_id, device=info.st_dev, inode=info.st_ino)
        document = copy.deepcopy(registry.document)
        document['projects'][alias] = entry
        raw = (json.dumps(document, indent=2, sort_keys=True) + '\n').encode('utf-8')
        if len(raw) > MAX_REGISTRY_BYTES:
            fail('REGISTRY_LIMIT', 'Registry exceeds 128 KiB')
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.projects-', suffix='.tmp', dir=registry.directory)
            with os.fdopen(fd, 'wb') as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            registry.verify()
            engine.verify()
            os.replace(temporary, registry.path)
            temporary = None
            directory_fd = os.open(str(registry.directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary is not None:
                os.unlink(temporary)
        return dict(alias=alias, project_id=engine.project_id, registry=str(registry.path))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Owner-run registration of initialized projects for the installed Rumbo launcher')
    parser.add_argument('--plugin-data', required=True, help='Existing private PLUGIN_DATA directory used by the host')
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add', help='Register an initialized project under a new alias; never initializes its ledger')
    add.add_argument('alias')
    add.add_argument('--root', required=True, help='Absolute canonical directory of the initialized project')
    args = parser.parse_args(argv)
    try:
        result = register_project(args.plugin_data, args.alias, args.root)
        print(json.dumps(result))
        return 0
    except (RumboError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
