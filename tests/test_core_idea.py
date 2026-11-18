"""Prototype: quoted constraints, per-task staleness, commit artifacts, CI attestations, engine Stop gate."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rumbo.core import Engine, RumboError, task_fingerprint

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT/'rumbo'/'scripts'/'engine_gate.py'
HAS_GIT = shutil.which('git') is not None
REQUEST = 'Export the report as CSV. Keep the column order exactly as it is today. Do not add new dependencies.'


def task(task_id, acceptance, dependencies=()):
    return dict(id=task_id, title='Task ' + task_id, dependencies=list(dependencies), acceptance=acceptance)


def contract(tasks, **extra):
    return dict(project_id='sample', goal='CSV export', original_request=REQUEST, decision_owner='owner',
                constraints=[dict(text='Column order unchanged', quote='Keep the column order exactly as it is today.')],
                tasks=tasks, **extra)


def git(root, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME='Synthetic', GIT_AUTHOR_EMAIL='synthetic@example.invalid',
               GIT_COMMITTER_NAME='Synthetic', GIT_COMMITTER_EMAIL='synthetic@example.invalid')
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.owner = Engine(self.root, 'owner', 'human')
        self.worker = None  # created once the owner's contract starts the ledger

    def start(self, data):
        self.owner.execute('create_contract', data)
        self.worker = Engine(self.root, 'worker', 'worker', create=False)

    def accept_file(self, task_id, name, text='ok'):
        (self.root/name).write_text(text)
        rev = self.owner.snapshot()['contract_revision']
        self.worker.execute('claim_task', dict(task_id=task_id, contract_revision=rev, lease_seconds=300))
        state = self.worker.execute('submit_artifact', dict(task_id=task_id, contract_revision=rev, path=name))
        art = next(t for t in state['tasks'] if t['id'] == task_id)['artifact']['revision']
        self.worker.execute('run_checks', dict(task_id=task_id, contract_revision=rev, artifact_revision=art))
        return self.owner.execute('decide', dict(task_id=task_id, contract_revision=rev, artifact_revision=art, outcome='accepted', reason='Looks right'))


def status(state):
    return {t['id']: t['status'] for t in state['tasks']}


class QuotedConstraintTests(Base):
    def test_quote_must_appear_in_the_original_request(self):
        data = contract([task('a', [dict(id='c', kind='file_contains', value='ok')])])
        data['constraints'].append(dict(text='Any library is fine', quote='Feel free to add any library.'))
        with self.assertRaises(RumboError) as caught:
            self.owner.execute('create_contract', data)
        self.assertEqual(caught.exception.code, 'QUOTE_NOT_IN_REQUEST')

    def test_quote_matches_across_whitespace_and_legacy_strings_still_work(self):
        data = contract([task('a', [dict(id='c', kind='file_contains', value='ok')])])
        data['constraints'] = ['Plain legacy constraint', dict(text='No new deps', quote='Do not add\n  new dependencies.')]
        state = self.owner.execute('create_contract', data)
        self.assertEqual(state['constraints'][1]['quote'], 'Do not add\n  new dependencies.')


class PerTaskStalenessTests(Base):
    def tasks(self):
        return [task('a', [dict(id='c', kind='file_contains', value='ok')]),
                task('b', [dict(id='c', kind='file_contains', value='ok')])]

    def reword_b(self, data):
        changed = copy.deepcopy(data)
        changed['tasks'][1]['title'] = 'Task b, reworded'
        return self.owner.execute('revise_contract', dict(contract=changed, expected_revision=1, reason='Reword b only'))

    def test_default_scope_keeps_whole_contract_staleness(self):
        data = contract(self.tasks())
        self.start(data)
        self.accept_file('a', 'a.txt'); self.accept_file('b', 'b.txt')
        self.assertEqual(status(self.reword_b(data)), {'a': 'stale', 'b': 'stale'})

    def test_task_scope_only_stales_the_changed_task(self):
        data = contract(self.tasks(), revision_scope='task')
        self.start(data)
        self.accept_file('a', 'a.txt'); self.accept_file('b', 'b.txt')
        state = self.reword_b(data)
        self.assertEqual(status(state), {'a': 'accepted', 'b': 'stale'})
        self.assertIn('agreed definition', next(t for t in state['tasks'] if t['id'] == 'b')['stale_reason'])
        # b is redone under the new revision and accepted again; a is untouched.
        self.assertEqual(status(self.accept_file('b', 'b.txt')), {'a': 'accepted', 'b': 'accepted'})

    def test_task_scope_still_stales_everything_when_shared_constraints_change(self):
        data = contract(self.tasks(), revision_scope='task')
        self.start(data)
        self.accept_file('a', 'a.txt'); self.accept_file('b', 'b.txt')
        changed = copy.deepcopy(data); changed['constraints'] = []
        state = self.owner.execute('revise_contract', dict(contract=changed, expected_revision=1, reason='Drop constraint'))
        self.assertEqual(status(state), {'a': 'stale', 'b': 'stale'})

    def test_dropping_task_scope_returns_to_contract_staleness(self):
        data = contract(self.tasks(), revision_scope='task')
        self.start(data)
        self.accept_file('a', 'a.txt')
        changed = copy.deepcopy(data); del changed['revision_scope']
        state = self.owner.execute('revise_contract', dict(contract=changed, expected_revision=1, reason='Back to default'))
        self.assertNotIn('revision_scope', state)
        self.assertEqual(status(state)['a'], 'stale')

    def test_fingerprint_ignores_progress_fields(self):
        data = contract(self.tasks(), revision_scope='task')
        state = self.owner.execute('create_contract', data)
        before = task_fingerprint(state, state['tasks'][0])
        state['tasks'][0]['lease'] = dict(actor='x', expires_at=1, contract_revision=1)
        self.assertEqual(task_fingerprint(state, state['tasks'][0]), before)


@unittest.skipUnless(HAS_GIT, 'git is required for commit artifacts')
class CommitArtifactTests(Base):
    def setUp(self):
        super().setUp()
        git(self.root, 'init', '-q')
        (self.root/'.gitignore').write_text('.rumbo/\n')
        (self.root/'export.py').write_text('COLUMNS = ["id", "name"]\n')
        (self.root/'config.json').write_text('{"format": "csv"}\n')
        git(self.root, 'add', '.'); git(self.root, 'commit', '-qm', 'Add CSV export')
        self.commit = git(self.root, 'rev-parse', 'HEAD')
        self.start(contract([task('export', [
            dict(id='code', kind='file_contains', file='export.py', value='COLUMNS'),
            dict(id='format', kind='json_equals', file='config.json', key='format', value='csv'),
            dict(id='tests', kind='ci_status', name='unit tests'),
        ])]))
        self.ci = Engine(self.root, 'ci-bot', 'ci', create=False)
        self.worker.execute('claim_task', dict(task_id='export', contract_revision=1, lease_seconds=300))

    def submit(self, commit=None):
        return self.worker.execute('submit_commit', dict(task_id='export', contract_revision=1, commit=commit or self.commit))

    def test_commit_records_changed_files_and_checks_read_files_in_the_commit(self):
        state = self.submit()
        artifact = state['tasks'][0]['artifact']
        self.assertEqual((artifact['source'], artifact['commit'], artifact['files']), ('git_commit', self.commit, ['.gitignore', 'config.json', 'export.py']))
        # Editing the working tree does not change what the commit holds.
        (self.root/'export.py').write_text('nothing\n')
        state = self.worker.execute('run_checks', dict(task_id='export', contract_revision=1, artifact_revision=1))
        outcomes = {e['check_id']: e['outcome'] for e in state['tasks'][0]['evidence']}
        self.assertEqual(outcomes, {'code': 'pass', 'format': 'pass'})
        self.assertEqual(state['tasks'][0]['status'], 'produced')  # CI has not attested yet

    def test_ci_attestation_completes_acceptance_for_the_exact_commit_only(self):
        self.submit()
        self.worker.execute('run_checks', dict(task_id='export', contract_revision=1, artifact_revision=1))
        attest = dict(task_id='export', contract_revision=1, artifact_revision=1, check_id='tests', outcome='pass', detail='https://ci.example.invalid/run/1')
        with self.assertRaises(RumboError) as wrong:
            self.ci.execute('attest_ci', dict(attest, commit='0' * 40))
        self.assertEqual(wrong.exception.code, 'STALE_ARTIFACT')
        for actor in (self.worker, Engine(self.root, 'rev', 'reviewer', create=False)):
            with self.assertRaises(RumboError) as forbidden:
                actor.execute('attest_ci', dict(attest, commit=self.commit))
            self.assertEqual(forbidden.exception.code, 'FORBIDDEN')
        with self.assertRaises(RumboError) as ci_only:
            self.ci.execute('run_checks', dict(task_id='export', contract_revision=1, artifact_revision=1))
        self.assertEqual(ci_only.exception.code, 'FORBIDDEN')
        state = self.ci.execute('attest_ci', dict(attest, commit=self.commit))
        self.assertEqual(state['tasks'][0]['status'], 'checks_passed')
        evidence = state['tasks'][0]['evidence'][-1]
        self.assertEqual((evidence['kind'], evidence['commit'], evidence['actor']), ('ci_attestation', self.commit, 'ci-bot'))
        state = self.owner.execute('decide', dict(task_id='export', contract_revision=1, artifact_revision=1, outcome='accepted', reason='CI green'))
        self.assertEqual(state['tasks'][0]['status'], 'accepted')

    def test_unknown_or_short_commits_and_private_check_files_are_refused(self):
        for commit, code in (('abc123', 'BAD_INPUT'), ('f' * 40, 'GIT_OBJECT_MISSING')):
            with self.assertRaises(RumboError) as caught:
                self.submit(commit)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(RumboError) as private:
            self.owner.execute('revise_contract', dict(expected_revision=1, reason='x', contract=contract([task('export', [
                dict(id='env', kind='file_contains', file='.env', value='x')])])))
        self.assertEqual(private.exception.code, 'PATH_PRIVATE')

    def test_file_checks_on_a_single_file_artifact_fail_instead_of_reading_elsewhere(self):
        self.owner.execute('revise_contract', dict(expected_revision=1, reason='file artifact', contract=contract([task('export', [
            dict(id='code', kind='file_contains', file='export.py', value='COLUMNS')])])))
        self.worker.execute('claim_task', dict(task_id='export', contract_revision=2, lease_seconds=300))
        self.worker.execute('submit_artifact', dict(task_id='export', contract_revision=2, path='export.py'))
        state = self.worker.execute('run_checks', dict(task_id='export', contract_revision=2, artifact_revision=1))
        self.assertEqual(state['tasks'][0]['evidence'][-1]['outcome'], 'fail')


class EngineGateTests(Base):
    def run_gate(self, hook):
        env = dict(os.environ, RUMBO_STATE_DIR=str(self.root/'gate-state'))
        result = subprocess.run(['python3', str(GATE), '--project', str(self.root)], input=json.dumps(hook),
                                text=True, capture_output=True, env=env, timeout=20)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return json.loads(result.stdout) if result.stdout else None

    def test_silent_without_a_ledger(self):
        empty = tempfile.TemporaryDirectory(); self.addCleanup(empty.cleanup)
        result = subprocess.run(['python3', str(GATE), '--project', empty.name], input='{}', text=True, capture_output=True, timeout=20)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertFalse((Path(empty.name)/'.rumbo').exists())

    def test_blocks_when_accepted_work_goes_stale_then_stops_after_three(self):
        self.start(contract([task('a', [dict(id='c', kind='file_contains', value='ok')])]))
        self.accept_file('a', 'a.txt')
        self.assertIsNone(self.run_gate({'session_id': 's1'}))
        (self.root/'a.txt').write_text('ok, but edited after acceptance')
        for _ in range(3):
            blocked = self.run_gate({'session_id': 's1'})
            self.assertEqual(blocked['decision'], 'block')
            self.assertIn('ACCEPTANCE_LOST a', blocked['reason'])
            self.assertIn('Artifact bytes changed', blocked['reason'])
        self.assertIsNone(self.run_gate({'session_id': 's1'}))
        # Without a session id it defers to stop_hook_active, so it never loops.
        self.assertEqual(self.run_gate({})['decision'], 'block')
        self.assertIsNone(self.run_gate({'stop_hook_active': True}))

    @unittest.skipUnless(HAS_GIT, 'git is required for working-tree changes')
    def test_blocks_on_changes_while_no_task_is_claimed(self):
        git(self.root, 'init', '-q')
        (self.root/'.gitignore').write_text('.rumbo/\ngate-state/\n')
        git(self.root, 'add', '.'); git(self.root, 'commit', '-qm', 'init')
        self.start(contract([task('a', [dict(id='c', kind='file_contains', value='ok')])]))
        self.assertIsNone(self.run_gate({'session_id': 's2'}))
        (self.root/'unplanned.py').write_text('print(1)\n')
        blocked = self.run_gate({'session_id': 's2'})
        self.assertIn('UNCLAIMED_CHANGES: files changed while no task is claimed: unplanned.py', blocked['reason'])
        # A claimed task covers in-progress changes.
        self.worker.execute('claim_task', dict(task_id='a', contract_revision=1, lease_seconds=300))
        self.assertIsNone(self.run_gate({'session_id': 's2'}))


if __name__ == '__main__':
    unittest.main()
