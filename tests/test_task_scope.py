"""Per-task staleness (revision_scope "task") and the engine Stop gate for lost acceptance."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from rumbo.core import Engine, task_fingerprint

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT/'rumbo'/'scripts'/'engine_gate.py'
REQUEST = 'Export the report as CSV. Keep the column order exactly as it is today. Do not add new dependencies.'


def task(task_id, acceptance, dependencies=()):
    return dict(id=task_id, title='Task ' + task_id, dependencies=list(dependencies), acceptance=acceptance)


def contract(tasks, **extra):
    return dict(project_id='sample', goal='CSV export', original_request=REQUEST, decision_owner='owner',
                constraints=['Column order unchanged'],
                tasks=tasks, **extra)


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
        b = next(t for t in state['tasks'] if t['id'] == 'b')
        self.assertIn('agreed definition', b['stale_reason'])
        # The current fingerprint is exposed, so readers can mark b's old records as historical.
        self.assertNotEqual(b['task_fingerprint'], b['artifact']['task_fingerprint'])
        self.assertTrue(all(e['task_fingerprint'] != b['task_fingerprint'] for e in b['evidence'] + b['decisions']))
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

    def test_reports_lost_acceptance_once_per_session(self):
        self.start(contract([task('a', [dict(id='c', kind='file_contains', value='ok')])]))
        self.accept_file('a', 'a.txt')
        self.assertIsNone(self.run_gate({'session_id': 's1'}))
        (self.root/'a.txt').write_text('ok, but edited after acceptance')
        blocked = self.run_gate({'session_id': 's1'})
        self.assertIn('ACCEPTANCE_LOST a', blocked['reason'])
        self.assertIn('Artifact bytes changed', blocked['reason'])
        self.assertIn('python3 -m rumbo --root', blocked['reason'])
        # The agent cannot restore acceptance itself, so the same problem is not reported again.
        self.assertIsNone(self.run_gate({'session_id': 's1'}))
        (self.root/'a.txt').write_text('ok')
        self.assertIsNone(self.run_gate({'session_id': 's1'}))
        (self.root/'a.txt').write_text('edited again')
        self.assertIsNone(self.run_gate({'session_id': 's1'}))
        # Another session hears about it once too.
        self.assertIn('ACCEPTANCE_LOST a', self.run_gate({'session_id': 's9'})['reason'])
        # Without a session id it defers to stop_hook_active, so it never loops.
        self.assertEqual(self.run_gate({})['decision'], 'block')
        self.assertIsNone(self.run_gate({'stop_hook_active': True}))

    def test_a_session_gets_at_most_three_blocks(self):
        names = ['a', 'b', 'c', 'd']
        self.start(contract([task(n, [dict(id='c', kind='file_contains', value='ok')]) for n in names]))
        for n in names:
            self.accept_file(n, n + '.txt')
        found = []
        for n in names:
            (self.root/(n + '.txt')).write_text('ok, edited')
            found.append(self.run_gate({'session_id': 's3'}))
        self.assertEqual([bool(b) for b in found], [True, True, True, False])

    def test_edits_outside_the_contract_do_not_block(self):
        self.start(contract([task('a', [dict(id='c', kind='file_contains', value='ok')])]))
        self.accept_file('a', 'a.txt')
        (self.root/'CONTRIBUTING.md').write_text('A typo fix the user asked for\n')
        self.assertIsNone(self.run_gate({'session_id': 's2'}))


if __name__ == "__main__":
    unittest.main()
