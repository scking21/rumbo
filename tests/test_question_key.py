"""Local guarded decision requests may opt into per-principal intent identity."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rumbo.core import Engine, RumboError
from rumbo.protocol import Protocol
from test_question_observation import notebook


class QuestionKeyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.owner = Engine(self.root, 'editor', 'human')
        self.contract = notebook()
        self.owner.execute('create_contract', self.contract)
        self.worker = Engine(self.root, 'scribe', 'worker', create=False)
        self.args = dict(task_id='index', question='Retain this heading?', request_key='intent-43',
                         observation=self.worker.observe_question('index')['question_observation'])

    def submit(self, worker=None, **edits):
        return (worker or self.worker).execute('request_decision', dict(self.args, **edits))

    def test_concurrent_retransmissions_commit_one_event_and_recover_through_restart(self):
        with ThreadPoolExecutor(2) as executor:
            futures = [executor.submit(self.submit) for _ in range(2)]
            acks = [future.result()['decision_request_ack'] for future in futures]
        self.assertEqual([False, True], sorted(ack['appended'] for ack in acks))
        self.assertEqual({ack['event_id'] for ack in acks}, {'e2'})
        restarted = Engine(self.root, 'scribe', 'worker', create=False)
        self.assertFalse(self.submit(restarted)['decision_request_ack']['appended'])
        self.assertEqual(len(self.owner.snapshot()['requests']), 1)
        self.assertNotIn('decision_request_ack', self.owner.snapshot())

    def test_collisions_do_not_modify_history(self):
        self.submit()
        before = self.owner.checkpoint()
        for edits in (dict(question='Use another title?'), dict(task_id='outline'),
                      dict(observation=dict(self.args['observation'], events_count=True))):
            with self.subTest(edits=edits), self.assertRaises(RumboError) as error:
                self.submit(**edits)
            self.assertEqual(error.exception.code, 'QUESTION_KEY_CONFLICT')
        self.assertEqual(self.owner.checkpoint(), before)

    def test_different_intents_and_principals_still_proceed(self):
        self.args['observation'] = self.worker.observe_question('index', related_task_ids=[])['question_observation']
        self.submit()
        self.submit(request_key='other-intent')
        self.submit(Engine(self.root, 'second-worker', 'worker', create=False))
        self.submit(Engine(self.root, 'scribe', 'reviewer', create=False))
        records = self.owner.snapshot()['requests']
        self.assertEqual(len(records), 4)
        self.assertEqual(len({(r['actor'], r['request_role'], r['request_key']) for r in records}), 4)
        with self.assertRaises(RumboError) as denied:
            self.submit(Engine(self.root, 'scribe', 'viewer', create=False))
        self.assertEqual(denied.exception.code, 'FORBIDDEN')

    def test_fresh_key_still_checks_observation_and_requires_it(self):
        self.submit()
        before = self.owner.checkpoint()
        with self.assertRaises(RumboError) as stale:
            self.submit(request_key='fresh-intent')
        self.assertEqual(stale.exception.code, 'STALE_QUESTION')
        with self.assertRaises(RumboError) as missing:
            self.worker.execute('request_decision', {k:v for k,v in self.args.items() if k!='observation'})
        self.assertEqual(missing.exception.code, 'BAD_INPUT')
        for key in ('', '/', 'k'*65, None, 42):
            with self.subTest(key=key), self.assertRaises(RumboError) as invalid:
                self.submit(request_key=key)
            self.assertEqual(invalid.exception.code, 'BAD_INPUT')
        self.assertEqual(before, self.owner.checkpoint())

    def test_replay_at_capacity_and_after_task_removed_returns_original_receipt(self):
        self.submit()
        self.contract['tasks'] = [t for t in self.contract['tasks'] if t['id']!='index']
        self.owner.execute('revise_contract', dict(contract=self.contract,expected_revision=1,reason='Remove index'))
        before = self.owner.checkpoint()
        with patch('rumbo.core.MAX_EVENTS', before['events_count']):
            request = dict(jsonrpc='2.0',id=8,method='tools/call',params=dict(
                name='rumbo_request_decision',arguments=dict(self.args,response_mode='receipt')))
            result = Protocol(self.worker,question_observations=True).dispatch(request)['result']
            self.assertFalse(result['isError'])
            receipt = result['structuredContent']
            self.assertEqual(receipt['kind'], 'rumbo.decision_request_receipt.v1')
            self.assertFalse(receipt['decision_request_ack']['appended'])
            self.assertEqual(receipt['decision_request_ack']['event_id'], 'e2')
            self.assertEqual(receipt['decision_request_ack']['recorded_contract_revision'], 1)
            self.assertEqual(receipt['ledger']['head'], before['ledger_head'])
        self.assertEqual(before, self.owner.checkpoint())
