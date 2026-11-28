"""Guard local file registration against stale retries and changed reviewed bytes."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from rumbo.core import Engine, RumboError
from rumbo.installed import InstalledProtocol, installed_tool_definitions
from rumbo.protocol import Protocol, tool_definitions
from rumbo.registry import register_project


ROOT = Path(__file__).resolve().parents[1]


def contract():
    return dict(project_id='guarded', goal='Register reviewed local bytes',
                original_request='Register the exact reviewed report.',
                decision_owner='owner', constraints=['Keep work local'],
                tasks=[dict(id='report', title='Report', dependencies=[],
                            acceptance=[dict(id='text', kind='file_contains', value='report')])])


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def request(name, arguments=None):
    return dict(jsonrpc='2.0', id=1, method='tools/call',
                params=dict(name=name, arguments=arguments or {}))


class GuardedSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base / 'project'
        self.project.mkdir()
        self.data = self.base / 'plugin-data'
        self.data.mkdir(mode=0o700)
        self.owner = Engine(self.project, 'owner', 'human')
        self.worker = Engine(self.project, 'worker', 'worker', create=False)
        self.owner.execute('create_contract', contract())
        self.file = self.project / 'report.txt'
        self.file.write_bytes(b'report one\n')

    def claim(self):
        self.worker.execute('claim_task', dict(task_id='report', contract_revision=1,
                                               lease_seconds=300))

    def submit(self, **extra):
        return self.worker.execute('submit_artifact', dict(task_id='report',
                                   contract_revision=1, path='report.txt', **extra))

    def test_stale_retry_cannot_replace_newer_registration_and_valid_refresh_proceeds(self):
        self.claim()
        first_digest = digest(self.file.read_bytes())
        first = self.submit(expected_artifact_revision=0, expected_sha256=first_digest)
        before_retry = self.owner.checkpoint()

        with self.assertRaisesRegex(RumboError, 'STALE_REGISTRATION'):
            self.submit(expected_artifact_revision=0, expected_sha256=first_digest)

        self.assertEqual(self.owner.checkpoint(), before_retry)
        self.assertEqual(first['tasks'][0]['artifact']['revision'], 1)

        self.file.write_bytes(b'report two\n')
        second_digest = digest(self.file.read_bytes())
        refreshed = self.submit(expected_artifact_revision=1, expected_sha256=second_digest)

        self.assertEqual(refreshed['tasks'][0]['artifact']['revision'], 2)
        self.assertEqual(refreshed['tasks'][0]['artifact']['sha256'], second_digest)

    def test_changed_reviewed_bytes_fail_without_receipt_then_current_digest_succeeds(self):
        self.claim()
        reviewed_digest = digest(self.file.read_bytes())
        before = self.owner.checkpoint()
        self.file.write_bytes(b'report changed after review\n')

        with self.assertRaisesRegex(RumboError, 'REVIEWED_BYTES_CHANGED'):
            self.submit(expected_artifact_revision=0, expected_sha256=reviewed_digest)

        self.assertEqual(self.owner.checkpoint(), before)
        self.assertIsNone(self.owner.snapshot()['tasks'][0]['artifact'])

        current_digest = digest(self.file.read_bytes())
        state = self.submit(expected_artifact_revision=0, expected_sha256=current_digest)
        self.assertEqual(state['tasks'][0]['artifact']['sha256'], current_digest)

    def test_legacy_unguarded_registration_remains_compatible(self):
        self.claim()
        first = self.submit()
        self.file.write_bytes(b'report legacy refresh\n')
        second = self.submit()

        self.assertEqual(first['tasks'][0]['artifact']['revision'], 1)
        self.assertEqual(second['tasks'][0]['artifact']['revision'], 2)

    def test_only_installed_catalog_advertises_guards_and_uses_them(self):
        guarded = {'expected_sha256', 'expected_artifact_revision'}
        installed = next(tool for tool in installed_tool_definitions()
                         if tool['name'] == 'rumbo_submit_artifact')
        hosted_python = next(tool for tool in tool_definitions(oauth=True)
                             if tool['name'] == 'rumbo_submit_artifact')

        self.assertTrue(guarded <= set(installed['inputSchema']['properties']))
        self.assertTrue(guarded.isdisjoint(installed['inputSchema']['required']))
        self.assertTrue(guarded.isdisjoint(hosted_python['inputSchema']['properties']))

        base_response = Protocol(self.worker).dispatch(request('rumbo_submit_artifact', dict(
            task_id='report', contract_revision=1, path='report.txt',
            expected_artifact_revision=0, expected_sha256=digest(self.file.read_bytes()))))
        self.assertTrue(base_response['result']['isError'])
        self.assertIn('UNKNOWN_FIELD', base_response['result']['content'][0]['text'])

        register_project(self.data, 'sample', self.project)
        installed_protocol = InstalledProtocol(self.data, clock=lambda: 1000.0)
        connected = installed_protocol.dispatch(request('rumbo_connect_project', {'alias':'sample'}))
        self.assertFalse(connected['result']['isError'])
        claimed = installed_protocol.dispatch(request('rumbo_claim_task', dict(
            task_id='report', contract_revision=1, lease_seconds=300)))
        self.assertFalse(claimed['result']['isError'])
        registered = installed_protocol.dispatch(request('rumbo_submit_artifact', dict(
            task_id='report', contract_revision=1, path='report.txt',
            expected_artifact_revision=0, expected_sha256=digest(self.file.read_bytes()))))
        self.assertFalse(registered['result']['isError'], registered)
        self.assertEqual(registered['result']['structuredContent']['tasks'][0]['artifact']['revision'], 1)

        script = ("import {toolDefinitions} from './openai-sites/worker/protocol.js';"
                  "process.stdout.write(JSON.stringify(toolDefinitions()));")
        process = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                                 text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        hosted_sites = json.loads(process.stdout)
        self.assertNotIn('rumbo_submit_artifact', {tool['name'] for tool in hosted_sites})
        for tool in hosted_sites:
            offered = set(tool['inputSchema']['properties']) & guarded
            expected = guarded if tool['name'] == 'rumbo_ingest_artifact' else set()
            self.assertEqual(offered, expected, tool['name'])


if __name__ == '__main__':
    unittest.main()
