"""Installed launcher boundary tests; the trusted CLI remains separately configured."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from rumbo.core import Engine, RumboError
from test_core import contract

ROOT = Path(__file__).resolve().parents[1]


class InstalledTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.data = self.base / 'plugin-data'
        self.data.mkdir(mode=0o700)
        self.project = self.base / 'project'
        self.project.mkdir()
        Engine(self.project, 'owner', 'human').execute('create_contract', contract())
        (self.project / 'export.csv').write_text('name,amount\nAlice,10\n')
        self.now = [1000.0]

    def modules(self):
        for module in ('rumbo.registry', 'rumbo.installed'):
            self.assertIsNotNone(importlib.util.find_spec(module), 'Missing installed registry launcher: ' + module)
        return importlib.import_module('rumbo.registry'), importlib.import_module('rumbo.installed')

    def register(self, alias='sample', root=None):
        registry, _ = self.modules()
        return registry.register_project(self.data, alias, root or self.project)

    def protocol(self):
        _, installed = self.modules()
        return installed.InstalledProtocol(self.data, clock=lambda: self.now[0])

    def call(self, protocol, name, arguments=None):
        response = protocol.dispatch(dict(jsonrpc='2.0', id=1, method='tools/call', params=dict(name=name, arguments=arguments or {})))
        self.assertIn('result', response, response)
        return response['result']

    def bind(self, protocol, alias='sample'):
        result = self.call(protocol, 'rumbo_connect_project', dict(alias=alias))
        self.assertFalse(result.get('isError'), result)
        return result['structuredContent']

    def assertToolError(self, result, code):
        self.assertTrue(result.get('isError'), result)
        self.assertIn(code, result['content'][0]['text'])

    def test_unbound_startup_lists_aliases_without_creating_project_state(self):
        protocol = self.protocol()
        result = self.call(protocol, 'rumbo_list_projects')
        self.assertEqual(result['structuredContent']['projects'], [])
        self.assertToolError(self.call(protocol, 'rumbo_state'), 'PROJECT_UNBOUND')
        self.assertEqual(list(self.data.iterdir()), [])

    def test_owner_registration_records_identity_without_changing_ledger(self):
        db = self.project / '.rumbo/state.sqlite3'
        before = (db.read_bytes(), db.stat().st_mtime_ns, db.stat().st_mode)
        self.register()
        self.assertEqual((db.read_bytes(), db.stat().st_mtime_ns, db.stat().st_mode), before)
        registry_file = self.data / 'projects.json'
        info = json.loads(registry_file.read_text())
        self.assertEqual(info['version'], 1)
        entry = info['projects']['sample']
        self.assertEqual(entry['root'], str(self.project.resolve()))
        self.assertEqual(entry['project_id'], 'sample')
        self.assertEqual((entry['device'], entry['inode']), (self.project.stat().st_dev, self.project.stat().st_ino))
        self.assertEqual(registry_file.stat().st_mode & 0o777, 0o600)
        listed = self.call(self.protocol(), 'rumbo_list_projects')['structuredContent']['projects']
        self.assertEqual(listed, [dict(alias='sample', project_id='sample')])
        self.assertNotIn(str(self.project), json.dumps(listed))

    def test_binding_is_read_only_and_uses_generated_worker_actor(self):
        self.register()
        db = self.project / '.rumbo/state.sqlite3'
        before = (db.read_bytes(), db.stat().st_mtime_ns, db.stat().st_mode)
        protocol = self.protocol()
        bound = self.bind(protocol)
        self.assertEqual(bound['alias'], 'sample')
        self.assertEqual(bound['project_id'], 'sample')
        self.assertEqual(bound['role'], 'worker')
        self.assertRegex(bound['actor'], r'^worker-[0-9a-f]{32}$')
        self.assertEqual((db.read_bytes(), db.stat().st_mtime_ns, db.stat().st_mode), before)
        state = self.call(protocol, 'rumbo_state')['structuredContent']
        self.assertEqual(state['contract_revision'], 1)

    def test_unknown_alias_paths_roles_and_actor_arguments_are_rejected(self):
        self.register()
        protocol = self.protocol()
        for alias in ('unknown', str(self.project), '../project', '.', 'a/b'):
            with self.subTest(alias=alias):
                result = self.call(protocol, 'rumbo_connect_project', dict(alias=alias))
                self.assertTrue(result['isError'])
        for extra in ('root', 'path', 'role', 'actor', 'resume'):
            with self.subTest(extra=extra):
                self.assertToolError(self.call(protocol, 'rumbo_connect_project', dict(alias='sample', **{extra: 'owner'})), 'UNKNOWN_FIELD')
        self.bind(protocol)

    def test_rebinding_even_to_valid_alias_or_same_alias_is_rejected(self):
        second = self.base / 'second'
        second.mkdir()
        Engine(second, 'owner', 'human').execute('create_contract', dict(contract(), project_id='second'))
        self.register()
        self.register('second', second)
        protocol = self.protocol()
        original = self.bind(protocol)
        for alias in ('second', 'sample'):
            self.assertToolError(self.call(protocol, 'rumbo_connect_project', dict(alias=alias)), 'PROJECT_ALREADY_BOUND')
        self.assertEqual(self.call(protocol, 'rumbo_state')['structuredContent']['project_id'], original['project_id'])

    def test_registry_modification_after_startup_and_binding_fails_closed(self):
        self.register()
        unbound = self.protocol()
        bound = self.protocol()
        self.bind(bound)
        path = self.data / 'projects.json'
        document = json.loads(path.read_text())
        document['projects']['sample']['project_id'] = 'retargeted'
        path.write_text(json.dumps(document))
        self.assertToolError(self.call(unbound, 'rumbo_connect_project', dict(alias='sample')), 'REGISTRY_CHANGED')
        self.assertToolError(self.call(bound, 'rumbo_state'), 'REGISTRY_CHANGED')
        self.assertToolError(self.call(bound, 'rumbo_claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60)), 'REGISTRY_CHANGED')
        self.assertEqual(Engine(self.project, 'observer', 'viewer').snapshot()['events_count'], 1)

    def test_registry_replacement_identical_bytes_is_rejected(self):
        self.register()
        protocol = self.protocol()
        self.bind(protocol)
        path = self.data / 'projects.json'
        replacement = self.data / 'replacement'
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(path)
        self.assertToolError(self.call(protocol, 'rumbo_state'), 'REGISTRY_CHANGED')

    def test_unsafe_unknown_and_duplicate_registry_documents_are_not_overwritten(self):
        registry, installed = self.modules()
        path = self.data / 'projects.json'
        for document in ('{"projects":{}}', '{"version":1,"projects":{},"role":"human"}', '{"version":1,"version":1,"projects":{}}'):
            with self.subTest(document=document):
                path.write_text(document)
                path.chmod(0o600)
                before = path.read_bytes()
                with self.assertRaisesRegex(RumboError, 'REGISTRY_INVALID'):
                    installed.InstalledProtocol(self.data)
                with self.assertRaisesRegex(RumboError, 'REGISTRY_INVALID'):
                    registry.register_project(self.data, 'sample', self.project)
                self.assertEqual(path.read_bytes(), before)

    def test_registry_and_data_directory_permissions_or_symlinks_are_rejected(self):
        self.register()
        _, installed = self.modules()
        path = self.data / 'projects.json'
        for mode in (0o644, 0o660):
            path.chmod(mode)
            with self.assertRaisesRegex(RumboError, 'REGISTRY_UNSAFE'):
                installed.InstalledProtocol(self.data)
        path.chmod(0o600)
        moved = self.data / 'real.json'
        path.rename(moved)
        path.symlink_to(moved)
        with self.assertRaisesRegex(RumboError, 'REGISTRY_UNSAFE'):
            installed.InstalledProtocol(self.data)
        path.unlink()
        moved.rename(path)
        self.data.chmod(0o777)
        with self.assertRaisesRegex(RumboError, 'REGISTRY_UNSAFE'):
            installed.InstalledProtocol(self.data)
        self.data.chmod(0o700)

    def test_registration_rejects_uninitialized_empty_corrupt_and_wrong_schema_databases_without_writes(self):
        registry, _ = self.modules()
        roots = []
        absent = self.base / 'absent'
        absent.mkdir()
        roots.append(absent)
        empty = self.base / 'empty'
        empty.mkdir()
        Engine(empty, 'worker', 'worker')
        roots.append(empty)
        corrupt = self.base / 'corrupt'
        (corrupt / '.rumbo').mkdir(parents=True)
        (corrupt / '.rumbo/state.sqlite3').write_bytes(b'not a database')
        roots.append(corrupt)
        wrong = self.base / 'wrong'
        (wrong / '.rumbo').mkdir(parents=True)
        with sqlite3.connect(wrong / '.rumbo/state.sqlite3') as db:
            db.execute('CREATE TABLE events(unrelated TEXT)')
        roots.append(wrong)
        for root in roots:
            with self.subTest(root=root.name):
                before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with self.assertRaises(RumboError):
                    registry.register_project(self.data, root.name, root)
                self.assertEqual({p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
        self.assertFalse((absent / '.rumbo').exists())
        self.assertFalse((self.data / 'projects.json').exists())

    def test_bind_revalidates_initialized_database_and_expected_project_identity(self):
        self.register()
        protocol = self.protocol()
        dbpath = self.project / '.rumbo/state.sqlite3'
        with sqlite3.connect(dbpath) as db:
            db.execute('DELETE FROM events')
        before = dbpath.read_bytes()
        self.assertToolError(self.call(protocol, 'rumbo_connect_project', dict(alias='sample')), 'PROJECT_UNINITIALIZED')
        self.assertEqual(dbpath.read_bytes(), before)
        Engine(self.project, 'owner', 'human').execute('create_contract', dict(contract(), project_id='different'))
        self.assertToolError(self.call(protocol, 'rumbo_connect_project', dict(alias='sample')), 'PROJECT_ID_MISMATCH')

    def test_directory_replacement_before_or_after_bind_cannot_redirect_operations(self):
        self.register()
        unbound = self.protocol()
        bound = self.protocol()
        self.bind(bound)
        old = self.base / 'original'
        self.project.rename(old)
        self.project.mkdir()
        Engine(self.project, 'owner', 'human').execute('create_contract', contract())
        self.assertToolError(self.call(unbound, 'rumbo_connect_project', dict(alias='sample')), 'PROJECT_CHANGED')
        self.assertToolError(self.call(bound, 'rumbo_state'), 'PROJECT_CHANGED')
        self.assertToolError(self.call(bound, 'rumbo_claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60)), 'PROJECT_CHANGED')
        self.assertEqual(Engine(self.project, 'observer', 'viewer').snapshot()['events_count'], 1)

    def test_removed_or_replaced_state_database_is_not_recreated_or_used(self):
        self.register()
        protocol = self.protocol()
        self.bind(protocol)
        path = self.project / '.rumbo/state.sqlite3'
        original = path.read_bytes()
        path.unlink()
        self.assertToolError(self.call(protocol, 'rumbo_state'), 'PROJECT_CHANGED')
        self.assertFalse(path.exists())
        path.write_bytes(original)
        self.assertToolError(self.call(protocol, 'rumbo_state'), 'PROJECT_CHANGED')

    def project_descriptors(self, identities=None):
        identities = identities or {(p.stat().st_dev, p.stat().st_ino) for p in
                                   (self.project, self.project / '.rumbo', self.project / '.rumbo/state.sqlite3')}
        found = {}
        for name in os.listdir('/dev/fd'):
            try:
                fd = int(name)
                info = os.fstat(fd)
            except (OSError, ValueError):
                continue
            identity = (info.st_dev, info.st_ino)
            if identity in identities:
                found.setdefault(identity, set()).add(fd)
        return found

    def test_bound_connection_holds_readonly_identity_pins_until_close(self):
        import fcntl
        self.register()
        protocol = self.protocol()
        self.bind(protocol)
        descriptors = self.project_descriptors()
        self.assertEqual(len(descriptors), 3, 'The root, state directory, and database need live OS descriptors to prevent freed inode reuse')
        for fd in set().union(*descriptors.values()):
            self.assertEqual(fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE, os.O_RDONLY)
            self.assertFalse(os.get_inheritable(fd))
        protocol.engine.close()
        protocol.engine.close()
        for fd in set().union(*descriptors.values()):
            with self.assertRaises(OSError):
                os.fstat(fd)
        self.assertToolError(self.call(protocol, 'rumbo_state'), 'PROJECT_CHANGED')

    def test_unlinked_database_pin_stays_live_and_replacement_is_rejected(self):
        self.register()
        protocol = self.protocol()
        self.bind(protocol)
        path = self.project / '.rumbo/state.sqlite3'
        identity = (path.stat().st_dev, path.stat().st_ino)
        descriptors = self.project_descriptors({identity})
        self.assertTrue(descriptors, 'Database inode must stay pinned after validation')
        path.unlink()
        for fd in descriptors[identity]:
            self.assertEqual(os.fstat(fd).st_nlink, 0)
        # No intervening request reports the deletion. A valid replacement with
        # the same project ID must still be rejected, before any ledger writes.
        Engine(self.project, 'owner', 'human').execute('create_contract', contract())
        before = path.read_bytes()
        self.assertNotEqual((path.stat().st_dev, path.stat().st_ino), identity)
        self.assertToolError(self.call(protocol, 'rumbo_state'), 'PROJECT_CHANGED')
        self.assertToolError(self.call(protocol, 'rumbo_claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60)), 'PROJECT_CHANGED')
        self.assertEqual(path.read_bytes(), before)

    def test_identity_descriptors_are_released_when_connection_is_collected(self):
        import gc
        import weakref
        registry, _ = self.modules()
        engine = registry.ExistingProjectEngine(self.project, 'test-worker')
        descriptors = self.project_descriptors()
        self.assertEqual(len(descriptors), 3)
        reference = weakref.ref(engine)
        del engine
        gc.collect()
        self.assertIsNone(reference())
        for fd in set().union(*descriptors.values()):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_failed_binding_and_owner_registration_do_not_leak_identity_descriptors(self):
        registry, _ = self.modules()
        before = self.project_descriptors()
        self.register()
        self.assertEqual(self.project_descriptors(), before)
        protocol = self.protocol()
        path = self.project / '.rumbo/state.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('DELETE FROM events')
        db.close()
        for _ in range(10):
            self.assertToolError(self.call(protocol, 'rumbo_connect_project', dict(alias='sample')), 'PROJECT_UNINITIALIZED')
            self.assertEqual(self.project_descriptors(), before)

    def test_identity_pins_accept_concurrent_workers_and_normal_ledger_mutations(self):
        import concurrent.futures
        self.register()
        workers = [self.protocol() for _ in range(6)]
        connections = [self.bind(worker) for worker in workers]
        args = dict(task_id='export', contract_revision=1, lease_seconds=60)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            claims = list(pool.map(lambda worker: self.call(worker, 'rumbo_claim_task', args), workers))
        self.assertEqual(sum(not result['isError'] for result in claims), 1)
        winner = next(i for i, result in enumerate(claims) if not result['isError'])
        for index, result in enumerate(claims):
            if index != winner:
                self.assertToolError(result, 'LEASE_CONFLICT')
        self.assertFalse(self.call(workers[winner], 'rumbo_submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv'))['isError'])
        self.assertFalse(self.call(workers[winner], 'rumbo_run_checks', dict(task_id='export', contract_revision=1, artifact_revision=1))['isError'])
        for worker in workers:
            result = self.call(worker, 'rumbo_state')
            self.assertFalse(result['isError'])
            state = result['structuredContent']
            self.assertEqual(state['events_count'], 4)
            self.assertEqual(state['tasks'][0]['lease']['actor'], connections[winner]['actor'])
            self.assertEqual(state['tasks'][0]['status'], 'checks_passed')

    def test_sibling_cleanup_and_failed_initialization_preserve_sqlite_lock(self):
        registry, _ = self.modules()
        holder = registry.ExistingProjectEngine(self.project, 'holder')
        sibling = registry.ExistingProjectEngine(self.project, 'sibling')
        self.assertTrue(callable(getattr(sibling, 'close', None)), 'Pins need explicit safe cleanup')
        self.addCleanup(holder.close)
        probe = """import sqlite3, sys
