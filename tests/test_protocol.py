import json
import http.client
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from rumbo.core import Engine
from rumbo.protocol import Protocol
from rumbo.server import create_server, OAuthVerifier
from test_core import contract


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        Engine(self.root, 'owner', 'human').execute('create_contract', contract())
        self.engine = Engine(self.root, 'maker', 'worker')
        self.protocol = Protocol(self.engine)

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, method, params=None, id=1):
        return self.protocol.dispatch(dict(jsonrpc='2.0', id=id, method=method, params=params or {}))

    def test_init_and_tools_have_annotations_no_human_tool(self):
        self.assertIn('protocolVersion', self.request('initialize')['result'])
        tools = self.request('tools/list')['result']['tools']
        names = [t['name'] for t in tools]
        self.assertIn('open_project_board', names)
        self.assertNotIn('decide', names)
        for tool in tools:
            self.assertEqual(set(tool['annotations']), {'readOnlyHint','destructiveHint','openWorldHint','idempotentHint'})
            self.assertFalse(tool['inputSchema']['additionalProperties'])
        board = next(t for t in tools if t['name']=='open_project_board')
        self.assertEqual(len(board['_meta']['openai/ui']['entrypoints']), 2)

    def test_state_and_board_are_real_projection(self):
        for name in ['rumbo_state','open_project_board']:
            result = self.request('tools/call',dict(name=name,arguments={}))['result']
            self.assertEqual(result['structuredContent']['goal'], 'Ship CSV export')
            self.assertFalse(result['isError'])

    def test_bad_role_fields_human_action_and_project_override(self):
        for name, args in [('rumbo_claim_task',dict(task_id='export',contract_revision=1,lease_seconds=60,role='human')),('decide',{}),('rumbo_state',dict(project_id='other'))]:
            response = self.request('tools/call', dict(name=name,arguments=args))
            self.assertTrue(response.get('error') or response['result']['isError'])
        self.assertEqual(self.engine.snapshot()['events_count'],1)

    def test_real_stdio_lifecycle_and_errors(self):
        requests = [dict(jsonrpc='2.0',id=1,method='initialize',params=dict(protocolVersion='2025-11-25',capabilities={},clientInfo=dict(name='test',version='1'))),dict(jsonrpc='2.0',method='notifications/initialized'),dict(jsonrpc='2.0',id=2,method='tools/call',params=dict(name='rumbo_claim_task',arguments=dict(task_id='export',contract_revision=1,lease_seconds=60))),dict(jsonrpc='2.0',id=3,method='tools/call',params=dict(name='rumbo_state',arguments={}))]
        proc = subprocess.run([sys.executable,'-m','rumbo','--root',str(self.root),'--actor','maker','mcp'],input='\n'.join(json.dumps(r) for r in requests)+'\nnot-json\n',text=True,capture_output=True,timeout=10)
        self.assertEqual(proc.returncode,0,proc.stderr)
        output = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(output),4)
        self.assertEqual(output[1]['result']['structuredContent']['tasks'][0]['lease']['actor'],'maker')
        self.assertEqual(output[2]['result']['structuredContent']['events_count'],2)
        self.assertEqual(output[3]['error']['code'],-32700)

    def test_unpaired_surrogate_id_does_not_terminate_stdio(self):
        lines=[dict(jsonrpc='2.0',id='\ud800',method='ping'),dict(jsonrpc='2.0',id=2,method='ping')]
        proc=subprocess.run([sys.executable,'-m','rumbo','--root',str(self.root),'mcp'],input='\n'.join(json.dumps(v) for v in lines)+'\n',text=True,capture_output=True,timeout=5)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout.splitlines()[-1])['id'],2)

    def test_deep_json_does_not_terminate_stdio(self):
        raw='['*65+'0'+']'*65+'\n'+json.dumps(dict(jsonrpc='2.0',id=2,method='ping'))+'\n'
        proc=subprocess.run([sys.executable,'-m','rumbo','--root',str(self.root),'mcp'],input=raw,text=True,capture_output=True,timeout=5)
        self.assertEqual(proc.returncode,0,proc.stderr)
        output=[json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(output[0]['error']['code'],-32700)
        self.assertEqual(output[1]['id'],2)

    def test_ingest_protocol_is_bounded_and_byte_scoped(self):
        claim=self.request('tools/call',dict(name='rumbo_claim_task',arguments=dict(task_id='export',contract_revision=1,lease_seconds=60)))
        self.assertFalse(claim['result']['isError'])
        result=self.request('tools/call',dict(name='rumbo_ingest_artifact',arguments=dict(task_id='export',contract_revision=1,filename='received.csv',content='name,amount\nRemote fixture,3\n')))
        self.assertNotIn('error',result)
        self.assertFalse(result['result']['isError'])
        artifact=result['result']['structuredContent']['tasks'][0]['artifact']
        self.assertEqual(artifact['source'],'uploaded_text')
        self.assertNotIn('Remote fixture,3',json.dumps(result))
        checked=self.request('tools/call',dict(name='rumbo_run_checks',arguments=dict(task_id='export',contract_revision=1,artifact_revision=1)))
        self.assertEqual(checked['result']['structuredContent']['tasks'][0]['status'],'checks_passed')

    def test_read_artifact_tool_returns_exact_untrusted_received_text(self):
        self.engine.execute('claim_task',dict(task_id='export',contract_revision=1,lease_seconds=60))
        self.engine.execute('ingest_artifact',dict(task_id='export',contract_revision=1,filename='export.csv',content='name,amount\nReview,7'))
        result=self.request('tools/call',dict(name='rumbo_read_artifact',arguments=dict(task_id='export',contract_revision=1,artifact_revision=1)))
        self.assertNotIn('error',result)
        view=result['result']['structuredContent']
        self.assertEqual(view['text'],'name,amount\nReview,7')
        self.assertIn('Untrusted',view['notice'])

    def test_malformed_json_rpc(self):
        for message in [[],None,{'jsonrpc':'1.0','id':1,'method':'tools/list'}, {'jsonrpc':'2.0','id':{},'method':'tools/list'}]:
            self.assertEqual(self.protocol.dispatch(message)['error']['code'],-32600)
        self.assertEqual(self.request('unknown')['error']['code'],-32601)

    def test_resource_not_arbitrary_file_read(self):
        self.assertEqual(self.request('resources/read',dict(uri='file:///etc/passwd'))['error']['code'],-32602)
        result = self.request('resources/read',dict(uri='ui://rumbo/project-board/v1.html'))['result']['contents'][0]
        self.assertEqual(result['mimeType'],'text/html;profile=mcp-app')
        self.assertEqual(result['_meta']['ui']['csp']['connectDomains'],[])

    def test_stdio_refuses_human_principal(self):
        proc = subprocess.run([sys.executable,'-m','rumbo','--root',str(self.root),'--actor','owner','--role','human','mcp'],text=True,capture_output=True,timeout=10)
        self.assertNotEqual(proc.returncode,0)


class HttpTests(ProtocolTests):
    def setUp(self):
        super().setUp()
        self.config = dict(mode='development',principals=[dict(token='ephemeral-test-token-not-production',actor='maker',role='worker',root=str(self.root))])
        self.server = create_server('127.0.0.1',0,self.config)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.url = 'http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        super().tearDown()

    def http(self,path='/mcp',body=None,token='ephemeral-test-token-not-production',headers=None):
        h = dict(headers or {})
        if token:
            h['Authorization']='Bearer '+token
        if body is not None:
            h['Content-Type']='application/json'; h['Accept']='application/json, text/event-stream'
            body=json.dumps(body).encode()
        req=urllib.request.Request(self.url+path,data=body,headers=h)
        try:
            with urllib.request.urlopen(req,timeout=5) as r:
                return r.status,dict(r.headers),r.read()
        except urllib.error.HTTPError as e:
            return e.code,dict(e.headers),e.read()

    def test_http_auth_protocol_and_no_token_leak(self):
        body=dict(jsonrpc='2.0',id=1,method='tools/call',params=dict(name='rumbo_state',arguments={}))
        for token in [None,'wrong']:
            status,headers,data=self.http(body=body,token=token)
            self.assertEqual(status,401)
            self.assertIn('WWW-Authenticate',headers)
            self.assertNotIn(b'Ship CSV',data)
        status,_,data=self.http(body=body)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(data)['result']['structuredContent']['project_id'],'sample')
        self.assertNotIn(b'ephemeral-test',data)

    def test_cross_origin_and_dns_rebinding_rejected(self):
        body=dict(jsonrpc='2.0',id=1,method='tools/list')
        self.assertEqual(self.http(body=body,headers={'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.http(body=body,headers={'Host':'evil.invalid'})[0],403)

    def test_duplicate_security_headers_rejected(self):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        body=json.dumps(dict(jsonrpc='2.0',id=1,method='tools/list')).encode()
        connection.putrequest('POST','/mcp')
        connection.putheader('Authorization','Bearer ephemeral-test-token-not-production')
        connection.putheader('Authorization','Bearer wrong')
        connection.putheader('Content-Type','application/json')
        connection.putheader('Content-Length',str(len(body)))
        connection.endheaders(body)
        response=connection.getresponse()
        self.assertEqual(response.status,400)
        response.read();connection.close()

    def test_two_principals_have_isolated_project_state(self):
        second=self.root/'other';second.mkdir()
        c=contract();c['project_id']='secret-project';c['goal']='Other private goal'
        Engine(second,'owner','human').execute('create_contract',c)
        self.config['principals'].append(dict(token='second-test-token',actor='other',role='worker',root=str(second)))
        body=dict(jsonrpc='2.0',id=1,method='tools/call',params=dict(name='rumbo_state',arguments={}))
        one=self.http(body=body)[2]
        two=self.http(body=body,token='second-test-token')[2]
        self.assertNotIn(b'secret-project',one)
        self.assertNotIn(b'Ship CSV export',two)
        self.assertIn(b'secret-project',two)

    def test_deep_json_and_duplicate_json_keys_rejected(self):
        for raw in [b'{"jsonrpc":"2.0","id":1,"method":"ping","method":"tools/list"}',b'['*15000+b']'*15000]:
            request=urllib.request.Request(self.url+'/mcp',data=raw,headers={'Authorization':'Bearer ephemeral-test-token-not-production','Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(request,timeout=5)
            self.assertEqual(e.exception.code,400)

    def test_no_unauthenticated_private_board(self):
        self.assertEqual(self.http('/api/state',token=None)[0],404)
        self.assertEqual(self.http('/',token=None)[0],404)

    def test_public_development_bind_rejected(self):
        with self.assertRaises(ValueError):
            create_server('0.0.0.0',0,self.config)

    def test_demo_anonymous_view_closes_if_project_becomes_private(self):
        from rumbo.demo import create_demo
        folder=self.root/'demo';folder.mkdir();create_demo(folder)
        server=create_server('127.0.0.1',0,dict(mode='demo',demo_root=str(folder)))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_port)+'/api/state'
        try:
            with urllib.request.urlopen(url) as response:
                self.assertTrue(json.load(response)['demo'])
            c=contract();c['project_id']='synthetic-csv-demo';c['decision_owner']='demo-owner';c['demo']=False;c['goal']='Private replacement'
            Engine(folder,'demo-owner','human').execute('revise_contract',dict(contract=c,expected_revision=1,reason='Private now'))
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(url)
            self.assertEqual(e.exception.code,403)
            self.assertNotIn(b'Private replacement',e.exception.read())
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_resource_metadata_and_notifications(self):
        status,_,raw=self.http('/.well-known/oauth-protected-resource',token=None)
        self.assertEqual(status,404) # development bearer mode does not pretend to be OAuth
        self.assertEqual(self.http(body=dict(jsonrpc='2.0',method='notifications/initialized'))[0],202)


class OAuthTests(unittest.TestCase):
    def config(self):
        return dict(mode='oauth',public_url='https://rumbo.example/mcp',issuer='https://issuer.example',introspection_url='https://issuer.example/introspect',introspection_client_id='rumbo-test',introspection_secret_env='RUMBO_TEST_SECRET',principals=[dict(subject='alice',actor='maker',role='worker',root='/tmp')])

    def claims(self):
        return dict(active=True,iss='https://issuer.example',aud='https://rumbo.example/mcp',sub='alice',scope='rumbo:read rumbo:write',exp=2000)

    def test_token_claims_bound_to_issuer_audience_scope_and_subject(self):
        verifier=OAuthVerifier(self.config(),clock=lambda:1000,introspect=lambda token:self.claims())
        principal=verifier.verify('test-token')
        self.assertEqual(principal['actor'],'maker')
        for patch in [dict(active=False),dict(iss='https://evil.invalid'),dict(aud='other'),dict(exp=999),dict(sub='bob'),dict(scope='other'),dict(exp=True)]:
            claims=self.claims(); claims.update(patch)
            bad=OAuthVerifier(self.config(),clock=lambda:1000,introspect=lambda token:claims)
            self.assertIsNone(bad.verify('test-token'))

    def test_owner_routes_are_integrated_and_fail_closed_without_setup(self):
        config=self.config()
        server=create_server('127.0.0.1',0,config)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            connection.request('GET','/owner',headers={'Host':'rumbo.example'})
            response=connection.getresponse()
            self.assertEqual(response.status,503)
            self.assertIn(b'not configured',response.read())
            connection.close()
        finally:server.shutdown();server.server_close();thread.join()

    def test_read_scope_cannot_write_and_unconfigured_servers_fail(self):
        claims=self.claims();claims['scope']='rumbo:read'
        verifier=OAuthVerifier(self.config(),clock=lambda:1000,introspect=lambda _:claims)
        self.assertEqual(verifier.verify('token')['role'],'viewer')
        for key in ['issuer','public_url','introspection_url']:
            config=self.config(); config[key]='http://127.0.0.1/private'
            with self.assertRaises(ValueError):
                OAuthVerifier(config)
        config=self.config();config['principals'][0]['role']='human'
        with self.assertRaises(ValueError):
            OAuthVerifier(config)


class SafeJsonTests(unittest.TestCase):
    def test_malformed_json_stays_rejected(self):
        from rumbo.protocol import safe_json
        for raw in ['[}', '][', '[', '{"x":"unterminated}', '{"x":1,}', '[1] garbage', '{"x":1,"x":2}', '[NaN]']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):safe_json(raw)

    def test_depth_limit_is_explicit_not_python_recursion_limit(self):
        from rumbo.protocol import safe_json
        with self.assertRaisesRegex(ValueError, 'nesting'):
            safe_json('[' * 65 + '0' + ']' * 65)
        self.assertIsInstance(safe_json('[' * 64 + '0' + ']' * 64), list)

    def test_rejects_depth_before_calling_json_decoder(self):
        from rumbo.protocol import safe_json
        with patch('rumbo.protocol.json.loads', side_effect=AssertionError('Decoder must not see deep data')):
            with self.assertRaisesRegex(ValueError, 'nesting'):
                safe_json(b'[' * 15000 + b']' * 15000)

    def test_depth_scanner_respects_strings_escapes_and_byte_encodings(self):
        from rumbo.protocol import safe_json
        value={'text':'[' * 100 + '\\"{}' + ']' * 100, 'next':[1]}
        raw=json.dumps(value)
        for encoded in [raw,raw.encode(),raw.encode('utf-16'),raw.encode('utf-32')]:
            self.assertEqual(safe_json(encoded),value)
        for encoded in [('['*65+'0'+']'*65).encode('utf-16'),('{"x":'*65+'0'+'}'*65).encode()]:
            with self.assertRaisesRegex(ValueError, 'nesting'):safe_json(encoded)


if __name__=='__main__': unittest.main()
