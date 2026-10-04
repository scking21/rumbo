"""Lease eligibility and event metadata share one synchronized decision time."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from rumbo.core import Engine, RumboError
from test_core import contract


class DecisionClockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.now = 1000
        self.owner = Engine(self.root, 'owner', 'human', clock=lambda: self.now)
        self.worker = Engine(self.root, 'maker', 'worker', clock=lambda: self.now)
        self.owner.execute('create_contract', contract())
        self.worker.execute('claim_task', self.claim_args())
        (self.root / 'export.csv').write_text('name,amount\nAlice,10\n')

    def claim_args(self):
        return dict(task_id='export', contract_revision=1, lease_seconds=30)

    def upload_args(self):
        return dict(task_id='export', contract_revision=1, filename='export.csv', content='name,amount')

    def last_event(self):
        with sqlite3.connect(self.worker.db_path) as db:
            return json.loads(db.execute('SELECT payload FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0])

    def assert_advancing_artifact(self, action, args):
        ticks = iter([1029, 1031, 1031])
        self.worker.clock = lambda: next(ticks)
        state = self.worker.execute(action, args)
        event = self.last_event()
        self.assertEqual(event['at'], 1029)
        self.assertEqual(event['data']['artifact']['at'], 1029)
        self.assertEqual(state['tasks'][0]['artifact']['at'], 1029)
        self.assertIsNone(state['tasks'][0]['lease'], 'Return projection must use current time')

    def test_advancing_clock_records_upload_eligibility_time(self):
        self.assert_advancing_artifact('ingest_artifact', self.upload_args())

    def test_advancing_clock_records_local_file_eligibility_time(self):
        self.assert_advancing_artifact('submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv'))

    def test_fractional_renewal_uses_decision_time_but_return_can_already_be_expired(self):
        ticks = iter([1029.5, 1060.0, 1060.0])
        self.worker.clock = lambda: next(ticks)
        state = self.worker.execute('claim_task', self.claim_args())
        event = self.last_event()
        self.assertEqual(event['at'], 1029.5)
        self.assertEqual(event['data']['lease']['expires_at'], 1059.5)
        self.assertIsNone(state['tasks'][0]['lease'])
        self.assertEqual(state['tasks'][0]['status'], 'unclaimed')

    def test_exact_fractional_expiry_rejects_artifacts_but_allows_reclaim(self):
        self.now = 1000.5
        self.worker.execute('claim_task', self.claim_args())
        self.now = 1030.499
        self.worker.execute('ingest_artifact', self.upload_args())
        self.assertEqual(self.last_event()['at'], 1030.499)
        other = Engine(self.root, 'other', 'worker', clock=lambda: self.now)
        with self.assertRaisesRegex(RumboError, 'LEASE_CONFLICT'):
            other.execute('claim_task', self.claim_args())
        before = self.owner.checkpoint()
        self.now = 1030.5
        for action, args in [('ingest_artifact', self.upload_args()),
                             ('submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv'))]:
            with self.subTest(action=action), self.assertRaisesRegex(RumboError, 'LEASE_REQUIRED'):
                self.worker.execute(action, args)
        self.assertEqual(self.owner.checkpoint(), before)
        state = other.execute('claim_task', self.claim_args())
        self.assertEqual(state['tasks'][0]['lease']['actor'], 'other')
        self.assertEqual(state['tasks'][0]['lease']['expires_at'], 1060.5)
        with self.assertRaisesRegex(RumboError, 'LEASE_REQUIRED'):
            self.worker.execute('ingest_artifact', self.upload_args())

    def test_clock_is_sampled_after_sqlite_lock_wait(self):
        self.now = 1029
        attempted = threading.Event()
        samples = []
        self.worker.clock = lambda: samples.append(self.now) or self.now
        original_db = self.worker._db

        @contextmanager
        def watched_db():
            with original_db() as db:
                db.set_trace_callback(lambda sql: attempted.set() if sql == 'BEGIN IMMEDIATE' else None)
                yield db

        with sqlite3.connect(self.worker.db_path) as blocker, patch.object(self.worker, '_db', watched_db):
            blocker.execute('BEGIN IMMEDIATE')
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.worker.execute, 'ingest_artifact', self.upload_args())
                try:
                    self.assertTrue(attempted.wait(5), 'Worker must reach the real SQLite lock')
                    self.assertEqual(samples, [], 'No time may be cached before the lock is acquired')
                    self.now = 1030
                finally:
                    blocker.commit()
                with self.assertRaisesRegex(RumboError, 'LEASE_REQUIRED'):
                    future.result(timeout=5)
        self.assertEqual(samples, [1030])
        self.assertEqual(self.owner.checkpoint()['events_count'], 2)

    def test_clock_is_sampled_after_ledger_replay(self):
        self.now = 1029
        replay = self.worker._replay

        def advancing_replay(db):
            state = replay(db)
            self.now = 1030
            return state

        with patch.object(self.worker, '_replay', advancing_replay):
            with self.assertRaisesRegex(RumboError, 'LEASE_REQUIRED'):
                self.worker.execute('ingest_artifact', self.upload_args())
        self.assertEqual(self.owner.checkpoint()['events_count'], 2)

    def test_invalid_clocks_fail_closed_with_bad_clock_before_any_mutation(self):
        before = self.owner.checkpoint()
        for now in [None, '1029', True, {}, float('nan'), float('inf'), -float('inf'), 10**1000]:
            with self.subTest(now=type(now).__name__):
                self.worker.clock = lambda: now
                with self.assertRaisesRegex(RumboError, 'BAD_CLOCK'):
                    self.worker.execute('ingest_artifact', self.upload_args())
                with self.assertRaisesRegex(RumboError, 'BAD_CLOCK'):
                    self.worker.snapshot()
                self.assertEqual(self.owner.checkpoint(), before)
        self.assertFalse((self.root / '.rumbo/artifacts').exists())

    def test_invalid_return_clock_rolls_back_candidate_ledger_event(self):
        before = self.owner.checkpoint()
        for invalid in [None, '1031', True, float('nan'), float('inf')]:
            with self.subTest(clock=type(invalid).__name__):
                ticks = iter([1029, invalid])
                self.worker.clock = lambda: next(ticks)
                with self.assertRaisesRegex(RumboError, 'BAD_CLOCK'):
                    self.worker.execute('ingest_artifact', self.upload_args())
                self.assertEqual(self.owner.checkpoint(), before)
                self.assertIsNone(self.owner.snapshot()['tasks'][0]['artifact'])
