"""The verify command checks existing history without bootstrapping storage."""
import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rumbo.core import Engine, RumboError
from test_core import contract


class ReadOnlyVerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def verify(self, root=None):
        return subprocess.run([sys.executable, '-m', 'rumbo', '--root', str(root or self.root), 'verify'],
                              text=True, capture_output=True, timeout=10)

    def owner(self):
        owner = Engine(self.root, 'owner', 'human')
        owner.execute('create_contract', contract())
        return owner

    def test_empty_directory_is_not_initialized_by_verify(self):
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn('NO_CONTRACT', result.stderr)
        self.assertFalse((self.root/'.rumbo').exists())

    def test_missing_root_is_not_created_by_verify(self):
        root = self.root/'absent'
        result = self.verify(root)
        self.assertEqual(result.returncode, 2)
        self.assertIn('PATH_INVALID', result.stderr)
        self.assertFalse(root.exists())

    def test_uninitialized_existing_ledger_is_not_a_valid_checkpoint(self):
        Engine(self.root, 'viewer', 'viewer')
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn('NO_CONTRACT', result.stderr)

    def test_verify_preserves_read_only_database_bytes_metadata_and_permissions(self):
        expected = self.owner().snapshot()
        path = self.root/'.rumbo/state.sqlite3'
        path.chmod(0o400)
        before = (path.read_bytes(), path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode))
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {key:expected[key] for key in ('project_id','events_count','ledger_head','integrity')})
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode)), before)

    def test_existing_wal_reads_latest_committed_history(self):
        owner = self.owner()
        path = self.root/'.rumbo/state.sqlite3'
        writer = sqlite3.connect(path)
        self.addCleanup(writer.close)
        self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('BEGIN')
        writer.execute('SELECT COUNT(*) FROM events').fetchone()
        owner.execute('request_decision', dict(task_id='export', question='Synthetic WAL checkpoint'))
        expected = owner.snapshot()
        self.assertTrue(path.with_name('state.sqlite3-wal').exists())
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['ledger_head'], expected['ledger_head'])
        self.assertEqual(json.loads(result.stdout)['events_count'], 2)

    def test_checkpoint_does_not_read_or_project_artifact_bytes(self):
        owner = self.owner()
        worker = Engine(self.root, 'maker', 'worker')
        worker.execute('claim_task', dict(task_id='export', contract_revision=1, lease_seconds=300))
        worker.execute('ingest_artifact', dict(task_id='export', contract_revision=1, filename='proof.txt', content='name,amount'))
        expected = owner.snapshot()
        with patch.object(Engine, '_digest_artifact', side_effect=AssertionError('Ledger verification must not read artifact bytes')):
            checkpoint = Engine(self.root, 'verifier', 'viewer', read_only=True).checkpoint()
        self.assertEqual(checkpoint['ledger_head'], expected['ledger_head'])

    def test_checkpointed_wal_preserves_main_database_and_reads_closed_history(self):
        expected = self.owner().snapshot()
        path = self.root/'.rumbo/state.sqlite3'
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
        finally:
            connection.close()
        self.assertFalse(path.with_name('state.sqlite3-wal').exists())
        before = (path.read_bytes(), path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode))
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['ledger_head'], expected['ledger_head'])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode)), before)
        # SQLite may materialize its auxiliary WAL index even in mode=ro.
        # This is documented rather than using immutable=1 and hiding live WAL.
        self.assertTrue({entry.name for entry in path.parent.iterdir()} <=
                        {'state.sqlite3', 'state.sqlite3-wal', 'state.sqlite3-shm'})

    def test_read_only_engine_cannot_acquire_write_authority(self):
        self.owner()
        with self.assertRaisesRegex(RumboError, 'FORBIDDEN'):
            Engine(self.root, 'owner', 'human', read_only=True)
        reader = Engine(self.root, 'verifier', 'viewer', read_only=True)
        with self.assertRaisesRegex(RumboError, 'FORBIDDEN'):
            reader.execute('request_decision', dict(task_id='export', question='Must not write'))

    def test_read_only_verify_still_rejects_corrupted_chain(self):
        self.owner()
        with sqlite3.connect(self.root/'.rumbo/state.sqlite3') as database:
            database.execute("UPDATE events SET digest='invalid'")
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn('LEDGER_CORRUPT', result.stderr)
