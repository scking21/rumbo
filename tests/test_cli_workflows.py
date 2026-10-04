"""Synthetic local CLI workflows and human configuration diagnostics."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ConfigurationDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def assert_invalid_config(self, config, message):
        path = self.base / 'server.json'
        path.write_text(json.dumps(config), encoding='utf-8')
        process = subprocess.run(
            [sys.executable, '-m', 'rumbo', 'serve', '--config', str(path), '--port', '0'],
            text=True, capture_output=True, timeout=5,
        )
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(process.stdout, '')
        self.assertIn(message, process.stderr)
        self.assertNotIn('Traceback', process.stderr)
        self.assertFalse((self.base / '.rumbo').exists())

    def test_non_object_configuration_has_actionable_cli_error(self):
        for config in (None, [], 'development', True, 3):
            with self.subTest(config=config):
                self.assert_invalid_config(config, 'Server configuration must be a JSON object')

    def test_non_object_principal_has_actionable_cli_error_in_each_mode(self):
        for mode in ('development', 'oauth', 'demo'):
            for principal in (None, 'worker', 3, []):
                with self.subTest(mode=mode, principal=principal):
                    self.assert_invalid_config(
                        dict(mode=mode, principals=[principal]),
                        'Each principal must be a JSON object',
                    )

    def test_demo_principal_collection_must_be_a_list(self):
        for principals in (None, 'worker', 3, {}):
            with self.subTest(principals=principals):
                self.assert_invalid_config(
                    dict(mode='demo', principals=principals),
                    'principals must be a list',
                )

    def test_demo_root_must_be_a_configured_path_string(self):
        for root in (True, 3, ['project'], {'root': 'project'}):
            with self.subTest(root=root):
                self.assert_invalid_config(
                    dict(mode='demo', demo_root=root),
                    'demo_root must be a configured path string',
                )

    def test_demo_optional_health_principal_does_not_require_a_bearer_token(self):
        from rumbo.server import create_server
        config = dict(mode='demo', principals=[
            dict(actor='demo-health', role='viewer', root=str(self.base)),
        ])
        server = create_server('127.0.0.1', 0, config)
        self.addCleanup(server.server_close)
        self.assertGreater(server.server_port, 0)


class LocalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def cli(self, *args, module='rumbo'):
        return subprocess.run(
            [sys.executable, '-m', module, *map(str, args)],
            text=True, capture_output=True, timeout=10,
        )

    def success(self, *args, module='rumbo'):
        result = self.cli(*args, module=module)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def test_help_lists_first_run_commands_without_initializing_a_project(self):
        root = self.base / 'empty'
        root.mkdir()
        result = self.cli('--root', root, '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ('demo', 'operator', 'state', 'verify', 'serve'):
            self.assertIn(command, result.stdout)
        self.assertEqual(list(root.iterdir()), [])

    def test_demo_cli_reports_synthetic_states_and_refuses_replacement(self):
        root = self.base / 'synthetic demo'
        state = self.success('--root', root, 'demo')
        self.assertTrue(state['demo'])
        self.assertEqual(state['project_id'], 'synthetic-csv-demo')
        self.assertEqual({task['status'] for task in state['tasks']},
                         {'accepted', 'produced', 'checks_passed', 'stale', 'unclaimed', 'blocked'})
        before = (root / '.rumbo' / 'state.sqlite3').read_bytes()
        result = self.cli('--root', root, 'demo')
        self.assertEqual(result.returncode, 2)
        self.assertIn('Use a new empty folder', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual((root / '.rumbo' / 'state.sqlite3').read_bytes(), before)
        self.assertEqual((root / 'sample.csv').read_text(), 'name,amount\nSynthetic Ada,12\n')

    def test_existing_project_verify_reports_checkpoint_without_changing_history(self):
        root = self.base / 'synthetic demo'
        state = self.success('--root', root, 'demo')
        database = root / '.rumbo' / 'state.sqlite3'
        before = (database.read_bytes(), database.stat().st_mtime_ns)
        checkpoint = self.success('--root', root, 'verify')
        expected = {key: state[key] for key in ('project_id', 'events_count', 'ledger_head', 'integrity')}
        self.assertEqual(checkpoint, expected)
        self.assertEqual((database.read_bytes(), database.stat().st_mtime_ns), before)

    def test_backup_cli_round_trip_preserves_metadata_after_contract_revision(self):
        import sqlite3
        from rumbo.core import Engine
        root = self.base / 'source project'
        root.mkdir()
        owner = Engine(root, 'fixture-owner', 'human')
        worker = Engine(root, 'fixture-maker', 'worker')
        reviewer = Engine(root, 'fixture-reviewer', 'reviewer')
        contract = dict(project_id='metadata-fixture', goal='Retain every recorded context field',
                        original_request='Synthetic request with Unicode: café 日本語',
                        decision_owner='fixture-owner', constraints=['Keep the original context'],
                        tasks=[dict(id='proof', title='Read this proof', dependencies=[],
                                    acceptance=[dict(id='text', kind='file_contains', value='proof'),
                                                dict(id='review', kind='manual_review', prompt='Inspect this text')])])
        owner.execute('create_contract', contract)
        worker.execute('request_decision', dict(task_id='proof', question='Does the original scope still apply?'))
        owner.execute('revise_contract', dict(expected_revision=1, reason='Clarify the synthetic title',
                                             contract=dict(contract, goal='Retain revised and original context')))
        self.success('--root', root, '--actor', 'fixture-maker', 'call', 'claim_task', '--json',
                     json.dumps(dict(task_id='proof', contract_revision=2, lease_seconds=3600)))
        for content in ('old proof', 'new proof café 日本語'):
            self.success('--root', root, '--actor', 'fixture-maker', 'call', 'ingest_artifact', '--json',
                         json.dumps(dict(task_id='proof', contract_revision=2, filename='proof.txt', content=content)))
        self.success('--root', root, '--actor', 'fixture-maker', 'call', 'run_checks', '--json',
                     json.dumps(dict(task_id='proof', contract_revision=2, artifact_revision=2)))
        reviewer.execute('submit_review', dict(task_id='proof', contract_revision=2, artifact_revision=2,
                                              check_id='review', outcome='pass', detail='Synthetic human-readable evidence'))
        owner.execute('decide', dict(task_id='proof', contract_revision=2, artifact_revision=2,
                                    outcome='accepted', reason='Synthetic reviewed approval'))
        before = owner.snapshot()
        archive = self.base / 'metadata backup.zip'
        destination = self.base / 'restored project'
        backed_up = self.success('backup', '--root', root, '--destination', archive, module='rumbo.backup')
        restored = self.success('restore', '--archive', archive, '--destination', destination, module='rumbo.backup')
        for key in ('project_id', 'events_count', 'ledger_head', 'uploaded_blobs', 'external_file_references'):
            self.assertEqual(backed_up[key], restored[key])
        self.assertEqual(backed_up['uploaded_blobs'], 2)
        self.assertEqual(self.success('--root', destination, 'state'), before)
        with sqlite3.connect(root / '.rumbo' / 'state.sqlite3') as original_db:
            original_events = original_db.execute('SELECT * FROM events ORDER BY seq').fetchall()
        with sqlite3.connect(destination / '.rumbo' / 'state.sqlite3') as restored_db:
            self.assertEqual(restored_db.execute('SELECT * FROM events ORDER BY seq').fetchall(), original_events)
        self.assertEqual(Engine(destination, 'fixture-reader', 'viewer').artifact_view(
            dict(task_id='proof', contract_revision=2, artifact_revision=2))['text'], 'new proof café 日本語')
