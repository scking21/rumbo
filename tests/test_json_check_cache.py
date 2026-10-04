"""Each check batch parses its exact artifact once, without caching later actions."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rumbo.core import Engine, artifact_json


class JSONCheckCacheTests(unittest.TestCase):
    def setup_artifact(self, raw, checks=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        checks = checks or [dict(id='json'+str(i), kind='json_equals', key='ok', value=True) for i in range(3)]
        owner = Engine(root, 'owner', 'human', clock=lambda: 1000)
        worker = Engine(root, 'maker', 'worker', clock=lambda: 1000)
        owner.execute('create_contract', dict(project_id='cache', goal='Exact checks', original_request='Check all criteria', decision_owner='owner', constraints=[], tasks=[dict(id='one', title='One', dependencies=[], acceptance=checks)]))
        worker.execute('claim_task', dict(task_id='one', contract_revision=1, lease_seconds=300))
        path = root / 'out.json'
        path.write_bytes(raw)
        worker.execute('submit_artifact', dict(task_id='one', contract_revision=1, path='out.json'))
        return worker, path, checks

    def run_checks(self, worker, revision=1):
        return worker.execute('run_checks', dict(task_id='one', contract_revision=1, artifact_revision=revision))

    def assert_evidence(self, state, raw, checks, outcomes, revision=1):
        expected = []
        for check, outcome in zip(checks, outcomes):
            if check['kind'] == 'manual_review':
                continue
            expected.append(dict(actor='maker', role='worker', contract_revision=1, artifact_revision=revision, artifact_sha256=hashlib.sha256(raw).hexdigest(), at=1000, id='e'+str(state['events_count'])+'-'+check['id'], kind='deterministic', check_id=check['id'], outcome=outcome, detail=check['kind']+' evaluated against the recorded artifact bytes'))
        self.assertEqual(state['tasks'][0]['evidence'][-len(expected):], expected)

    def test_mixed_checks_parse_once_and_keep_every_receipt(self):
        raw = b'{"ok":false,"ok":true,"bad":NaN}'
        checks = [dict(id='bad', kind='json_equals', key='bad', value=0),
                  dict(id='text', kind='file_contains', value='"ok"'),
                  dict(id='good', kind='json_equals', key='ok', value=True),
                  dict(id='review', kind='manual_review', prompt='Inspect'),
                  dict(id='sha', kind='sha256', value=hashlib.sha256(raw).hexdigest()),
                  dict(id='missing', kind='json_equals', key='missing', value=None)]
        worker, _, _ = self.setup_artifact(raw, checks)
        with patch('rumbo.core.artifact_json', wraps=artifact_json) as parser:
            state = self.run_checks(worker)
        self.assert_evidence(state, raw, checks, ['fail', 'pass', 'pass', None, 'pass', 'fail'])
        parser.assert_called_once_with(raw)

    def test_invalid_artifacts_cache_the_failed_parse_and_keep_other_checks(self):
        cases = [b'{"ok":true,}', b'{"ok":true,"unused":"\\ud800","unused":0}',
                 b'{"ok":true,"unused":"\xed\xa0\x80"}',
                 b'{"ok":true,"unused":'+b'['*512+b'0'+b']'*512+b'}',
                 b'{"ok":true,"unused":'+b'9'*4301+b'}']
        for raw in cases:
            with self.subTest(raw=raw[:50]):
                checks = [dict(id='first', kind='json_equals', key='ok', value=True),
                          dict(id='sha', kind='sha256', value=hashlib.sha256(raw).hexdigest()),
                          dict(id='last', kind='json_equals', key='ok', value=True)]
                worker, _, _ = self.setup_artifact(raw, checks)
                with patch('rumbo.core.artifact_json', wraps=artifact_json) as parser:
                    state = self.run_checks(worker)
                self.assert_evidence(state, raw, checks, ['fail', 'pass', 'fail'])
                parser.assert_called_once_with(raw)

    def test_null_and_other_non_object_results_are_still_cached(self):
        for raw in [b'null', b'false', b'1.0', b'[]']:
            with self.subTest(raw=raw):
                worker, _, checks = self.setup_artifact(raw)
                with patch('rumbo.core.artifact_json', wraps=artifact_json) as parser:
                    state = self.run_checks(worker)
                self.assert_evidence(state, raw, checks, ['fail']*3)
                parser.assert_called_once_with(raw)

    def test_later_actions_and_replacements_parse_fresh_bytes(self):
        worker, path, checks = self.setup_artifact(b'{"ok":true}')
        runs = [(1, b'{"ok":true}', 'pass'), (1, b'{"ok":true}', 'pass'),
                (2, b'{"ok":false}', 'fail'), (3, b'{"ok":', 'fail'),
                (4, b'{"ok":true}', 'pass')]
        with patch('rumbo.core.artifact_json', wraps=artifact_json) as parser:
            for index, (revision, raw, outcome) in enumerate(runs):
                if index > 1:
                    path.write_bytes(raw)
                    worker.execute('submit_artifact', dict(task_id='one', contract_revision=1, path='out.json'))
                state = self.run_checks(worker, revision)
                self.assert_evidence(state, raw, checks, [outcome]*3, revision)
                self.assertEqual(parser.call_count, index+1)
                self.assertEqual(parser.call_args.args, (raw,))
                self.assertEqual(len(state['tasks'][0]['evidence']), (index+1)*3)

    def test_no_json_criteria_do_not_parse_artifact(self):
        raw = b'not JSON'
        checks = [dict(id='text', kind='file_contains', value='not JSON'),
                  dict(id='review', kind='manual_review', prompt='Inspect')]
        worker, _, _ = self.setup_artifact(raw, checks)
        with patch('rumbo.core.artifact_json', wraps=artifact_json) as parser:
            state = self.run_checks(worker)
        self.assert_evidence(state, raw, checks, ['pass', None])
        parser.assert_not_called()
