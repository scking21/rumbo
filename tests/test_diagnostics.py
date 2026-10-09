"""Refusals name the current value or the next action an agent needs to recover."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rumbo.core import Engine, RumboError
from rumbo.protocol import Protocol


def contract():
    check = [dict(id='header', kind='file_contains', value='name,amount')]
    return dict(project_id='sample', goal='Ship CSV export', original_request='Export CSV.', decision_owner='owner', constraints=[], tasks=[
        dict(id='export', title='Export CSV', dependencies=[], acceptance=check),
        dict(id='doc', title='Describe the export', dependencies=['export'], acceptance=check),
    ])


class RecoveryMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = [1000.0]
        clock = lambda: self.now[0]
        self.owner = Engine(self.root, 'owner', 'human', clock=clock)
        self.worker = Engine(self.root, 'maker', 'worker', clock=clock)
        self.other = Engine(self.root, 'other', 'worker', clock=clock)
        self.owner.execute('create_contract', contract())
        (self.root / 'export.csv').write_text('name,amount\nAlice,10\n')
        (self.root / 'doc.md').write_text('name,amount\n')

    def refusal(self, engine, action, **arguments):
        with self.assertRaises(RumboError) as caught:
            if action == 'read':
                engine.artifact_view(arguments)
            else:
                engine.execute(action, arguments)
        return caught.exception

    def produce(self, task='export', path='export.csv', revision=1):
        self.worker.execute('claim_task', dict(task_id=task, contract_revision=revision, lease_seconds=60))
        return self.worker.execute('submit_artifact', dict(task_id=task, contract_revision=revision, path=path))

    def accept(self):
        self.produce()
        self.worker.execute('run_checks', dict(task_id='export', contract_revision=1, artifact_revision=1))
        self.owner.execute('decide', dict(task_id='export', contract_revision=1, artifact_revision=1, outcome='accepted', reason='Reviewed'))

    def test_stale_contract_names_the_current_revision(self):
        self.owner.execute('revise_contract', dict(contract=contract(), expected_revision=1, reason='Clarify'))
        self.owner.execute('revise_contract', dict(contract=contract(), expected_revision=2, reason='Clarify again'))
        for engine, action, arguments in (
            (self.worker, 'claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60)),
            (self.worker, 'read', dict(task_id='export', contract_revision=1, artifact_revision=1)),
            (self.owner, 'revise_contract', dict(contract=contract(), expected_revision=1, reason='Late')),
        ):
            with self.subTest(action=action):
                error = self.refusal(engine, action, **arguments)
                self.assertEqual(error.code, 'STALE_CONTRACT')
                self.assertIn('revision 3, not 1', error.message)

    def test_unknown_task_lists_the_contract_tasks(self):
        error = self.refusal(self.worker, 'claim_task', task_id='exprot', contract_revision=1, lease_seconds=60)
        self.assertEqual(error.code, 'UNKNOWN_TASK')
        self.assertIn('exprot', error.message)
        self.assertIn('export, doc', error.message)

    def test_missing_lease_and_foreign_lease_are_told_apart(self):
        missing = self.refusal(self.worker, 'submit_artifact', task_id='export', contract_revision=1, path='export.csv')
        self.assertEqual(missing.code, 'LEASE_REQUIRED')
        self.assertIn('claim the task first', missing.message)
        self.worker.execute('claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60))
        foreign = self.refusal(self.other, 'submit_artifact', task_id='export', contract_revision=1, path='export.csv')
        self.assertEqual(foreign.code, 'LEASE_REQUIRED')
        self.assertIn('Another actor holds', foreign.message)
        self.now[0] += 61
        expired = self.refusal(self.worker, 'submit_artifact', task_id='export', contract_revision=1, path='export.csv')
        self.assertIn('claim the task first', expired.message)

    def test_blocked_task_names_the_dependencies_awaiting_acceptance(self):
        error = self.refusal(self.worker, 'claim_task', task_id='doc', contract_revision=1, lease_seconds=60)
        self.assertEqual(error.code, 'DEPENDENCY_BLOCKED')
        self.assertIn('Dependencies need acceptance: export', error.message)

    def test_stale_artifact_tells_absent_outdated_and_wrong_revision_apart(self):
        absent = self.refusal(self.worker, 'run_checks', task_id='export', contract_revision=1, artifact_revision=1)
        self.assertEqual(absent.code, 'STALE_ARTIFACT')
        self.assertIn('no registered artifact', absent.message)
        self.produce()
        wrong = self.refusal(self.worker, 'run_checks', task_id='export', contract_revision=1, artifact_revision=2)
        self.assertIn('at revision 1, not 2', wrong.message)
        self.assertIn('at revision 1, not 2', self.refusal(self.worker, 'read', task_id='export', contract_revision=1, artifact_revision=2).message)
        self.owner.execute('revise_contract', dict(contract=contract(), expected_revision=1, reason='Clarify'))
        outdated = self.refusal(self.worker, 'run_checks', task_id='export', contract_revision=2, artifact_revision=1)
        self.assertEqual(outdated.code, 'STALE_ARTIFACT')
        self.assertIn('registered under contract revision 1', outdated.message)
        self.assertIn('again under revision 2', outdated.message)

    def test_changed_bytes_say_to_register_again(self):
        self.produce()
        (self.root / 'export.csv').write_text('name,amount\nAlice,11\n')
        for action in ('run_checks', 'read'):
            with self.subTest(action=action):
                error = self.refusal(self.worker, action, task_id='export', contract_revision=1, artifact_revision=1)
                self.assertEqual(error.code, 'ARTIFACT_CHANGED')
                self.assertIn('registered artifact revision 1', error.message)
                self.assertIn('register the artifact again', error.message)

    def test_dependency_redecision_says_to_register_again(self):
        self.accept()
        self.produce('doc', 'doc.md')
        self.owner.execute('decide', dict(task_id='export', contract_revision=1, artifact_revision=1, outcome='accepted', reason='Reviewed again'))
        error = self.refusal(self.worker, 'run_checks', task_id='doc', contract_revision=1, artifact_revision=1)
        self.assertEqual(error.code, 'DEPENDENCY_BLOCKED')
        self.assertIn('register the artifact again', error.message)

    def test_second_contract_points_to_revision(self):
        error = self.refusal(self.owner, 'create_contract', **contract())
        self.assertEqual(error.code, 'CONTRACT_EXISTS')
        self.assertIn('revision 1', error.message)
        self.assertIn('revise_contract', error.message)

    def test_cycle_names_a_task_on_it(self):
        cyclic = contract()
        cyclic['tasks'][0]['dependencies'] = ['doc']
        error = self.refusal(self.owner, 'revise_contract', contract=cyclic, expected_revision=1, reason='Loop')
        self.assertEqual(error.code, 'DEPENDENCY_CYCLE')
        self.assertIn('cycle through export', error.message)

    def test_mcp_tool_errors_carry_the_recovery_text(self):
        response = Protocol(self.worker).dispatch(dict(jsonrpc='2.0', id=1, method='tools/call', params=dict(name='rumbo_run_checks', arguments=dict(task_id='export', contract_revision=4, artifact_revision=1))))
        self.assertTrue(response['result']['isError'])
        self.assertIn('STALE_CONTRACT: Contract is at revision 1, not 4', response['result']['content'][0]['text'])


class NonCreatingEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_uninitialized_root_is_refused_and_left_untouched(self):
        with self.assertRaises(RumboError) as caught:
            Engine(self.root, 'maker', 'worker', create=False)
        self.assertEqual(caught.exception.code, 'NO_CONTRACT')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_ledger_removed_after_construction_is_not_recreated(self):
        Engine(self.root, 'owner', 'human').execute('create_contract', contract())
        database = self.root / '.rumbo' / 'state.sqlite3'
        engine = Engine(self.root, 'maker', 'worker', create=False)
        self.assertEqual(engine.snapshot()['project_id'], 'sample')
        database.unlink()
        for attempt in (engine.snapshot, lambda: engine.execute('claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60))):
            with self.assertRaises(RumboError) as caught:
                attempt()
            self.assertEqual(caught.exception.code, 'LEDGER_UNREADABLE')
            self.assertEqual([entry.name for entry in database.parent.iterdir()], [])


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'rumbo', *map(str, args)], text=True, capture_output=True, timeout=10)

    def test_agent_commands_do_not_start_a_ledger_in_an_uninitialized_directory(self):
        claim = json.dumps(dict(task_id='export', contract_revision=1, lease_seconds=60))
        for command in (['state'], ['call', 'claim_task', '--json', claim], ['mcp']):
            with self.subTest(command=command[0]):
                result = self.cli('--root', self.root, *command)
                self.assertEqual(result.returncode, 2)
                self.assertIn('NO_CONTRACT: No project ledger in this root; check the root', result.stderr)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_agent_commands_still_work_on_an_initialized_project(self):
        Engine(self.root, 'owner', 'human').execute('create_contract', contract())
        result = self.cli('--root', self.root, 'state')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['project_id'], 'sample')

    def test_malformed_json_argument_names_its_source(self):
        Engine(self.root, 'owner', 'human').execute('create_contract', contract())
        result = self.cli('--root', self.root, 'call', 'claim_task', '--json', '{task_id: export}')
        self.assertEqual(result.returncode, 2)
        self.assertIn('BAD_INPUT: --json is not one valid JSON value', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_version_matches_the_package(self):
        from rumbo import __version__
        result = self.cli('--version')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'rumbo ' + __version__)


if __name__ == '__main__':
    unittest.main()