connection = sqlite3.connect(sys.argv[1], timeout=0)
try:
    connection.execute('BEGIN IMMEDIATE')
except sqlite3.OperationalError as error:
    print('locked' if 'locked' in str(error) else str(error))
else:
    print('unlocked')
finally:
    connection.close()
"""
        def lock_state():
            result = subprocess.run([sys.executable, '-c', probe, str(self.project / '.rumbo/state.sqlite3')], text=True, capture_output=True, check=True)
            return result.stdout.strip()
        with holder._db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.assertEqual(lock_state(), 'locked')
            sibling.close()
            self.assertEqual(lock_state(), 'locked', 'Closing a sibling raw pin must not release this process SQLite transaction lock')
            expected = dict(device=self.project.stat().st_dev, inode=self.project.stat().st_ino, project_id='wrong-id')
            with self.assertRaisesRegex(RumboError, 'PROJECT_ID_MISMATCH'):
                registry.ExistingProjectEngine(self.project, 'failed-validator', expected=expected)
            self.assertEqual(lock_state(), 'locked', 'Failed construction cleanup must not release sibling transaction locks')
        self.assertEqual(lock_state(), 'unlocked')

    def test_process_actors_are_unique_and_lease_collision_expires_without_resume(self):
        self.register()
        first, second = self.protocol(), self.protocol()
        one, two = self.bind(first), self.bind(second)
        self.assertNotEqual(one['actor'], two['actor'])
        args = dict(task_id='export', contract_revision=1, lease_seconds=30)
        self.assertFalse(self.call(first, 'rumbo_claim_task', args)['isError'])
        self.assertToolError(self.call(second, 'rumbo_claim_task', args), 'LEASE_CONFLICT')
        self.assertToolError(self.call(second, 'rumbo_submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv')), 'LEASE_REQUIRED')
        self.now[0] += 31
        self.assertFalse(self.call(second, 'rumbo_claim_task', args)['isError'])
        actor = self.call(second, 'rumbo_state')['structuredContent']['tasks'][0]['lease']['actor']
        self.assertEqual(actor, two['actor'])
        for ttl in (29, 3601, True):
            self.assertToolError(self.call(second, 'rumbo_claim_task', dict(args, lease_seconds=ttl)), 'BAD_INPUT')

    def test_installed_tool_set_excludes_reviewer_and_human_authority(self):
        self.register()
        protocol = self.protocol()
        response = protocol.dispatch(dict(jsonrpc='2.0', id=1, method='tools/list'))
        names = {t['name'] for t in response['result']['tools']}
        self.assertIn('rumbo_list_projects', names)
        self.assertIn('rumbo_connect_project', names)
        self.assertIn('open_project_board', names)
        self.assertNotIn('rumbo_submit_review', names)
        self.bind(protocol)
        response = protocol.dispatch(dict(jsonrpc='2.0', id=1, method='tools/call', params=dict(name='rumbo_submit_review', arguments={})))
        self.assertEqual(response['error']['code'], -32602)

    def test_binding_notification_does_not_change_binding(self):
        self.register()
        protocol = self.protocol()
        response = protocol.dispatch(dict(jsonrpc='2.0', method='tools/call', params=dict(name='rumbo_connect_project', arguments=dict(alias='sample'))))
        self.assertIsNone(response)
        self.assertToolError(self.call(protocol, 'rumbo_state'), 'PROJECT_UNBOUND')
        self.bind(protocol)

    def test_wal_database_validation_cannot_create_sidecars(self):
        registry, _ = self.modules()
        path = self.project / '.rumbo/state.sqlite3'
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
        db.close()
        before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
        with self.assertRaisesRegex(RumboError, 'LEDGER_STORAGE_UNSUPPORTED'):
            registry.register_project(self.data, 'sample', self.project)
        self.assertEqual({p.name: p.read_bytes() for p in path.parent.iterdir()}, before)

    def test_readonly_validation_refuses_pending_journal_without_touching_it(self):
        registry, _ = self.modules()
        path = self.project / '.rumbo/state.sqlite3-journal'
        path.write_bytes(b'pending journal')
        before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
        with self.assertRaisesRegex(RumboError, 'LEDGER_STORAGE_UNSUPPORTED'):
            registry.register_project(self.data, 'sample', self.project)
        self.assertEqual({p.name: p.read_bytes() for p in path.parent.iterdir()}, before)

    def test_changed_ledger_identity_after_binding_is_rejected_before_mutation(self):
        self.register()
        protocol = self.protocol()
        self.bind(protocol)
        path = self.project / '.rumbo/state.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('DELETE FROM events')
        Engine(self.project, 'owner', 'human').execute('create_contract', dict(contract(), project_id='different'))
        before = path.read_bytes()
        self.assertToolError(self.call(protocol, 'rumbo_state'), 'PROJECT_ID_MISMATCH')
        self.assertToolError(self.call(protocol, 'rumbo_claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60)), 'PROJECT_ID_MISMATCH')
        self.assertEqual(path.read_bytes(), before)

    def test_corrupt_hash_chain_is_rejected_read_only_at_registration_and_binding(self):
        registry, _ = self.modules()
        self.register()
        protocol = self.protocol()
        path = self.project / '.rumbo/state.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute("UPDATE events SET digest='bad'")
        before = path.read_bytes()
        self.assertToolError(self.call(protocol, 'rumbo_connect_project', dict(alias='sample')), 'LEDGER_CORRUPT')
        with self.assertRaisesRegex(RumboError, 'LEDGER_CORRUPT'):
            registry.register_project(self.data, 'other', self.project)
        self.assertEqual(path.read_bytes(), before)

    def test_noncanonical_symlink_directory_is_not_registered(self):
        registry, installed = self.modules()
        linked = self.base / 'linked'
        linked.symlink_to(self.project, target_is_directory=True)
        with self.assertRaisesRegex(RumboError, 'PROJECT_CHANGED'):
            registry.register_project(self.data, 'linked', linked)
        data_link = self.base / 'linked-data'
        data_link.symlink_to(self.data, target_is_directory=True)
        with self.assertRaisesRegex(RumboError, 'REGISTRY_UNSAFE'):
            installed.InstalledProtocol(data_link)

    def test_concurrent_owner_registration_preserves_both_aliases(self):
        # Delay the real final rename so concurrent unprotected writers both
        # validate the same snapshot. The actual registry and files are real.
        import concurrent.futures
        import time
        from unittest.mock import patch
        registry, _ = self.modules()
        replace = os.replace
        def delayed_replace(source, target):
            time.sleep(0.2)
            return replace(source, target)
        with patch.object(registry.os, 'replace', side_effect=delayed_replace):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda alias: registry.register_project(self.data, alias, self.project), ['one', 'two']))
        self.assertEqual({result['alias'] for result in results}, {'one', 'two'})
        self.assertEqual(set(json.loads((self.data / 'projects.json').read_text())['projects']), {'one', 'two'})

    def test_owner_cli_registers_initialized_alias_and_rejects_duplicate_alias(self):
        self.modules()
        command = [sys.executable, '-m', 'rumbo.registry', '--plugin-data', str(self.data), 'add', 'sample', '--root', str(self.project)]
        first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        before = (self.data / 'projects.json').read_bytes()
        second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual((self.data / 'projects.json').read_bytes(), before)

    def test_packaged_launcher_ignores_legacy_environment_and_has_unique_actor_after_restart(self):
        self.register()
        from scripts.package_release import build_local
        import zipfile
        archive = self.base / 'local.zip'
        build_local(ROOT, archive)
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(self.base / 'installed')
        launcher = self.base / 'installed/rumbo/scripts/run_mcp.py'
        env = dict(os.environ, PLUGIN_DATA=str(self.data), RUMBO_PROJECT_ROOT=str(self.base / 'unapproved'), RUMBO_ACTOR='owner', RUMBO_ROLE='human')
        requests = [dict(jsonrpc='2.0', id=1, method='tools/call', params=dict(name='rumbo_state', arguments={})), dict(jsonrpc='2.0', id=2, method='tools/call', params=dict(name='rumbo_connect_project', arguments=dict(alias='sample')))]
        actors = []
        for _ in range(2):
            process = subprocess.run([sys.executable, str(launcher)], input=''.join(json.dumps(r)+'\n' for r in requests), text=True, capture_output=True, env=env, cwd=self.base)
            self.assertEqual(process.returncode, 0, process.stderr)
            outputs = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertToolError(outputs[0]['result'], 'PROJECT_UNBOUND')
            connection = outputs[1]['result']['structuredContent']
            self.assertEqual(connection['role'], 'worker')
            self.assertNotEqual(connection['actor'], 'owner')
            actors.append(connection['actor'])
        self.assertNotEqual(*actors)
        self.assertFalse((self.base / 'unapproved').exists())

    def test_packaged_launcher_requires_plugin_data_even_with_legacy_environment(self):
        self.modules()
        env = {k:v for k,v in os.environ.items() if k != 'PLUGIN_DATA'}
        env.update(RUMBO_PROJECT_ROOT=str(self.project), RUMBO_ROLE='reviewer')
        from scripts.package_release import build_local
        import zipfile
        archive = self.base / 'local.zip'
        build_local(ROOT, archive)
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(self.base / 'installed')
        launcher = self.base / 'installed/rumbo/scripts/run_mcp.py'
        process = subprocess.run([sys.executable, str(launcher)], input='', text=True, capture_output=True, env=env, cwd=self.base)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('PLUGIN_DATA', process.stderr)
