"""Project-file destination and content are independent owner criteria."""
from pathlib import Path
import tempfile
import unittest
from rumbo.core import Engine, RumboError
from test_core import contract


class DeliveryLocationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.owner = Engine(self.root, 'owner', 'human')
        self.worker = Engine(self.root, 'worker', 'worker')
        for folder in ['final', 'draft']:
            target = self.root / folder / 'packet.csv'
            target.parent.mkdir()
            target.write_text('name,amount\n')
        self.job = contract()
        self.job['revision_scope'] = 'task'
        self.rule = {'id': 'where', 'kind': 'project_file_at', 'value': 'final/packet.csv'}
        self.job['tasks'][0]['acceptance'].append(self.rule)
        self.ids = dict(task_id='export', contract_revision=1)

    def start(self):
        self.owner.execute('create_contract', self.job)
        self.worker.execute('claim_task', dict(self.ids, lease_seconds=300))

    def register(self, path):
        return self.worker.execute('submit_artifact', dict(self.ids, path=path))

    def check(self, rev):
        return self.worker.execute('run_checks', dict(self.ids, artifact_revision=rev))['tasks'][0]

    def test_misdelivery_preserves_good_revision_and_human_decision(self):
        self.start()
        self.register('final/packet.csv')
        task = self.check(1)
        self.assertEqual(task['status'], 'checks_passed')
        self.assertEqual({e['check_id'] for e in task['evidence']}, {'where', 'header'})
        before = self.owner.execute('decide', dict(self.ids, artifact_revision=1, outcome='accepted', reason='Inspected delivery'))
        with self.assertRaisesRegex(RumboError, 'DESTINATION_MISMATCH'):
            self.register('draft/packet.csv')
        with self.assertRaisesRegex(RumboError, 'DESTINATION_MISMATCH'):
            self.worker.execute('ingest_artifact', dict(self.ids, filename='packet.csv', content='name,amount\n'))
        self.assertEqual(self.worker.snapshot(), before)

    def test_right_location_still_requires_correct_content(self):
        self.start()
        (self.root/'final/packet.csv').write_text('unfinished')
        self.register('final/packet.csv')
        task = self.check(1)
        self.assertEqual({e['check_id']: e['outcome'] for e in task['evidence']}, {'where': 'pass', 'header': 'fail'})
        with self.assertRaisesRegex(RumboError, 'CHECKS_INCOMPLETE'):
            self.owner.execute('decide', dict(self.ids, artifact_revision=1, outcome='accepted', reason='Attempt'))
        (self.root/'final/packet.csv').write_text('name,amount')
        self.register('final/packet.csv')
        self.assertEqual(self.check(2)['status'], 'checks_passed')

    def test_owner_reassignment_reopens_only_the_changed_scope(self):
        self.start()
        self.register('final/packet.csv')
        self.check(1)
        self.owner.execute('decide',dict(self.ids,artifact_revision=1,outcome='accepted',reason='Ready'))
        self.rule['value']='draft/packet.csv'
        state=self.owner.execute('revise_contract',dict(expected_revision=1,contract=self.job,reason='Move delivery'))
        self.assertEqual(state['tasks'][0]['status'],'stale')
        self.ids['contract_revision']=2
        self.worker.execute('claim_task',dict(self.ids,lease_seconds=300))
        self.register('draft/packet.csv')
        self.assertEqual(self.check(2)['status'],'checks_passed')

    def test_old_contract_keeps_content_only_behavior(self):
        self.job['tasks'][0]['acceptance'].remove(self.rule)
        self.start()
        self.register('draft/packet.csv')
        self.assertEqual(self.check(1)['status'],'checks_passed')

    def test_reject_conflicting_owner_slots(self):
        self.job['tasks'][0]['acceptance'].append(dict(self.rule,id='second',value='draft/packet.csv'))
        with self.assertRaisesRegex(RumboError,'two different'):
            self.start()

    def test_same_destination_preserves_valid_relative_spellings(self):
        self.rule['value'] = './final/packet.csv'
        self.start()
        self.register('./final//packet.csv')
        self.assertEqual(self.check(1)['status'], 'checks_passed')
