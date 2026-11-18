"""Opt-in wire projection: engine state, authority and full recovery stay unchanged."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from rumbo.core import Engine
from rumbo.installed import InstalledProtocol, installed_tool_definitions
from rumbo.protocol import Protocol, TOOL_SPECS, tool_definitions, mutation_receipt
from rumbo.registry import register_project
from test_core import contract

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = [spec[0] for spec in TOOL_SPECS if not spec[4]]


def request(name, arguments, id=1):
    return dict(jsonrpc='2.0', id=id, method='tools/call', params=dict(name=name, arguments=arguments))


def assert_receipt(case, receipt, state, name, task_id, recovery_args=None):
    task = next(task for task in state['tasks'] if task['id'] == task_id)
    case.assertEqual(receipt['kind'], 'rumbo.mutation_receipt.v1')
    case.assertIs(receipt['complete'], False)
    case.assertEqual(receipt['observation'], 'operation_response_only')
    case.assertEqual(receipt['operation'], name)
    case.assertEqual(receipt['project_id'], state['project_id'])
    case.assertEqual(receipt['contract_revision'], state['contract_revision'])
    case.assertEqual(receipt['task_id'], task_id)
    case.assertEqual(receipt['task_status'], task['status'])
    case.assertIs(receipt['human_decision_recorded'], False)
    artifact = task['artifact']
    case.assertEqual(receipt['artifact'], {key: artifact[key] for key in ('revision', 'contract_revision', 'sha256')} if artifact else None)
    case.assertEqual(receipt['ledger'], dict(events_count=state['events_count'], head=state['ledger_head']))
    case.assertEqual(receipt['recovery'], dict(tool='rumbo_state', arguments=recovery_args or {}))
    for marker in ('Incomplete', 'other tasks', 'evidence and human decisions', 'recorded identity, not fresh verification', 'earlier human decision', 'not cache validity', 'lost response', 'not idempotent', 'not authorization'):
        case.assertIn(marker, receipt['notice'])
    case.assertTrue({'tasks', 'goal', 'requests', 'evidence', 'decisions'}.isdisjoint(receipt))


class MutationReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = 1000
        self.owner = Engine(self.root, 'owner', 'human', clock=lambda: self.now)
        self.worker = Engine(self.root, 'maker', 'worker', clock=lambda: self.now)
        self.reviewer = Engine(self.root, 'reviewer', 'reviewer', clock=lambda: self.now)
        self.owner.execute('create_contract', contract())
        self.protocol = Protocol(self.worker)
        (self.root/'export.csv').write_text('name,amount\nhello,3\n')

    def call(self, name, args, mode='receipt', protocol=None):
        arguments = copy.deepcopy(args)
        if mode is not None:
            arguments['response_mode'] = mode
        before = copy.deepcopy(arguments)
        result = (protocol or self.protocol).dispatch(request(name, arguments))
        self.assertEqual(arguments, before, 'Client arguments must not be consumed/mutated')
        return result['result']

    def test_optional_schema_is_exact_and_sites_catalog_matches(self):
        definitions = tool_definitions(oauth=True)
        for definition in definitions:
            schema = definition['inputSchema']
            self.assertNotIn('response_mode', schema['required'])
            self.assertEqual('response_mode' in schema['properties'], definition['name'] in MUTATIONS)
            if definition['name'] in MUTATIONS:
                self.assertEqual(schema['properties']['response_mode']['enum'], ['snapshot', 'receipt'])
                self.assertFalse(definition['annotations']['idempotentHint'])
                self.assertEqual(definition['securitySchemes'][0]['scopes'], ['rumbo:read', 'rumbo:write'])
        catalog = (ROOT/'openai-sites/worker/base-tools.js').read_text().split('export const baseTools=', 1)[1].strip().removesuffix(';')
        self.assertEqual(json.loads(catalog), [tool for tool in tool_definitions() if tool['name'] != 'rumbo_submit_artifact'])
        for tool in installed_tool_definitions():
            if tool['name'] in ('rumbo_list_projects', 'rumbo_connect_project'):
                self.assertNotIn('response_mode', tool['inputSchema']['properties'])

    def test_invalid_modes_fail_before_every_mutation(self):
        for name, _, _, properties, readonly in TOOL_SPECS:
            if readonly:
                continue
            args = {key: 1 if prop['type'] == 'integer' else 'export' for key, prop in properties.items()}
            for mode in (None, '', 'Receipt', 'compact', 1, False, [], {}, ['receipt']):
                with self.subTest(name=name, mode=mode), patch.object(self.worker, 'execute', side_effect=AssertionError('Must reject before engine')):
                    result = self.protocol.dispatch(request(name, dict(args, response_mode=mode)))['result']
                    self.assertTrue(result['isError'])
                    self.assertIn('BAD_INPUT: response_mode', result['content'][0]['text'])
        self.assertEqual(self.worker.snapshot()['events_count'], 1)
        self.assertFalse((self.root/'.rumbo/artifacts').exists())

    def test_read_board_bind_and_special_tools_reject_irrelevant_flag(self):
        for name, _, _, properties, readonly in TOOL_SPECS:
            if readonly:
                args = {key: 1 if prop['type'] == 'integer' else 'export' for key, prop in properties.items()}
                result = self.call(name, args)
                self.assertTrue(result['isError'])
                self.assertIn('UNKNOWN_FIELD: response_mode', result['content'][0]['text'])
        data = self.root/'plugin-data'; data.mkdir()
        register_project(data, 'sample', self.root)
        installed = InstalledProtocol(data, clock=lambda: self.now)
        for name, args in [('rumbo_list_projects', {}), ('rumbo_connect_project', {'alias':'sample'})]:
            self.assertTrue(self.call(name, args, protocol=installed)['isError'])
        self.assertIsNone(installed.alias)
        self.assertFalse(self.call('rumbo_connect_project', {'alias':'sample'}, mode=None, protocol=installed)['isError'])
        receipt = self.call('rumbo_claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60), protocol=installed)['structuredContent']
        recovered = installed.dispatch(request(receipt['recovery']['tool'], receipt['recovery']['arguments']))['result']['structuredContent']
        assert_receipt(self, receipt, recovered, 'rumbo_claim_task', 'export')

    def workflow(self, mode):
        root = self.root/str(mode); root.mkdir()
        clock = lambda: 1000
        owner = Engine(root, 'owner', 'human', clock=clock)
        maker = Engine(root, 'maker', 'worker', clock=clock)
        reviewer = Engine(root, 'reviewer', 'reviewer', clock=clock)
        c = contract(); c['tasks'][0]['acceptance'].append(dict(id='review', kind='manual_review', prompt='Inspect bytes'))
        c['tasks'].append(dict(id='dependent', title='Dependent', dependencies=['export'], acceptance=[dict(id='header', kind='file_contains', value='name,amount')]))
        owner.execute('create_contract', c)
        (root/'export.csv').write_text('name,amount\nhello,3\n')
        responses, snapshots = [], []
        def do(action, args, engine=maker):
            result = self.call('rumbo_'+action, args, mode=mode, protocol=Protocol(engine))
            self.assertFalse(result['isError'], result)
            state = maker.snapshot()
            if mode == 'receipt':
                assert_receipt(self, result['structuredContent'], state, 'rumbo_'+action, args['task_id'])
                recovery = result['structuredContent']['recovery']
                self.assertEqual(Protocol(maker).dispatch(request(recovery['tool'], recovery['arguments']))['result']['structuredContent'], state)
            else:
                expected = dict(content=[dict(type='text', text='Rumbo project sample, contract revision '+str(state['contract_revision'])+'. 2 tasks. Evidence is not authorization.')], structuredContent=state, isError=False)
                self.assertEqual(json.dumps(result), json.dumps(expected), 'Legacy snapshot serialization must be unchanged')
            responses.append(result); snapshots.append(state)
            return result['structuredContent']
        def human(action, args):
            snapshots.append(owner.execute(action, args))
        claim = dict(task_id='export', contract_revision=1, lease_seconds=300)
        exact = dict(task_id='export', contract_revision=1, artifact_revision=1)
        do('claim_task', claim)
        do('submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv'))
        do('run_checks', exact)
        do('submit_review', dict(exact, check_id='review', outcome='pass', detail='Exact synthetic bytes'), reviewer)
        do('request_decision', dict(task_id='export', question='Accept this revision?'))
        human('decide', dict(exact, outcome='accepted', reason='Owner reviewed exact bytes'))
        accepted = do('request_decision', dict(task_id='export', question='Keep accepted work?'))
        if mode == 'receipt':
            self.assertEqual(accepted['task_status'], 'accepted'); self.assertIs(accepted['human_decision_recorded'], False)
        do('claim_task', dict(claim, task_id='dependent'))
        do('ingest_artifact', dict(task_id='dependent', contract_revision=1, filename='dependent.csv', content='name,amount\nhello,3\n'))
        do('run_checks', dict(exact, task_id='dependent'))
        human('decide', dict(exact, task_id='dependent', outcome='accepted', reason='Dependency accepted'))
        do('submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv'))
        self.assertEqual(snapshots[-1]['tasks'][1]['status'], 'blocked')
        do('run_checks', dict(exact, artifact_revision=2))
        do('submit_review', dict(exact, artifact_revision=2, check_id='review', outcome='pass', detail='Same bytes new revision'), reviewer)
        human('decide', dict(exact, artifact_revision=2, outcome='rejected', reason='Owner chose rejection'))
        human('decide', dict(exact, artifact_revision=2, outcome='accepted', reason='Owner reconsidered'))
        human('revise_contract', dict(contract=c, expected_revision=1, reason='New owner scope'))
        do('request_decision', dict(task_id='export', question='Review changed contract?'))
        do('claim_task', dict(claim, contract_revision=2))
        do('ingest_artifact', dict(task_id='export', contract_revision=2, filename='export.csv', content='name,amount\nhello,9\n'))
        do('run_checks', dict(exact, contract_revision=2, artifact_revision=3))
        do('submit_review', dict(exact, contract_revision=2, artifact_revision=3, check_id='review', outcome='pass', detail='New exact bytes'), reviewer)
        historical = snapshots[-1]['tasks'][0]['decisions']
        self.assertEqual(len(historical), 3)
        restarted = Engine(root, 'maker', 'worker', clock=clock)
        self.assertEqual(restarted.snapshot(), snapshots[-1])
        view = restarted.artifact_view(dict(exact, contract_revision=2, artifact_revision=3))
        self.assertEqual(view['text'], 'name,amount\nhello,9\n')
        self.assertEqual(view['sha256'], hashlib.sha256(view['text'].encode()).hexdigest())
        with sqlite3.connect(root/'.rumbo/state.sqlite3') as db:
            rows = db.execute('SELECT seq,payload,previous,digest FROM events ORDER BY seq').fetchall()
        return responses, snapshots, rows, view

    def test_all_mutations_have_identical_poststate_history_artifacts_and_restart(self):
        default = self.workflow(None)
        explicit = self.workflow('snapshot')
        receipt = self.workflow('receipt')
        self.assertEqual(json.dumps(default), json.dumps(explicit))
        self.assertEqual(default[1:], receipt[1:])

    def test_errors_and_no_writes_are_identical_in_both_modes(self):
        claim = dict(task_id='export', contract_revision=1, lease_seconds=300)
        exact = dict(task_id='export', contract_revision=1, artifact_revision=1)
        self.call('rumbo_claim_task', claim)
        self.call('rumbo_submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv'))
        cases = [
            ('rumbo_claim_task', dict(claim, contract_revision=2), self.protocol, 'STALE_CONTRACT'),
            ('rumbo_run_checks', dict(exact, artifact_revision=2), self.protocol, 'STALE_ARTIFACT'),
            ('rumbo_submit_review', dict(exact, check_id='x', outcome='pass', detail='No reviewer role'), self.protocol, 'FORBIDDEN'),
            ('rumbo_request_decision', dict(task_id='export', question='No write scope'), Protocol(Engine(self.root, 'viewer', 'viewer')), 'FORBIDDEN'),
            ('rumbo_claim_task', dict(claim, role='human'), self.protocol, 'UNKNOWN_FIELD'),
        ]
        (self.root/'export.csv').write_text('corrupt changed bytes')
        cases.append(('rumbo_run_checks', exact, self.protocol, 'ARTIFACT_CHANGED'))
        before = (self.root/'.rumbo/state.sqlite3').read_bytes()
        for name, args, protocol, error in cases:
            results = [self.call(name, args, mode, protocol) for mode in (None, 'snapshot', 'receipt')]
            self.assertEqual(results[0], results[1]); self.assertEqual(results[1], results[2])
            self.assertTrue(results[0]['isError']); self.assertIn(error, results[0]['content'][0]['text'])
        self.assertEqual(before, (self.root/'.rumbo/state.sqlite3').read_bytes())

    def test_receipt_markers_recovery_and_human_boundary_negative_controls(self):
        receipt = self.call('rumbo_claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60))['structuredContent']
        state = self.worker.snapshot()
        for key, value in [('complete', True), ('notice', ''), ('recovery', {'tool':'rumbo_state','arguments':{'role':'human'}}), ('human_decision_recorded', True), ('observation', 'cached_state_valid')]:
            mutant = copy.deepcopy(receipt); mutant[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                assert_receipt(self, mutant, state, 'rumbo_claim_task', 'export')
        for key in ('kind', 'complete', 'recovery', 'notice', 'ledger', 'artifact'):
            mutant = copy.deepcopy(receipt); del mutant[key]
            with self.subTest(missing=key), self.assertRaises((AssertionError, KeyError)):
                assert_receipt(self, mutant, state, 'rumbo_claim_task', 'export')

    def test_ledger_anchor_does_not_validate_cached_lease_or_artifact_projection(self):
        receipt = self.call('rumbo_claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60))['structuredContent']
        self.now = 1060
        expired = self.worker.snapshot()
        self.assertEqual(receipt['ledger']['head'], expired['ledger_head'])
        self.assertEqual(receipt['task_status'], 'claimed'); self.assertEqual(expired['tasks'][0]['status'], 'unclaimed')
        self.call('rumbo_claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60))
        self.call('rumbo_submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv'))
        self.call('rumbo_run_checks', dict(task_id='export', contract_revision=1, artifact_revision=1))
        self.owner.execute('decide', dict(task_id='export', contract_revision=1, artifact_revision=1, outcome='accepted', reason='Reviewed'))
        receipt = self.call('rumbo_request_decision', dict(task_id='export', question='Still accepted?'))['structuredContent']
        (self.root/'export.csv').write_text('drift')
        drifted = self.worker.snapshot()
        self.assertEqual(receipt['ledger']['head'], drifted['ledger_head'])
        self.assertEqual(receipt['task_status'], 'accepted'); self.assertEqual(drifted['tasks'][0]['status'], 'stale')

    def test_structured_receipt_size_is_bounded_not_whole_rpc_envelope(self):
        # Maximum validated identifier/hash widths and conservative legal counters.
        state = dict(project_id='p'*64, contract_revision=10000, events_count=10000,
                     ledger_head='a'*64, tasks=[dict(id='t'*64, status='checks_passed',
                     artifact=dict(revision=10000, contract_revision=10000, sha256='b'*64))])
        value = mutation_receipt('rumbo_request_decision', {'task_id':'t'*64}, state)
        self.assertLess(len(json.dumps(value).encode()), 2048)
        self.assertLess(len(json.dumps(value, separators=(',', ':')).encode()), 2048)
        envelope = dict(jsonrpc='2.0', id='x'*65536, result={'structuredContent':value})
        self.assertGreater(len(json.dumps(envelope).encode()), 65536)

    def test_extracted_installed_launcher_keeps_worker_scope_and_recovers_receipt(self):
        from scripts.package_release import build_local
        archive = self.root/'candidate.zip'
        build_local(ROOT, archive)
        unpacked = self.root/'unpacked'
        with zipfile.ZipFile(archive) as source:
            source.extractall(unpacked)
        plugin = unpacked/'rumbo'
        self.assertEqual((plugin/'rumbo/protocol.py').read_bytes(), (ROOT/'rumbo/protocol.py').read_bytes())
        data = self.root/'plugin-data'; data.mkdir()
        register_project(data, 'sample', self.root)
        requests = [dict(jsonrpc='2.0', id=1, method='tools/list'),
                    request('rumbo_connect_project', {'alias':'sample'}, 2),
                    request('rumbo_request_decision', dict(task_id='export', question='One question', response_mode='receipt'), 3),
                    request('rumbo_state', {}, 4),
                    request('rumbo_submit_review', {}, 5)]
        env = dict(os.environ, PLUGIN_DATA=str(data)); env.pop('PYTHONPATH', None)
        process = subprocess.run([sys.executable, '-I', str(plugin/'scripts/run_mcp.py')], cwd=plugin,
                                 env=env, input=''.join(json.dumps(r)+'\n' for r in requests), text=True,
                                 capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(responses), 5)
        self.assertEqual(responses[0]['result']['tools'], installed_tool_definitions())
        self.assertEqual(responses[1]['result']['structuredContent']['role'], 'worker')
        state = responses[3]['result']['structuredContent']
        assert_receipt(self, responses[2]['result']['structuredContent'], state, 'rumbo_request_decision', 'export')
        self.assertEqual(state['events_count'], 2)
        self.assertEqual(len(state['requests']), 1)
        self.assertEqual(responses[4]['error']['message'], 'Unknown tool')

    def test_actual_stdio_lost_reply_readback_precedes_any_retry(self):
        # One real process commits and emits the response; simulate a consumer losing it.
        args = dict(task_id='export', question='One question only', response_mode='receipt')
        command = [sys.executable, '-m', 'rumbo', '--root', str(self.root), '--actor', 'maker', 'mcp']
        process = subprocess.run(command, input=json.dumps(request('rumbo_request_decision', args))+'\n', text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        receipt = json.loads(process.stdout)['result']['structuredContent']
        recovery = receipt['recovery']
        long_id = 'x'*65536
        process = subprocess.run(command, input=json.dumps(request(recovery['tool'], recovery['arguments'], long_id))+'\n', text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        response = json.loads(process.stdout)
        self.assertEqual(response['id'], long_id)
        self.assertEqual(len(response['result']['structuredContent']['requests']), 1)
        self.assertEqual(response['result']['structuredContent']['events_count'], 2)
        # No replay/retry: read-back shows the write happened despite the lost reply.


if __name__ == '__main__':
    unittest.main()
