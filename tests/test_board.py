"""Acceptance board security, behavior, and MCP Apps protocol regression tests.

Static tests need only Python. Browser tests run when Playwright and Chromium are
already installed, and otherwise skip without adding runtime dependencies.
"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOARD = Path(__file__).resolve().parents[1] / 'rumbo/web/board.html'
STATE = {
    'version': 1, 'project_id': 'checkout', 'goal': 'Ship a trustworthy checkout',
    'original_request': 'Make checkout auditable.', 'decision_owner': 'Maya Chen',
    'contract_revision': 3, 'constraints': ['Keep payment data private'],
    'events_count': 18, 'ledger_head': 'a' * 64, 'integrity': {'valid': True}, 'demo': True,
    'tasks': [
        {'id': 'totals', 'title': 'Validate checkout totals', 'status': 'checks_passed',
         'contract_revision': 3, 'dependencies': [], 'lease': None,
         'acceptance': [{'id': 'numeric', 'kind': 'json_equals', 'description': 'Totals match invoice'},
                        {'id': 'review', 'kind': 'review', 'description': 'Reviewer checks edge cases'}],
         'artifact': {'revision': 2, 'path': 'checkout.py', 'sha256': 'b' * 64, 'size': 512, 'maker': 'Builder'},
         'evidence': [{'id': 'e1', 'kind': 'deterministic', 'check_id': 'numeric', 'outcome': 'pass',
                      'actor': 'Rumbo checker', 'role': 'system', 'artifact_revision': 2,
                      'contract_revision': 3, 'detail': {'expected_total': 125, 'actual_total': 125}, 'at': '2026-10-01T03:00:00Z'},
                     {'id': 'e2', 'kind': 'reviewer_assertion', 'check_id': 'review', 'outcome': 'pass',
                      'actor': 'Priya', 'role': 'reviewer', 'artifact_revision': 2, 'contract_revision': 3,
                      'detail': 'I checked zero quantity and discounts.', 'at': '2026-10-01T03:01:00Z'}],
         'decisions': [], 'stale_reason': None},
        {'id': 'receipt', 'title': 'Publish purchase receipt', 'status': 'accepted',
         'contract_revision': 3, 'dependencies': [], 'acceptance': [], 'lease': None,
         'artifact': {'revision': 1, 'path': 'receipt.txt', 'sha256': 'c' * 64, 'size': 90, 'maker': 'Builder'},
         'evidence': [], 'decisions': [{'id': 'd1', 'outcome': 'accept', 'actor': 'Maya Chen',
          'reason': 'Meets the contract.', 'artifact_revision': 1, 'contract_revision': 3,
          'at': '2026-10-01T03:02:00Z'}], 'stale_reason': None},
        {'id': 'retry', 'title': 'Harden retry behavior', 'status': 'stale', 'contract_revision': 3,
         'dependencies': ['totals'], 'acceptance': [], 'artifact': None, 'lease': None,
         'evidence': [], 'decisions': [], 'stale_reason': 'Contract changed after prior review'}
    ]
}

class BoardSourceTests(unittest.TestCase):
    def source(self):
        self.assertTrue(BOARD.is_file(), 'The acceptance board HTML must exist')
        return BOARD.read_text()

    def test_self_contained_and_no_html_injection_sinks(self):
        source = self.source()
        self.assertNotRegex(source, r'<(?:script|link|img)\b[^>]*(?:src|href)\s*=')
        self.assertNotRegex(source, r'\b(?:innerHTML|outerHTML|insertAdjacentHTML|eval)\b')
        self.assertNotIn('document.write', source)
        self.assertIn('textContent', source)
        self.assertIn('Content-Security-Policy', source)

    def test_no_approval_or_write_tools(self):
        source = self.source()
        self.assertIn('rumbo_state', source)
        self.assertNotRegex(source, r'rumbo_(?:accept|reject|decide|claim|produce|check|assert)')
        self.assertNotRegex(source, r'method:\s*[\"\x27](?:POST|PUT|PATCH|DELETE)')

    def test_protocol_and_accessibility_hooks(self):
        source = self.source()
        for token in ['ui/initialize', 'ui/notifications/initialized', 'ui/notifications/tool-result',
                      'ui/notifications/size-changed', 'ui/notifications/host-context-changed',
                      'event.source !== window.parent', 'aria-live', 'aria-pressed',
                      'prefers-reduced-motion', '2026-01-26']:
            self.assertIn(token, source)

NODE_HARNESS = r"""
const vm = require('node:vm'), fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0,'utf8'));
class Element {
  constructor(tag) {this.tagName=tag;this.children=[];this.value='';this.hidden=false;this.dataset={};this.attrs={};this.handlers={};this._text='';}
  set textContent(s) {this._text=String(s);this.children=[];}
  get textContent() {return this._text+this.children.map(c=>c.textContent).join('\n');}
  get childNodes(){return this.children;}
  append(...kids){this.children.push(...kids);}
  replaceChildren(...kids){this.children=[];this._text='';this.append(...kids);}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,fn){this.handlers[k]=fn;}
  getBoundingClientRect(){return {width:1000,height:900};}
  focus(){this.focused=true;} select(){this.selected=true;}
}
const nodes={};
for(const id of ['goal','demo','refresh','error','integrity','contract-revision','decision-owner','accepted-count','review-count','attention-count','context-body','contract-context','connection','ledger','task-list','list-empty','task-detail','status-filter'])nodes[id]=new Element('div');
nodes['status-filter'].value='all';
function findId(node,id){return node.id===id?node:node.children.map(c=>findId(c,id)).find(Boolean);}
const document={documentElement:new Element('html'),body:new Element('body'),createElement:tag=>new Element(tag),createDocumentFragment:()=>new Element('fragment'),getElementById:id=>nodes[id]||Object.values(nodes).map(n=>findId(n,id)).find(Boolean)};
const messages=[],fetches=[];let listener;const window={addEventListener:(name,fn)=>{if(name==='message')listener=fn},removeEventListener:()=>{}};
const parent={postMessage:message=>{
  messages.push(message);
  if(message.method==='ui/initialize')queueMicrotask(()=>listener({source:parent,origin:'https://host.test',data:{jsonrpc:'2.0',id:message.id,result:{protocolVersion:input.unsupported?'1900-01-01':'2026-01-26',hostCapabilities:{serverTools:{}},hostContext:{theme:'light'}}}}));
  if(message.method==='ui/notifications/initialized')queueMicrotask(()=>listener({source:parent,origin:'https://host.test',data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:input.state}}}));
  if(message.method==='tools/call')queueMicrotask(()=>listener({source:parent,origin:'https://host.test',data:{jsonrpc:'2.0',id:message.id,result:{structuredContent:input.state}}}));
}};
window.parent=input.embedded?parent:window;
const context={document,window,console,Set,Map,Date,Error,String,Number,Array,Object,Promise,JSON,AbortController,
  setTimeout:(fn,ms)=>{const id=setTimeout(fn,ms);id.unref();return id},clearTimeout,
  navigator:{clipboard:{writeText:async v=>{context.copied=v}}},
  ResizeObserver:class{observe(){}disconnect(){}},fetch:async url=>{fetches.push(url);return {ok:true,json:async()=>input.state}}};
