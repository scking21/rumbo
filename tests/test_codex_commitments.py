"""Local packaging/CLI checks, not evidence of installed Codex execution."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from scripts.package_release import build_local, build_submission, build_review_draft, GATES

ROOT = Path(__file__).resolve().parents[1]

class CodexCommitmentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='codex commitments ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        archive = self.base/'local.zip'
        build_local(ROOT, archive)
        with zipfile.ZipFile(archive) as z:
            z.extractall(self.base/'unpacked')
        self.plugin = self.base/'unpacked/rumbo'
        self.record = self.base/'project space/.rumbo/record.json'
    def run_cli(self, *args, input=None):
        return subprocess.run([sys.executable, '-I', '-S', str(self.plugin/'scripts/commitments.py'), *args], input=input, text=True, capture_output=True, cwd=self.base, timeout=10)
    def test_pinned_handoff_uses_the_record_that_is_projected(self):
        import hashlib
        project = self.record.parent.parent
        self.record.parent.mkdir(parents=True)
        row = dict(id='guide', text='Draft available', owner='editor', acceptance='Read draft',
                   status='verified', evidence='Editor read the draft')
        record = dict(version=1, objective=dict(text='Ship the guide', quote='Ship the guide'),
                      target='approved guide', outcomes=[row], items=[], checks=[])
        self.record.write_text(json.dumps(record))
        pin = hashlib.sha256(self.record.read_bytes()).hexdigest()
        args = ('handoff', '--record', str(self.record), '--root', str(project))
        self.assertEqual(self.run_cli(*args, '--reviewed-record-sha256', pin).returncode, 0)
        row['owner'] = 'another editor'
        self.record.write_text(json.dumps(record))
        changed = self.run_cli(*args, '--reviewed-record-sha256', pin)
        self.assertEqual((changed.returncode, changed.stdout), (2, ''))
        self.assertIn('HANDOFF_RECORD_CHANGED', changed.stderr)
        self.assertEqual(json.loads(self.run_cli(*args).stdout)['outcomes'][0]['owner'], 'another editor')
        invalid = self.run_cli(*args, '--reviewed-record-sha256', 'bad')
        self.assertIn('INVALID_REVIEW_DIGEST', invalid.stderr)

    def test_runtime_exact_bytes_and_skill_boundaries(self):
        self.assertEqual((self.plugin/'scripts/_commitments_record.py').read_bytes(), (ROOT/'rumbo/scripts/record.py').read_bytes())
        skill = (self.plugin/'skills/commitments/SKILL.md').read_text()
        for phrase in ['explicit', 'not automatic', 'private session', 'transcript verification', 'CONTINUE', 'BOUNDED']:
            self.assertIn(phrase, skill)
        self.assertFalse((self.plugin/'hooks').exists())
    def test_init_validate_check_show_and_literal_quote(self):
        quote = 'Budget $450; keep `original` text.\n'
        result = self.run_cli('init', '--record', str(self.record), '--objective', 'Preserve decisions', '--quote', '-', input=quote)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('$450', self.record.read_text())
        self.assertIn('`original`', self.record.read_text())
        for command in ['validate', 'check', 'show']:
            result = self.run_cli(command, '--record', str(self.record))
            self.assertEqual(result.returncode, 0, result.stderr+result.stdout)
    def test_denied_hook_and_transcript_surface_no_writes(self):
        for args in [('stop-gate',), ('pre-write',), ('check','--record',str(self.record),'--transcript','private.jsonl'), ('check','--record',str(self.record),'--trans','private.jsonl')]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2, result.stdout+result.stderr)
        self.assertFalse(self.record.exists())
    def test_help_and_missing_record_have_no_initialization(self):
        self.assertEqual(self.run_cli('--help').returncode, 0)
        self.assertEqual(self.run_cli('check').returncode, 2)
        self.run_cli('show', '--record', str(self.record))
        self.assertFalse(self.record.parent.exists())
    def test_check_propagates_results_and_preserves_bytes(self):
        cases = [('Cost $100; budget $500.', 100, 0, 'PASS'),
                 ('Cost $600; budget $500.', 600, 1, 'FAIL'),
                 ('Budget $500.', 100, 1, 'UNSOURCED')]
        self.record.parent.mkdir(parents=True)
        for quote, amount, code, marker in cases:
            record = {'version':1, 'objective':{'text':'Check budget', 'quote':quote},
                      'items':[], 'checks':[{'id':'C1', 'kind':'within_budget',
                          'amounts':[amount], 'total_cap':500, 'refs':[]}]}
            self.record.write_text(json.dumps(record))
            before=self.record.read_bytes()
            result=self.run_cli('check','--record',str(self.record))
            canonical=subprocess.run([sys.executable,'-I','-S',str(ROOT/'rumbo/scripts/record.py'),
                'check','--record',str(self.record)],capture_output=True,text=True,timeout=10)
            self.assertEqual((result.returncode,result.stdout,result.stderr),
                             (canonical.returncode,canonical.stdout,canonical.stderr))
            self.assertEqual(result.returncode,code,result.stdout+result.stderr)
            self.assertIn(marker,result.stdout)
            self.assertEqual(before,self.record.read_bytes())

    def test_packaged_handoff_keeps_runnable_and_blocked_rows_distinct(self):
        target=self.record.parents[1]
        target.mkdir(parents=True)
        artifact=target/'report.txt';artifact.write_text('reviewed report\n')
        import hashlib
        digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
        record={'version':1,'objective':{'text':'Build report and index','quote':'Build report and index.'},
                'target':'the report packet in this project','items':[],'checks':[],
                'outcomes':[
                    {'id':'O1','text':'Report saved','owner':'worker','acceptance':'report.txt has reviewed bytes',
                     'status':'verified','evidence':'read back report.txt',
                     'artifacts':[{'path':'report.txt','sha256':digest}]},
                    {'id':'O2','text':'Index saved','owner':'worker','acceptance':'index.txt names report.txt',
                     'status':'runnable','next_action':'write and read back index.txt'},
                    {'id':'O3','text':'Owner accepts packet','owner':'project owner','acceptance':'owner decision recorded',
                     'status':'blocked','blocker':'owner decision unavailable','restart_trigger':'owner records decision'}]}
        self.record.parent.mkdir(parents=True);self.record.write_text(json.dumps(record))
        result=self.run_cli('handoff','--record',str(self.record),'--root',str(target))
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        report=json.loads(result.stdout)
        self.assertEqual(report['status'],'CONTINUE')
        self.assertEqual(report['outcomes'][0]['artifacts'][0]['state'],'current')
        self.assertEqual(report['outcomes'][1]['next_action'],'write and read back index.txt')
        self.assertEqual(report['outcomes'][2]['restart_trigger'],'owner records decision')
    def test_init_refuses_existing_record_without_overwriting(self):
        self.record.parent.mkdir(parents=True)
        self.record.write_text('user edits must survive')
        result=self.run_cli('init','--record',str(self.record),'--objective','new','--quote','new')
        self.assertEqual(result.returncode,1)
        self.assertIn('RECORD_EXISTS',result.stderr)
        self.assertEqual(self.record.read_text(),'user edits must survive')
    def test_missing_or_symlink_runtime_fails_closed(self):
        runtime=self.plugin/'scripts/_commitments_record.py'
        runtime.unlink()
        decoy=self.base/'rumbo/scripts/record.py'
        decoy.parent.mkdir(parents=True)
        marker=self.base/'decoy-executed'
        decoy.write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("executed")\n')
        for symlink in (False, True):
            if symlink:
                runtime.symlink_to(decoy)
            result=self.run_cli('show','--record',str(self.record))
            self.assertEqual(result.returncode,2,result.stdout+result.stderr)
            self.assertIn('Bundled commitments runtime is missing',result.stderr)
            self.assertFalse(marker.exists())
    def test_show_ignores_hook_stdin_and_never_creates_markers(self):
        state=self.base/'hook state'
        command=[sys.executable,'-I','-S',str(self.plugin/'scripts/commitments.py'),
                 'show','--record',str(self.record)]
        result=subprocess.run(command,input=json.dumps({'session_id':'synthetic-session',
            'prompt':'Plan a workshop schedule and budget'}),text=True,capture_output=True,
            env=dict(os.environ,RUMBO_STATE_DIR=str(state)),timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'')
        self.assertFalse(state.exists())
        self.assertFalse(self.record.exists())
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env=dict(os.environ,RUMBO_STATE_DIR=str(state)))
        try:
            self.assertEqual(process.wait(timeout=3),0)
        finally:
            if process.poll() is None: process.kill();process.wait()
            for stream in (process.stdin,process.stdout,process.stderr):stream.close()
    def test_hosted_packages_exclude_local_commitments(self):
        config = {key:'https://rumbo.company.dev/'+key for key in ['website_url','support_url','privacy_url','terms_url','video_url']}
        config.update(mcp_url='https://rumbo.company.dev/mcp',attestations={g:True for g in GATES})
        for name,builder,args in [('public',build_submission,[config]),('sites',build_review_draft,[{'mcp_url':config['mcp_url']}])]:
            target=self.base/(name+'.zip');builder(ROOT,target,*args)
            with zipfile.ZipFile(target) as z:
                self.assertFalse(any('/skills/commitments/' in n or '/scripts/commitments' in n or '_commitments_record' in n for n in z.namelist()))
