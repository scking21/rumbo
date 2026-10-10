import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import warnings
import zipfile

from rumbo.core import Engine, RumboError


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / 'source'
        self.root.mkdir()
        self.owner = Engine(self.root, 'owner', 'human')
        self.owner.execute('create_contract', dict(project_id='backup-test', goal='Keep the state',
            original_request='Retain uploaded evidence', decision_owner='owner', constraints=[],
            tasks=[dict(id='task', title='Proof', dependencies=[],
                        acceptance=[dict(id='text', kind='file_contains', value='proof')])]))
        self.worker = Engine(self.root, 'worker', 'worker')
        self.worker.execute('claim_task', dict(task_id='task', contract_revision=1, lease_seconds=3600))
        self.archive = self.base / 'backup.zip'
        self.destination = self.base / 'restored'

    def tearDown(self):
        self.tmp.cleanup()

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('rumbo.backup'), 'operator backup API is missing')
        from rumbo import backup
        return backup

    def upload(self, text):
        self.worker.execute('ingest_artifact', dict(task_id='task', contract_revision=1,
                                                  filename='proof.txt', content=text))
        return hashlib.sha256(text.encode()).hexdigest()

    def backup(self):
        return self.api().backup_project(self.root, self.archive)

    def rewrite(self, mutate):
        with zipfile.ZipFile(self.archive) as archive:
            items = {info.filename: archive.read(info) for info in archive.infolist()}
        mutate(items)
        with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, data in items.items():
                archive.writestr(name, data)

    def assert_restore_rejected(self):
        with self.assertRaises(RumboError):
            self.api().restore_project(self.archive, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.base.glob('.rumbo-restore-*')))

    def test_round_trip_preserves_history_all_uploads_and_acceptance_after_restart(self):
        digests = [self.upload('old proof'), self.upload('new proof')]
        self.worker.execute('run_checks', dict(task_id='task', contract_revision=1, artifact_revision=2))
        self.owner.execute('decide', dict(task_id='task', contract_revision=1, artifact_revision=2,
                                         outcome='accepted', reason='Reviewed'))
        before = self.owner.snapshot()
        summary = self.backup()
        self.assertEqual(summary['ledger_head'], before['ledger_head'])
        self.assertEqual(summary['uploaded_blobs'], 2)
        self.assertEqual(summary['events_count'], before['events_count'])
        result = self.api().restore_project(self.archive, self.destination)
        self.assertEqual(result['ledger_head'], before['ledger_head'])
        restarted = Engine(self.destination, 'viewer', 'viewer').snapshot()
        self.assertEqual(restarted['ledger_head'], before['ledger_head'])
        self.assertEqual(restarted['tasks'][0]['status'], 'accepted')
        for digest in digests:
            self.assertTrue((self.destination / '.rumbo' / 'artifacts' / digest).is_file())
        self.assertEqual(Engine(self.root, 'viewer', 'viewer').snapshot()['ledger_head'], before['ledger_head'])
        self.assertEqual(stat.S_IMODE(self.archive.stat().st_mode), 0o600)
        for path in self.destination.rglob('*'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)

    def test_external_registered_files_and_credentials_are_excluded_and_reported(self):
        (self.root / 'proof.txt').write_text('proof')
        (self.root / '.env').write_text('SECRET=do-not-copy')
        (self.root / 'credentials.json').write_text('do-not-copy')
        self.worker.execute('submit_artifact', dict(task_id='task', contract_revision=1, path='proof.txt'))
        summary = self.backup()
        self.assertEqual(summary['external_file_references'], ['proof.txt'])
        self.assertIn('stale', summary['notice'])
        self.api().restore_project(self.archive, self.destination)
        self.assertEqual(set(p.name for p in self.destination.iterdir()), {'.rumbo'})
        restored = Engine(self.destination, 'viewer', 'viewer').snapshot()
        self.assertEqual(restored['tasks'][0]['status'], 'stale')
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), {'manifest.json', '.rumbo/state.sqlite3'})

    def test_real_concurrent_writes_produce_consistent_database_and_matching_blobs(self):
        self.upload('initial proof')
        started, stop = threading.Event(), threading.Event()
        errors = []
        writes = []
        def writer():
            try:
                worker = Engine(self.root, 'worker', 'worker')
                while not stop.is_set():
                    i = len(writes)
                    worker.execute('ingest_artifact', dict(task_id='task', contract_revision=1,
                        filename='proof.txt', content='proof ' + str(i)))
                    writes.append(i)
                    started.set()
            except BaseException as exc:
                errors.append(exc)
                started.set()
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            self.assertTrue(started.wait(5))
            self.backup()
        finally:
            stop.set(); thread.join(20)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
        self.assertTrue(writes)
        self.api().restore_project(self.archive, self.destination)
        state = Engine(self.destination, 'viewer', 'viewer').snapshot()
        self.assertTrue(state['integrity']['valid'])
        with sqlite3.connect(str(self.destination / '.rumbo/state.sqlite3')) as db:
            for (payload,) in db.execute('SELECT payload FROM events'):
                event = json.loads(payload)
                if event['action'] == 'ingest_artifact':
                    digest = event['data']['artifact']['sha256']
                    blob = (self.destination / '.rumbo/artifacts' / digest).read_bytes()
                    self.assertEqual(hashlib.sha256(blob).hexdigest(), digest)

    def test_live_wal_backup_includes_committed_wal_pages(self):
        with sqlite3.connect(str(self.root / '.rumbo/state.sqlite3')) as keeper:
            keeper.execute('PRAGMA journal_mode=WAL').fetchall()
            keeper.execute('BEGIN')
            keeper.execute('SELECT COUNT(*) FROM events').fetchone()
            self.upload('WAL proof')
            self.assertTrue((self.root / '.rumbo/state.sqlite3-wal').exists())
            self.backup()
            self.api().restore_project(self.archive, self.destination)
            self.assertEqual(Engine(self.destination, 'viewer', 'viewer').snapshot()['ledger_head'], self.owner.snapshot()['ledger_head'])

    def test_tampered_history_is_rejected_without_output(self):
        with sqlite3.connect(str(self.root / '.rumbo/state.sqlite3')) as db:
            db.execute("UPDATE events SET payload='{}' WHERE seq=1")
        with self.assertRaisesRegex(RumboError, 'LEDGER_CORRUPT'):
            self.backup()
        self.assertFalse(self.archive.exists())
        self.assertFalse(list(self.base.glob('.rumbo-backup-*')))

    def test_missing_or_corrupt_historical_upload_fails_even_when_latest_is_valid(self):
        old = self.upload('old proof')
        self.upload('new proof')
        path = self.root / '.rumbo/artifacts' / old
        for value in (b'corruption', None):
            with self.subTest(value=value):
                if value is None: path.unlink()
                else: path.write_bytes(value)
                with self.assertRaises(RumboError): self.backup()
                self.assertFalse(self.archive.exists())

    def test_backup_never_overwrites_existing_archive(self):
        self.archive.write_bytes(b'keep me')
        with self.assertRaises(RumboError): self.backup()
        self.assertEqual(self.archive.read_bytes(), b'keep me')

    def test_restore_accepts_empty_directory_but_rejects_existing_data(self):
        self.backup()
        self.destination.mkdir()
        self.api().restore_project(self.archive, self.destination)
        with self.assertRaises(RumboError): self.api().restore_project(self.archive, self.destination)
        other = self.base / 'occupied'; other.mkdir(); (other / 'keep').write_text('keep')
        with self.assertRaises(RumboError): self.api().restore_project(self.archive, other)
        self.assertEqual((other / 'keep').read_text(), 'keep')

    def test_symlink_source_and_output_paths_are_rejected(self):
        api = self.api()
        alias = self.base / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RumboError): api.backup_project(alias, self.archive)
        self.archive.symlink_to(self.base / 'victim')
        with self.assertRaises(RumboError): self.backup()
        self.assertFalse((self.base / 'victim').exists())
        self.archive.unlink()
        digest = self.upload('proof')
        blob = self.root / '.rumbo/artifacts' / digest
        outside = self.base / 'outside'; outside.write_bytes(blob.read_bytes()); blob.unlink(); blob.symlink_to(outside)
        with self.assertRaises(RumboError): self.backup()

    def test_trusted_macos_system_ancestor_is_canonicalized(self):
        api=self.api();base=self.base.resolve();alias=base/'system-alias';alias.symlink_to(base, target_is_directory=True)
        original=Path.lstat
        def root_owned(path):
            result=original(path)
            if path in (alias,base):
                values=list(result);values[4]=0
                return os.stat_result(values)
            return result
        with mock.patch.object(api.sys,'platform','darwin'), mock.patch.dict(api.SYSTEM_ALIASES,{alias:base},clear=True), mock.patch.object(Path,'lstat',root_owned):
            api.backup_project(alias/'source',alias/'backup.zip')
            api.restore_project(alias/'backup.zip',alias/'restored')
            self.assertEqual(Engine(self.destination,'reader','viewer').snapshot()['project_id'],'backup-test')
            with self.assertRaises(RumboError):api._path(alias)
            untrusted=self.base/'user-alias';untrusted.symlink_to(self.root,target_is_directory=True)
            with self.assertRaises(RumboError):api._path(alias/'user-alias'/'file')

    def test_system_alias_requires_platform_owner_and_exact_target(self):
        api=self.api();base=self.base.resolve();alias=base/'system-alias';alias.symlink_to(base,target_is_directory=True)
        original=Path.lstat
        def user_owned(path):
            result=original(path)
            if path==alias:
                values=list(result);values[4]=1000
                return os.stat_result(values)
            return result
        with mock.patch.dict(api.SYSTEM_ALIASES,{alias:base},clear=True):
            with mock.patch.object(api.sys,'platform','linux'),self.assertRaises(RumboError):api._path(alias/'source')
            with mock.patch.object(api.sys,'platform','darwin'),mock.patch.object(Path,'lstat',user_owned),self.assertRaises(RumboError):api._path(alias/'source')
        def root_alias_untrusted_target(path):
            result=original(path)
            if path in (alias,base):
                values=list(result);values[4]=0 if path==alias else 1000
                return os.stat_result(values)
            return result
        with mock.patch.object(Path,'lstat',root_alias_untrusted_target),mock.patch.object(api.sys,'platform','darwin'):
            with mock.patch.dict(api.SYSTEM_ALIASES,{alias:base/'wrong'},clear=True),self.assertRaisesRegex(RumboError,'Unexpected system path alias'):api._path(alias/'source')
            with mock.patch.dict(api.SYSTEM_ALIASES,{alias:base},clear=True),self.assertRaisesRegex(RumboError,'Untrusted system alias target'):api._path(alias/'source')

    def test_backup_paths_reject_parent_traversal_before_normalization(self):
        with self.assertRaises(RumboError):self.api()._path(self.base/'missing'/'..'/'source')

    def test_restore_rejects_archive_and_destination_symlinks(self):
        self.backup()
        alias = self.base / 'alias.zip'; alias.symlink_to(self.archive)
        with self.assertRaises(RumboError): self.api().restore_project(alias, self.destination)
        target = self.base / 'target'; target.mkdir(); self.destination.symlink_to(target, target_is_directory=True)
        with self.assertRaises(RumboError): self.api().restore_project(self.archive, self.destination)
        self.assertEqual(list(target.iterdir()), [])

    def test_path_traversal_and_unexpected_archive_entries_are_rejected(self):
        for name in ('../escape', '/absolute', '.rumbo/../escape', '.rumbo\\escape', '.env', '.rumbo/state.sqlite3-journal'):
            with self.subTest(name=name):
                if self.archive.exists(): self.archive.unlink()
                self.backup()
                self.rewrite(lambda items: items.update({name: b'bad'}))
                self.assert_restore_rejected()
        self.assertFalse((self.base / 'escape').exists())

    def test_duplicate_archive_names_are_rejected(self):
        self.backup()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'a') as archive:
                archive.writestr('manifest.json', '{}')
        self.assert_restore_rejected()

    def test_archive_symlink_entries_are_rejected(self):
        self.backup()
        with zipfile.ZipFile(self.archive, 'a') as archive:
            info = zipfile.ZipInfo('.rumbo/artifacts/' + '0' * 64)
            info.create_system = 3; info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, '/etc/passwd')
        self.assert_restore_rejected()

    def test_manifest_and_data_checksum_mismatch_are_rejected(self):
        self.backup()
        self.rewrite(lambda items: items.update({'.rumbo/state.sqlite3': items['.rumbo/state.sqlite3'] + b'tamper'}))
        self.assert_restore_rejected()

    def test_compressed_archive_bombs_are_rejected(self):
        with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', b'0' * (1024 * 1024))
        self.assert_restore_rejected()

    def test_interrupted_backup_and_restore_clean_staging(self):
        api = self.api()
        self.upload('proof')
        with mock.patch.object(zipfile.ZipFile, 'writestr', side_effect=OSError('simulated interrupted write')):
            with self.assertRaises(RumboError): self.backup()
        self.assertFalse(self.archive.exists())
        self.assertFalse(list(self.base.glob('.rumbo-backup-*')))
        self.backup()
        with mock.patch.object(api.os, 'rename', side_effect=OSError('simulated publish failure')):
            with self.assertRaises(RumboError): api.restore_project(self.archive, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.base.glob('.rumbo-restore-*')))

    def test_explicit_database_upload_event_and_archive_bounds(self):
        api = self.api()
        self.upload('proof')
        for constant, limit in [('MAX_DATABASE_BYTES', 1), ('MAX_INGEST', 1), ('MAX_UPLOAD_TOTAL', 1), ('MAX_EVENTS', 1), ('MAX_LEDGER_BYTES', 1)]:
            with self.subTest(constant=constant), mock.patch.object(api, constant, limit):
                with self.assertRaises(RumboError): self.backup()
                self.assertFalse(self.archive.exists())
        self.backup()
        with mock.patch.object(api, 'MAX_ARCHIVE_BYTES', 1): self.assert_restore_rejected()

    def test_unreferenced_uploads_are_not_copied(self):
        digest = self.upload('proof')
        orphan = hashlib.sha256(b'orphan').hexdigest()
        (self.root / '.rumbo/artifacts' / orphan).write_bytes(b'orphan')
        self.backup()
        self.api().restore_project(self.archive, self.destination)
        self.assertEqual({p.name for p in (self.destination / '.rumbo/artifacts').iterdir()}, {digest})

    def test_restored_hash_chain_is_verified_even_if_archive_checksums_are_recomputed(self):
        self.backup()
        def tamper(items):
            path = self.base / 'tampered.sqlite3'
            path.write_bytes(items['.rumbo/state.sqlite3'])
            with sqlite3.connect(str(path)) as db:
                db.execute("UPDATE events SET payload='{}' WHERE seq=1")
            items['.rumbo/state.sqlite3'] = path.read_bytes()
            manifest = json.loads(items['manifest.json'])
            manifest['files']['.rumbo/state.sqlite3'] = dict(size=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            items['manifest.json'] = json.dumps(manifest).encode()
        self.rewrite(tamper)
        self.assert_restore_rejected()

    def test_restore_rejects_missing_referenced_upload_even_with_updated_manifest(self):
        digest = self.upload('proof')
        self.backup()
        def omit(items):
            name = '.rumbo/artifacts/' + digest
            del items[name]
            manifest = json.loads(items['manifest.json'])
            del manifest['files'][name]
            items['manifest.json'] = json.dumps(manifest).encode()
        self.rewrite(omit)
        self.assert_restore_rejected()

    def test_other_database_tables_are_never_archived(self):
        with sqlite3.connect(str(self.root / '.rumbo/state.sqlite3')) as db:
            db.execute('CREATE TABLE credentials(secret TEXT)')
            db.execute("INSERT INTO credentials VALUES('do-not-copy')")
        with self.assertRaises(RumboError): self.backup()
        self.assertFalse(self.archive.exists())

    def test_archive_directory_size_is_bounded_before_zip_parsing(self):
        self.backup()
        data = bytearray(self.archive.read_bytes())
        # EOCD total/disk entry counts are attacker-controlled; reject before ZipFile allocates.
        data[-14:-10] = b'\xff\xff\xff\xff'
        self.archive.write_bytes(data)
        with mock.patch.object(zipfile, 'ZipFile', side_effect=AssertionError('must not parse')):
            self.assert_restore_rejected()

    def test_backup_timeout_does_not_publish_incomplete_archive(self):
        api = self.api()
        with mock.patch.object(api, 'BACKUP_TIMEOUT_SECONDS', -1):
            with self.assertRaisesRegex(RumboError, 'BACKUP_BUSY'): self.backup()
        self.assertFalse(self.archive.exists())
        self.assertFalse(list(self.base.glob('.rumbo-backup-*')))

    def test_restore_failure_preserves_preexisting_empty_destination(self):
        self.backup()
        self.destination.mkdir()
        original = self.destination.stat().st_ino
        self.rewrite(lambda items: items.update({'.rumbo/state.sqlite3': b'bad'}))
        with self.assertRaises(RumboError): self.api().restore_project(self.archive, self.destination)
        self.assertEqual(self.destination.stat().st_ino, original)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_backup_keeps_a_same_process_writer_lock(self):
        # POSIX drops every lock this process holds on a file when any descriptor for it closes.
        probe = ("import sqlite3,sys\n"
                 "db=sqlite3.connect(sys.argv[1],timeout=0,isolation_level=None)\n"
                 "try:db.execute('BEGIN IMMEDIATE');print('ACQUIRED')\n"
                 "except sqlite3.OperationalError:print('BUSY')\n")
        def other_process():
            return subprocess.run([sys.executable, '-c', probe, str(self.root / '.rumbo/state.sqlite3')],
                                  capture_output=True, text=True).stdout.strip()
        writer = sqlite3.connect(self.root / '.rumbo/state.sqlite3', isolation_level=None)
        self.addCleanup(writer.close)
        writer.execute('BEGIN IMMEDIATE')
        self.assertEqual(other_process(), 'BUSY')
        self.backup()
        self.assertEqual(other_process(), 'BUSY', 'Backup released a lock owned by another connection')

    def test_cli_prints_json_and_failure_has_nonzero_status(self):
        self.api()
        result = subprocess.run([sys.executable, '-m', 'rumbo.backup', 'backup', '--root', str(self.root), '--destination', str(self.archive)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['project_id'], 'backup-test')
        result = subprocess.run([sys.executable, '-m', 'rumbo.backup', 'restore', '--archive', str(self.archive), '--destination', str(self.destination)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['project_id'], 'backup-test')
        again = subprocess.run([sys.executable, '-m', 'rumbo.backup', 'restore', '--archive', str(self.archive), '--destination', str(self.destination)], capture_output=True, text=True)
        self.assertNotEqual(again.returncode, 0)


if __name__ == '__main__':
    unittest.main()
