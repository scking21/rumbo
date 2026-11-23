"""Local Engine/CLI: question observation is optional context, never authority."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from rumbo.core import Engine, RumboError

def notebook():
    def task(tid, title, *deps):
        return dict(id=tid, title=title, dependencies=list(deps),
                    acceptance=[dict(id='content', kind='file_contains', value='chapter')])
    return dict(project_id='notebook', goal='Prepare sample notes',
                original_request='Prepare an outline and an index.', decision_owner='editor',
                constraints=['Sample-only notebook'], revision_scope='task',
                tasks=[task('outline', 'Outline for the short chapter', 'notes'),
                       task('index', 'Index for the short chapter'), task('notes', 'Notes', 'source'),
                       task('source', 'Source notes')])

class QuestionObservationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.owner = Engine(self.root, 'editor', 'human', clock=lambda: 1000)
        self.worker = Engine(self.root, 'scribe', 'worker', clock=lambda: 1000, create=False)
        self.contract = notebook()
        self.owner.execute('create_contract', self.contract)
        self.obs, self.q = self.compose()
    def compose(self):
        s = self.worker.observe_question('outline', related_task_ids=[])
        t = next(t for t in s['tasks'] if t['id']=='outline')
        return s['question_observation'], 'Does this wording fit: '+t['title']+'?'
    def events(self):
        with sqlite3.connect(self.worker.db_path.as_uri()+'?mode=ro', uri=True) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            return db.execute('SELECT seq,payload,previous,digest FROM events ORDER BY seq').fetchall()
    def revise(self, change):
        rev = self.owner.snapshot()['contract_revision']
        updated = copy.deepcopy(self.contract)
        change(updated)
        self.owner.execute('revise_contract', dict(contract=updated, expected_revision=rev, reason='Edit notes'))
        self.contract = updated
    def ask(self, obs=None, *, code=None):
        obs = self.obs if obs is None else obs
        before = self.events()
        args = dict(task_id='outline', question=self.q, observation=obs)
        if code:
            with self.assertRaises(RumboError) as err:
                self.worker.execute('request_decision', args)
            self.assertEqual(err.exception.code, code)
            self.assertEqual(self.events(), before)
        else:
            result = self.worker.execute('request_decision', args)
            after = self.events()
            self.assertEqual(after[:-1], before)
            data = json.loads(after[-1][1])['data']
            self.assertEqual(data['observation'], obs)
            self.assertEqual(data['question'], self.q)
            self.assertEqual(data['contract_revision'], result['contract_revision'])
            self.assertFalse(any(t['decisions'] for t in result['tasks']))
            self.assertEqual(after[-1][-1], Engine(self.root, 'verify', 'viewer', read_only=True, create=False).checkpoint()['ledger_head'])
    def test_unchanged(self):
        self.ask()
    def test_disjoint_question(self):
        self.worker.execute('request_decision', dict(task_id='index', question='Alphabetize?'))
        self.ask()
    def test_sibling_contract_edit(self):
        self.revise(lambda c: c['tasks'][1].update(title='Updated index'))
        self.ask()
    def test_target_revision_rejects_then_recomposition_works(self):
        self.revise(lambda c: c['tasks'][0].update(title='Updated outline'))
        self.ask(code='STALE_QUESTION')
        self.obs, self.q = self.compose()
        self.ask()
    def test_indirect_prerequisite_definition_change(self):
        self.revise(lambda c: c['tasks'][3].update(title='A new source'))
        self.ask(code='STALE_QUESTION')
    def test_reverted_task_change_is_not_continuous(self):
        original = self.contract['tasks'][0]['title']
        self.revise(lambda c: c['tasks'][0].update(title='Other outline'))
        self.revise(lambda c: c['tasks'][0].update(title=original))
        self.ask(code='STALE_QUESTION')
    def test_recreated_task_requires_fresh_observation(self):
        orig = copy.deepcopy(self.contract['tasks'][0])
        self.revise(lambda c: c['tasks'].pop(0))
        self.ask(code='STALE_QUESTION')
        self.revise(lambda c: c['tasks'].insert(0, orig))
        self.ask(code='STALE_QUESTION')
    def test_changed_original_request_changes_context(self):
        self.revise(lambda c: c.update(original_request='Draft rather than finalize the notes'))
        self.ask(code='STALE_QUESTION')
    def test_restored_author_text_changes_context(self):
        request = self.contract['original_request']
        self.revise(lambda c: c.update(original_request='New instructions'))
        self.revise(lambda c: c.update(original_request=request))
        self.ask(code='STALE_QUESTION')
    def test_prerequisite_lineage_not_only_status(self):
        self.worker.execute('claim_task', dict(task_id='source', contract_revision=1, lease_seconds=30))
        reg = dict(task_id='source', contract_revision=1, filename='s.txt', content='chapter')
        self.worker.execute('ingest_artifact', reg)
        self.obs, self.q = self.compose()
        self.worker.execute('ingest_artifact', reg)
        self.ask(code='STALE_QUESTION')
    def test_task_project_anchor_and_shape(self):
        for key, value, code in [('project_id','different','STALE_QUESTION'),('task_id','index','STALE_QUESTION'),
                                ('ledger_head','a'*64,'STALE_QUESTION'),('context_sha256','b'*64,'STALE_QUESTION'),
                                ('events_count',10,'STALE_QUESTION'),('events_count',True,'BAD_INPUT')]:
            with self.subTest(key=key, value=value):
                self.ask(dict(self.obs, **{key:value}), code=code)
    def test_default_path_does_not_claim_a_checked_observation(self):
        self.revise(lambda c: c['tasks'][0].update(title='Changed'))
        self.assertNotIn('question_observation', self.worker.snapshot())
        result = self.worker.execute('request_decision', dict(task_id='outline', question=self.q))
        self.assertNotIn('observation', result['requests'][0])
    def test_real_cli(self):
        command = [sys.executable, '-B', '-m', 'rumbo', '--root', str(self.root), '--actor', 'scribe']
        def run(*args):
            return subprocess.run(command+list(args), text=True, capture_output=True, cwd=Path(__file__).resolve().parents[1], timeout=15)
        r = run('state', '--question-task', 'outline', '--declare-question-context')
        self.assertEqual(r.returncode, 0, r.stderr)
        obs = json.loads(r.stdout)['question_observation']
        args = ['call','request_decision','--json',json.dumps(dict(task_id='outline', question=self.q, observation=obs))]
        self.revise(lambda c: c['tasks'][1].update(title='Index only'))
        r = run(*args); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['requests'][-1]['observation'], obs)
        self.revise(lambda c: c['tasks'][0].update(title='Outline changed'))
        before = self.events()
        r = run(*args); self.assertEqual(r.returncode, 2); self.assertIn('STALE_QUESTION', r.stderr)
        self.assertEqual(self.events(), before)

    def test_contending_writer_uses_post_commit_context(self):
        # The real owner/worker hold separate SQLite connections. Pause the owner after
        # preparing its genuine change under BEGIN IMMEDIATE. Release it only when the
        # question writer's connection actually traces the competing BEGIN IMMEDIATE.
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import contextmanager
        import threading
        for name, idx, expected in [('sibling', 1, 'OK'), ('target', 0, 'STALE_QUESTION')]:
            with self.subTest(name=name):
                owner_locked, begin_attempt = threading.Event(), threading.Event()
                class PausedOwner(Engine):
                    def _prepare(self, action, args, state, now):
                        result = super()._prepare(action, args, state, now)
                        owner_locked.set()
                        if not begin_attempt.wait(5):
                            raise AssertionError('question never attempted its write transaction')
                        return result
                class TracedWorker(Engine):
                    @contextmanager
                    def _db(self):
                        with super()._db() as db:
                            db.set_trace_callback(lambda sql: begin_attempt.set() if sql == 'BEGIN IMMEDIATE' else None)
                            yield db
                before = self.events()
                rev = self.owner.snapshot()['contract_revision']
                self.contract['tasks'][idx]['title'] = 'New '+name
                owner = PausedOwner(self.root,'editor','human',create=False)
                worker = TracedWorker(self.root,'scribe','worker',create=False)
                self.obs, self.q = self.compose()
                with ThreadPoolExecutor(2) as pool:
                    edit = pool.submit(owner.execute, 'revise_contract',
                                       dict(expected_revision=rev, reason='Contended edit', contract=self.contract))
                    self.assertTrue(owner_locked.wait(5))
                    submit = pool.submit(worker.execute,'request_decision',dict(task_id='outline', question=self.q, observation=self.obs))
                    edit.result(timeout=8)
                    if expected=='OK':
                        self.assertEqual(submit.result(timeout=8)['requests'][-1]['observation'], self.obs)
                    else:
                        with self.assertRaises(RumboError) as caught:
                            submit.result(timeout=8)
                        self.assertEqual(caught.exception.code, expected)
                after = self.events()
                self.assertEqual(after[:len(before)], before)
                actions = [json.loads(r[1])['action'] for r in after[len(before):]]
                self.assertEqual(actions, ['revise_contract']+(['request_decision'] if expected=='OK' else []))

    def test_unscoped_default_holds_changed_sibling_mentioned_in_question(self):
        s = self.worker.observe_question('outline')
        self.assertEqual(s['question_observation']['scope'], {'mode':'whole_project'})
        self.q = 'Use this reference title: '+s['tasks'][1]['title']+'?'
        self.revise(lambda c: c['tasks'][1].update(title='New index'))
        self.ask(s['question_observation'], code='STALE_QUESTION')

    def test_conservative_default_accepts_unchanged_project(self):
        s = self.worker.observe_question('outline')
        self.ask(s['question_observation'])

    def test_named_extra_context_holds_non_dependency_reference(self):
        s = self.worker.observe_question('outline', related_task_ids=['index'])
        self.assertEqual(s['question_observation']['scope'], {'mode':'declared_tasks','related_task_ids':['index']})
        self.q = 'Can I use the index heading '+s['tasks'][1]['title']+'?'
        self.revise(lambda c: c['tasks'][1].update(title='Rewritten index'))
        self.ask(s['question_observation'], code='STALE_QUESTION')

    def test_cannot_drop_extra_context_from_existing_token(self):
        obs = self.worker.observe_question('outline', related_task_ids=['index'])['question_observation']
        obs['scope']['related_task_ids'] = []
        self.ask(obs, code='STALE_QUESTION')

    def test_false_context_declaration_is_not_semantic_verification(self):
        # The engine cannot infer hidden references: deliberately underdeclared input.
        s = self.worker.observe_question('outline', related_task_ids=[])
        self.q = 'Use the index heading '+s['tasks'][1]['title']+'?'
        self.revise(lambda c: c['tasks'][1].update(title='New index'))
        self.ask(s['question_observation'])
