"""The installed worker can verify exact current bytes without creating a new review basis."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from rumbo.core import Engine, RumboError
from rumbo.installed import InstalledProtocol, _verify_checks, installed_tool_definitions
from rumbo.protocol import Protocol, tool_definitions
from rumbo.registry import register_project


class VerifyChecksTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        self.project = root/'project'
        self.project.mkdir()
        self.data = root/'plugin-data'
        self.data.mkdir(mode=0o700)
        self.path = self.project/'index.json'
        self.path.write_bytes(b'{"edition":true}\n')
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        checks = [dict(id='where', kind='project_file_at', value='index.json'),
                  dict(id='hash', kind='sha256', value=digest),
                  dict(id='text', kind='file_contains', value='edition'),
                  dict(id='bool', kind='json_equals', key='edition', value=True),
                  dict(id='manual', kind='manual_review', prompt='Inspect edition')]
        self.owner = Engine(self.project, 'owner', 'human')
        self.worker = Engine(self.project, 'maker', 'worker')
        self.owner.execute('create_contract', dict(project_id='audit', goal='Index review', original_request='Check the index.',
            decision_owner='owner', constraints=[], tasks=[dict(id='index', title='Index', dependencies=[], acceptance=checks)]))
        self.args = dict(task_id='index', contract_revision=1, artifact_revision=1)
        self.worker.execute('claim_task', dict(task_id='index',contract_revision=1,lease_seconds=3600))
        self.register_file()

    def register_file(self):
        return self.worker.execute('submit_artifact', dict(task_id='index',contract_revision=1,path='index.json'))

    def test_current_results_match_fresh_receipts_and_preserve_owner_basis(self):
        evidence = self.worker.execute('run_checks', self.args)['tasks'][0]['evidence']
        Engine(self.project, 'reviewer', 'reviewer').execute('submit_review',
            dict(self.args, check_id='manual', outcome='pass', detail='Inspected this fixture'))
        self.owner.execute('decide', dict(self.args, outcome='accepted', reason='Checked edition'))
        before = self.owner.snapshot()
        observer = Engine(self.project, 'reader', 'viewer', read_only=True, create=False)
        observation = _verify_checks(observer, self.args)
        self.assertEqual(observation['checks'], [{key:item[key] for key in ('check_id','outcome','detail')} for item in evidence])
        self.assertEqual(observation['manual_review_ids'], ['manual'])
        self.assertEqual(observation['status'], 'accepted')
        self.assertFalse(observation['recorded'])
        self.assertEqual(observation['ledger_head'], before['ledger_head'])
        self.assertEqual(before, self.owner.snapshot())
        self.assertEqual(self.worker.execute('run_checks', self.args)['tasks'][0]['status'], 'checks_passed')

    def test_changed_and_replaced_bytes_cannot_verify_the_old_revision(self):
        self.path.write_bytes(b'{"edition":1}\n')
        with self.assertRaisesRegex(RumboError, 'ARTIFACT_CHANGED'):
            _verify_checks(self.worker, self.args)
        self.register_file()
        with self.assertRaisesRegex(RumboError, 'STALE_ARTIFACT'):
            _verify_checks(self.worker, self.args)
        args = dict(self.args, artifact_revision=2)
        observation = _verify_checks(self.worker, args)
        self.assertEqual([row['outcome'] for row in observation['checks']], ['pass','fail','pass','fail'])
        self.assertEqual(observation['status'], 'produced')
        self.assertEqual(self.worker.snapshot()['tasks'][0]['evidence'], [])

    def test_explicitly_local_bound_and_read_only(self):
        name = 'rumbo_verify_checks'
        self.assertNotIn(name, {t['name'] for t in tool_definitions(oauth=True)})
        self.assertNotIn(name, {t['name'] for t in tool_definitions(question_observations=True)})
        tool = next(t for t in installed_tool_definitions() if t['name'] == name)
        self.assertTrue(tool['annotations']['readOnlyHint'])
        req = dict(jsonrpc='2.0', id=1, method='tools/call', params=dict(name=name, arguments=self.args))
        self.assertEqual(Protocol(self.worker).dispatch(req)['error']['message'], 'Unknown tool')
        register_project(self.data, 'disposable', self.project)
        protocol = InstalledProtocol(self.data)
        self.assertIn('PROJECT_UNBOUND', protocol.dispatch(req)['result']['content'][0]['text'])
        protocol.dispatch(dict(req, params=dict(name='rumbo_connect_project', arguments=dict(alias='disposable'))))
        self.addCleanup(protocol.engine.close)
        self.assertFalse(protocol.dispatch(req)['result']['isError'])
        for invalid in ({'role':'human'},{'path':'other'},{'contract_revision':True},{'artifact_revision':False}):
            with self.subTest(invalid=invalid):
                result = protocol.dispatch(dict(req, params=dict(name=name, arguments=dict(self.args, **invalid))))
                self.assertTrue(result['result']['isError'])
        self.path.write_bytes(b'changed')
        failed = protocol.dispatch(req)['result']
        self.assertTrue(failed['isError'])
        self.assertEqual(failed['structuredContent'],
                         dict(code='ARTIFACT_CHANGED', recorded=False, recovery=dict(tool='rumbo_state', arguments={})))
        self.assertNotIn('register the artifact again', failed['content'][0]['text'])
        self.project.rename(self.project.with_name('moved'))
        self.assertIn('PROJECT_CHANGED', protocol.dispatch(req)['result']['content'][0]['text'])