vm.runInNewContext(input.script,context);
setImmediate(async()=>{
  if(input.action==='refresh')await nodes.refresh.handlers.click();
  if(input.action==='filter') {nodes['status-filter'].value='attention';nodes['status-filter'].handlers.change();}
  if(input.action==='spoof')listener({source:window,origin:'https://host.test',data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{version:1,goal:'FORGED',tasks:[]}}}});
  if(input.action==='copy') {const seek=n=>n.tagName==='button'&&n.textContent==='Copy handoff'?n:n.children.map(seek).find(Boolean);await seek(nodes['task-detail']).handlers.click();}
  if(input.action==='refresh_error'){context.fetch=async()=>({ok:false,status:503});await nodes.refresh.handlers.click();}
  const out={texts:Object.fromEntries(Object.entries(nodes).map(([k,v])=>[k,v.textContent])),demoHidden:nodes.demo.hidden,errorHidden:nodes.error.hidden,messages,fetches,copied:context.copied};
  process.stdout.write(JSON.stringify(out));
});
"""

@unittest.skipUnless(shutil.which('node'), 'Node not installed; static tests still run')
class BoardRuntimeTests(unittest.TestCase):
    def run_ui(self, state=None, **options):
        source = BOARD.read_text()
        script = re.search(r'<script>(.*?)</script>', source, re.S).group(1)
        result = subprocess.run(['node','-e',NODE_HARNESS],input=json.dumps({'script':script,'state':state or copy.deepcopy(STATE),**options}), text=True,capture_output=True,check=True)
        return json.loads(result.stdout)

    def test_runtime_renders_provenance_demo_and_classified_review(self):
        result = self.run_ui()
        detail = result['texts']['task-detail']
        self.assertIn('Assertion by Priya', detail)
        self.assertNotIn('Unrecognized evidence', detail)
        self.assertIn('Awaiting Maya Chen', detail)
        self.assertEqual(result['fetches'], ['/api/state'])
        self.assertFalse(result['demoHidden'])

    def test_uploaded_source_is_not_presented_as_repository_provenance(self):
        state=copy.deepcopy(STATE);state['tasks'][0]['artifact']['source']='uploaded_text'
        result=self.run_ui(state=state)
        self.assertIn('Uploaded text: received bytes only',result['texts']['task-detail'])

    def test_repeated_checks_mark_old_acceptance_not_current(self):
        from rumbo.core import Engine
        from test_core import contract
        with tempfile.TemporaryDirectory() as root:
            owner=Engine(root,'owner','human');maker=Engine(root,'maker','worker')
            owner.execute('create_contract',contract())
            maker.execute('claim_task',dict(task_id='export',contract_revision=1,lease_seconds=60))
            maker.execute('ingest_artifact',dict(task_id='export',contract_revision=1,filename='file.csv',content='name,amount'))
            maker.execute('run_checks',dict(task_id='export',contract_revision=1,artifact_revision=1))
            owner.execute('decide',dict(task_id='export',contract_revision=1,artifact_revision=1,outcome='accepted',reason='Reviewed'))
            state=maker.execute('run_checks',dict(task_id='export',contract_revision=1,artifact_revision=1))
            self.assertEqual(state['tasks'][0]['status'],'checks_passed')
            result=self.run_ui(state=state)
            self.assertIn('Not current acceptance',result['texts']['task-detail'])

    def test_runtime_bridge_handshake_initial_delivery_and_refresh(self):
        result = self.run_ui(embedded=True)
        self.assertEqual(result['texts']['goal'], STATE['goal'])
        self.assertEqual(result['fetches'], [])
        self.assertEqual([m['method'] for m in result['messages']], ['ui/initialize','ui/notifications/initialized'])
        result = self.run_ui(embedded=True,action='refresh')
        call = [m for m in result['messages'] if m['method']=='tools/call'][0]
        self.assertEqual(call['params'], {'name':'rumbo_state','arguments':{}})

    def test_runtime_rejects_spoofed_message_and_unsupported_protocol(self):
        result = self.run_ui(embedded=True,action='spoof')
        self.assertEqual(result['texts']['goal'], STATE['goal'])
        result = self.run_ui(embedded=True,unsupported=True)
        self.assertIn('does not support MCP Apps protocol', result['texts']['error'])
        self.assertNotIn('ui/notifications/initialized',[m['method'] for m in result['messages']])

    def test_runtime_filter_copy_and_refresh_error(self):
        result=self.run_ui(action='filter')
        self.assertIn('Harden retry behavior', result['texts']['task-list'])
        self.assertNotIn('Validate checkout totals', result['texts']['task-list'])
        result=self.run_ui(action='copy')
        self.assertIn('Reviewer assertions: 1',result['copied'])
        self.assertIn('Rumbo DEMO handoff',result['copied'])
        result=self.run_ui(action='refresh_error')
        self.assertIn('Showing the last snapshot',result['texts']['error'])
        self.assertEqual(result['texts']['goal'],STATE['goal'])

    def test_runtime_marks_changed_digests_and_superseded_records(self):
        state=copy.deepcopy(STATE)
        original=state['tasks'][0]['evidence'][0]
        original['artifact_sha256']='old-digest'
        replacement=copy.deepcopy(original)
        replacement.update(id='e3',artifact_sha256=state['tasks'][0]['artifact']['sha256'],outcome='fail')
        state['tasks'][0]['evidence'].append(replacement)
        state['tasks'][0]['decisions']=[dict(id='d1',outcome='accepted',actor='Maya',reason='Earlier',artifact_revision=2,contract_revision=3),dict(id='d2',outcome='rejected',actor='Maya',reason='Latest',artifact_revision=2,contract_revision=3)]
        result=self.run_ui(state=state)
        self.assertIn('Historical · does not apply',result['texts']['task-detail'])
        self.assertIn('Superseded decision',result['texts']['task-detail'])

    def test_runtime_shows_decision_requests_as_recorded_questions(self):
        state=copy.deepcopy(STATE)
        state['requests']=[dict(task_id='totals',question='Should we include currency conversion?',actor='Builder',contract_revision=3,at='2026-10-01T03:01:00Z')]
        result=self.run_ui(state=state)
        self.assertIn('Should we include currency conversion?',result['texts']['task-detail'])
        self.assertIn('Recorded decision requests',result['texts']['task-detail'])

    def test_real_engine_snapshot_displays_exact_acceptance_and_assertion(self):
        from rumbo.core import Engine
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            owner=Engine(root,'owner','human')
            worker=Engine(root,'builder','worker')
            reviewer=Engine(root,'reader','reviewer')
            owner.execute('create_contract',dict(project_id='ui-test',goal='Keep acceptance precise',original_request='Test real engine state',decision_owner='owner',constraints=[],tasks=[dict(id='task',title='Export records',dependencies=[],acceptance=[dict(id='header',kind='file_contains',value='name,amount'),dict(id='review',kind='manual_review',prompt='Check <semantic> correctness')])]))
            (root/'export.csv').write_text('name,amount\nTest,10\n')
            worker.execute('claim_task',dict(task_id='task',contract_revision=1,lease_seconds=60))
            worker.execute('submit_artifact',dict(task_id='task',contract_revision=1,path='export.csv'))
            worker.execute('run_checks',dict(task_id='task',contract_revision=1,artifact_revision=1))
            reviewer.execute('submit_review',dict(task_id='task',contract_revision=1,artifact_revision=1,check_id='review',outcome='pass',detail='Inspected semantic sample'))
            result=self.run_ui(state=owner.snapshot())
            detail=result['texts']['task-detail']
            self.assertIn('name,amount',detail)
            self.assertIn('Check <semantic> correctness',detail)
            self.assertIn('Assertion by reader',detail)
            self.assertNotIn('Unrecognized evidence',detail)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

@unittest.skipUnless(os.environ.get('RUMBO_BROWSER_TESTS') == '1',
                     'optional browser suite: set RUMBO_BROWSER_TESTS=1 with Playwright/Chromium installed')
class BoardBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise RuntimeError('Browser tests were requested but Playwright is not installed')
        cls.current_state = copy.deepcopy(STATE)
        cls.api_error = False
        cls.requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests.append(self.path)
                if self.path == '/api/state':
                    self.send_response(503 if cls.api_error else 200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(cls.current_state).encode())
                elif self.path == '/host':
                    self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
                    fixture = json.dumps(cls.current_state).replace('<', '\\u003c')
                    self.wfile.write(('''<!doctype html><html><body><script>
                        window.messages=[];window.fixture=''' + fixture + ''';
                        addEventListener('message', e=>{messages.push(e.data);
                          if(e.data.method==='ui/initialize') e.source.postMessage({jsonrpc:'2.0',id:e.data.id,result:{
                            protocolVersion:'2026-01-26',hostInfo:{name:'Test host',version:'1'},
                            hostCapabilities:{serverTools:{}},hostContext:{theme:'light'}}},'*');
                          if(e.data.method==='ui/notifications/initialized') e.source.postMessage({jsonrpc:'2.0',
                            method:'ui/notifications/tool-result',params:{structuredContent:fixture}},'*');
                          if(e.data.method==='tools/call') e.source.postMessage({jsonrpc:'2.0',id:e.data.id,
                            result:{structuredContent:fixture}},'*');
                        });</script><iframe title="Rumbo" src="/" style="width:100%;height:900px;border:0"></iframe></body></html>''').encode())
                else:
                    self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
                    self.wfile.write(BOARD.read_bytes() if BOARD.exists() else b'<html><body>Missing board</body></html>')
            def log_message(self, *_):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.worker.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=os.environ.get('RUMBO_BROWSER_EXECUTABLE') or shutil.which('chromium'), headless=True,
                                           args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.server.shutdown(); cls.server.server_close()

    def setUp(self):
        type(self).current_state = copy.deepcopy(STATE)
        type(self).api_error = False
        type(self).requests = []
        self.page = self.browser.new_page(viewport={'width': 1440, 'height': 1000})
        self.page.set_default_timeout(2000)

    def tearDown(self):
        screenshot_dir=os.environ.get('RUMBO_SCREENSHOT_DIR')
        if screenshot_dir:
            folder=Path(screenshot_dir);folder.mkdir(parents=True,exist_ok=True)
            self.page.screenshot(path=str(folder/(self._testMethodName+'.png')),full_page=True)
        self.page.close()

    def open_board(self):
        self.assertTrue(BOARD.exists(), 'The acceptance board HTML must exist')
        self.page.goto(self.url)
        self.page.get_by_role('heading', name=STATE['goal'], exact=True).wait_for()

    def test_renders_evidence_provenance_and_demo(self):
        self.open_board()
        body = self.page.locator('body').inner_text()
        for expected in ['Demo', 'Deterministic receipts', 'Reviewer assertions',
                         'Human decision', 'Checks passed is not acceptance', 'Priya', 'Awaiting Maya Chen']:
            self.assertIn(expected, body)
        self.assertEqual(self.page.locator('#task-list button').count(), 3)
        self.assertEqual(self.page.get_by_role('button', name=re.compile(r'^(Accept|Approve|Reject|Authorize)$')).count(), 0)

    def test_filter_selection_and_copy_summary(self):
        self.open_board()
        self.page.get_by_label('Filter tasks').select_option('attention')
        self.assertEqual(self.page.locator('#task-list button').count(), 1)
        self.page.locator('#task-list button').click()
        self.assertIn('Contract changed after prior review', self.page.locator('#task-detail').inner_text())
        self.page.get_by_role('button', name='Copy handoff').click()
        self.assertRegex(self.page.locator('#message').inner_text(), 'Copied|copy')

    def test_injection_is_literal_and_narrow_layout_does_not_overflow(self):
        hostile = '<img src=x onerror="window.PWNED=true">'
        type(self).current_state['goal'] = hostile
        type(self).current_state['tasks'][0]['title'] = hostile
        type(self).current_state['tasks'][0]['evidence'][0]['detail'] = hostile
        self.page.set_viewport_size({'width': 375, 'height': 812})
        self.page.goto(self.url)
        self.page.get_by_role('heading', name=hostile, exact=True).first.wait_for()
        self.assertEqual(self.page.locator('img').count(), 0)
        self.assertFalse(self.page.evaluate('Boolean(window.PWNED)'))
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))

    def test_empty_state_and_refresh_failure_retains_snapshot_warning(self):
        self.open_board()
        type(self).api_error = True
        self.page.get_by_role('button', name='Refresh', exact=True).click()
        self.page.get_by_role('alert').wait_for()
        self.assertIn('last snapshot', self.page.get_by_role('alert').inner_text().lower())
        type(self).api_error = False
        type(self).current_state['tasks'] = []
        self.page.get_by_role('button', name='Refresh', exact=True).click()
        self.page.get_by_text('No tasks yet', exact=True).wait_for()

    def test_bridge_initial_result_no_duplicate_fetch_and_refresh(self):
        self.page.goto(self.url + '/host')
        frame = self.page.frame_locator('iframe')
        frame.get_by_role('heading', name=STATE['goal'], exact=True).wait_for()
        self.assertNotIn('/api/state', type(self).requests)
        methods = self.page.evaluate('messages.map(m=>m.method).filter(Boolean)')
        self.assertIn('ui/notifications/initialized', methods)
        self.assertNotIn('tools/call', methods)
        frame.get_by_role('button', name='Refresh', exact=True).click()
        self.page.wait_for_function("messages.some(m=>m.method==='tools/call')")
        calls = self.page.evaluate("messages.filter(m=>m.method==='tools/call')")
        self.assertEqual(calls[0]['params'], {'name': 'rumbo_state', 'arguments': {}})
        self.assertTrue(self.page.evaluate("messages.some(m=>m.method==='ui/notifications/size-changed')"))
        # A message forged by the view itself must not impersonate its parent.
        child = self.page.frames[1]
        child.evaluate("""() => dispatchEvent(new MessageEvent('message', {source: window,
          data: {jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{
          version:1,goal:'FORGED',tasks:[]}}}}))""")
        self.assertEqual(frame.get_by_role('heading', name='FORGED', exact=True).count(), 0)

if __name__ == '__main__':
    unittest.main()
