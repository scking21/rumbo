"""Retain a previously accepted basis during a mixed verify/record task on the local launcher."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from rumbo.core import Engine
from rumbo.registry import register_project


def launcher_protocol():
    path = Path(__file__).resolve().parents[1] / 'openai-plugin/rumbo/scripts/run_mcp.py'
    spec = importlib.util.spec_from_file_location('local_approval_launcher', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ApprovalProtocol


class ApprovalPreservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        self.project = root / 'project'
        self.project.mkdir()
        data = root / 'plugin-data'
        data.mkdir(mode=0o700)
        self.owner = Engine(self.project, 'editor', 'human')
        maker = Engine(self.project, 'maker', 'worker')
        tasks = [dict(id=name, title=name, dependencies=deps,
                      acceptance=[dict(id='text',kind='file_contains',value='pass')])
                 for name,deps in [('catalog',[]), ('binder',['catalog']), ('insert',[])]]
        self.owner.execute('create_contract', dict(project_id='book', goal='Keep catalog acceptance and check the insert',
            original_request='Verify the catalog; record insert checks.', decision_owner='editor', constraints=[], tasks=tasks))
        for task in tasks:
            name = task['id']
            path = name+'.txt'
            (self.project/path).write_text('pass')
            maker.execute('claim_task', dict(task_id=name, contract_revision=1, lease_seconds=3600))
            maker.execute('submit_artifact', dict(task_id=name, contract_revision=1, path=path))
            if name != 'insert':
                maker.execute('run_checks', self.target(name))
                self.owner.execute('decide', dict(self.target(name), outcome='accepted', reason='Inspected'))
        register_project(data, 'book', self.project)
        self.worker = launcher_protocol()(data)
        self.call('rumbo_connect_project', alias='book')
        self.addCleanup(self.worker.engine.close)

    @staticmethod
    def target(task):
        return dict(task_id=task, contract_revision=1, artifact_revision=1)

    def call(self, tool, **args):
        return self.worker.dispatch(dict(jsonrpc='2.0', id=1, method='tools/call',
            params=dict(name=tool, arguments=args)))['result']

    def test_mixed_intent_and_deliberately_revised_instruction(self):
        catalog, insert = self.target('catalog'), self.target('insert')
        before = self.owner.snapshot()
        verified = self.call('rumbo_verify_checks', **catalog, preserve_approval=True)['structuredContent']
        token = verified['approval_preservation']['record_after_verification']
        held = self.call('rumbo_run_checks', **catalog)
        self.assertEqual(held['structuredContent']['code'], 'APPROVAL_PRESERVED')
        self.assertEqual(before, self.owner.snapshot())
        self.assertFalse(self.call('rumbo_run_checks', **insert)['isError'])
        state = self.owner.snapshot()
        self.assertEqual([t['status'] for t in state['tasks']], ['accepted', 'accepted', 'checks_passed'])
        self.assertFalse(self.call('rumbo_run_checks', **catalog, record_after_verification=token)['isError'])
        recorded = self.owner.snapshot()
        self.assertEqual([t['status'] for t in recorded['tasks']], ['checks_passed', 'blocked', 'checks_passed'])
        self.assertEqual(recorded['events_count'], before['events_count'] + 2)
        repeated = self.call('rumbo_run_checks', **catalog, record_after_verification=token)
        self.assertEqual(repeated['structuredContent']['code'], 'APPROVAL_PRESERVED')
        self.assertEqual(self.owner.snapshot(), recorded)

    def test_correcting_rejected_options_preserves_one_use(self):
        catalog = self.target('catalog')
        before = self.owner.snapshot()
        observation = self.call('rumbo_verify_checks', **catalog, preserve_approval=True)
        token = observation['structuredContent']['approval_preservation']['record_after_verification']
        request = dict(catalog, record_after_verification=token)
        for bad_options, expected in (({'response_mode': 'compact'}, 'BAD_INPUT'),
                                      ({'format': 'receipt'}, 'UNKNOWN_FIELD')):
            with self.subTest(options=bad_options):
                rejected = self.call('rumbo_run_checks', **request, **bad_options)
                self.assertTrue(rejected['isError'])
                self.assertTrue(rejected['content'][0]['text'].startswith(expected + ':'))
                self.assertEqual(self.owner.snapshot(), before)
        recorded = self.call('rumbo_run_checks', **request, response_mode='receipt')
        self.assertFalse(recorded['isError'])
        after = self.owner.snapshot()
        self.assertEqual(after['events_count'], before['events_count'] + 1)
        self.assertEqual([t['status'] for t in after['tasks']], ['checks_passed', 'blocked', 'produced'])
        repeated = self.call('rumbo_run_checks', **request)
        self.assertEqual(repeated['structuredContent']['code'], 'APPROVAL_PRESERVED')
        self.assertEqual(self.owner.snapshot(), after)

    def test_rotated_token_and_project_identity_boundary(self):
        catalog = self.target('catalog')
        def token():
            return self.call('rumbo_verify_checks', **catalog, preserve_approval=True)['structuredContent']['approval_preservation']['record_after_verification']
        old, current = token(), token()
        self.assertNotEqual(old, current)
        self.assertEqual(self.call('rumbo_run_checks', **catalog, record_after_verification=old)['structuredContent']['code'],
                         'APPROVAL_PRESERVED')
        self.project.rename(self.project.with_name('moved'))
        for args in (catalog, dict(catalog, record_after_verification=current)):
            with self.subTest(override='record_after_verification' in args):
                self.assertEqual(self.call('rumbo_run_checks', **args)['structuredContent']['code'], 'PROJECT_CHANGED')
