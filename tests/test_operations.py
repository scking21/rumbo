import contextlib
import concurrent.futures
import http.client
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from rumbo.core import Engine
from rumbo.server import create_server
from test_core import contract

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        Engine(self.root,'owner','human').execute('create_contract',contract())
        self.config=dict(mode='development',log_requests=True,principals=[dict(token='synthetic-token',actor='worker',role='worker',root=str(self.root))])
        self.server=create_server('127.0.0.1',0,self.config)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)
    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,path,method='GET',body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        h=dict(headers or {})
        if body is not None:h['Content-Type']='application/json';body=json.dumps(body)
        conn.request(method,path,body,headers=h);res=conn.getresponse();result=(res.status,res.read());conn.close();return result
    def test_health_is_status_only_and_checks_local_ledger(self):
        for path in ['/health/live','/health/ready']:
            status,raw=self.request(path)
            self.assertEqual(status,200)
            self.assertEqual(json.loads(raw),{'status':'ok'})
            self.assertNotIn(b'sample',raw)
        with sqlite3.connect(self.root/'.rumbo/state.sqlite3') as db:db.execute("UPDATE events SET digest='bad' WHERE seq=1")
        self.assertEqual(self.request('/health/live')[0],200)
        status,raw=self.request('/health/ready');self.assertEqual(status,503)
        self.assertEqual(json.loads(raw),{'status':'unavailable'})
        self.assertNotIn(b'LEDGER',raw)
    def test_structural_logs_never_include_request_secrets_or_queries(self):
        logged=threading.Event()
        class CapturedLogs(io.StringIO):
            def write(self,value):
                count=super().write(value)
                if self.getvalue().count('\n')>=2:logged.set()
                return count
        output=CapturedLogs()
        with contextlib.redirect_stderr(output):
            self.request('/owner/callback?code=TOP_SECRET&state=ALSO_SECRET',headers={'Authorization':'Bearer PRIVATE_TOKEN','Cookie':'PRIVATE_COOKIE'})
            self.request('/mcp','POST',dict(jsonrpc='2.0',id=1,method='tools/call',params=dict(name='rumbo_state',arguments={})),{'Authorization':'Bearer synthetic-token'})
            # The handler logs after writing the response: reading the body is
            # not a synchronization barrier for the server thread's stderr.
            self.assertTrue(logged.wait(5),'Both completed requests must be logged')
        lines=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(lines),2)
        self.assertEqual({line['route'] for line in lines},{'owner','mcp'})
        self.assertEqual(set(lines[0]),{'event','method','route','status','duration_ms'})
        for private in ['TOP_SECRET','ALSO_SECRET','PRIVATE_TOKEN','PRIVATE_COOKIE','sample','Ship CSV']:
            self.assertNotIn(private,output.getvalue())
    def test_concurrent_request_logs_remain_complete_json_records(self):
        logged = threading.Event()
        count = 24
        class SlowCapture(io.StringIO):
            def write(self, value):
                result = super().write(value)
                if value != '\n':
                    # A slow destination can switch threads between print's
                    # JSON write and its separate newline write.
                    time.sleep(0.002)
                if self.getvalue().count('\n') == count:
                    logged.set()
                return result
        output = SlowCapture()
        with contextlib.redirect_stderr(output):
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(lambda _: self.request('/health/live')[0], range(count)))
            self.assertTrue(logged.wait(5), 'All request logs must finish')
        self.assertEqual(results, [200]*count)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), count)
        for line in lines:
            self.assertEqual(json.loads(line)['event'], 'http_request')

    def test_domain_challenge_requires_explicit_bounded_regular_public_file(self):
        self.assertEqual(self.request('/.well-known/openai-apps-challenge')[0],404)
        token=self.root/'openai-apps-challenge';token.write_text('synthetic-public-domain-proof')
        self.config['public_challenge_file']=str(token)
        status,raw=self.request('/.well-known/openai-apps-challenge')
        self.assertEqual((status,raw),(200,b'synthetic-public-domain-proof'))
        self.config['introspection_secret_env']='RUMBO_CHALLENGE_TEST_SECRET'
        with patch.dict(os.environ,{'RUMBO_CHALLENGE_TEST_SECRET_FILE':str(token)}):
            self.assertEqual(self.request('/.well-known/openai-apps-challenge')[0],404)
        self.assertEqual(self.request('/.well-known/openai-apps-challenge?path=/etc/passwd')[0],404)
        token.write_text('x'*4097)
        self.assertEqual(self.request('/.well-known/openai-apps-challenge')[0],404)
        token.unlink();token.symlink_to(self.root/'.rumbo/state.sqlite3')
        self.assertEqual(self.request('/.well-known/openai-apps-challenge')[0],404)

    def test_log_setting_is_boolean_not_truthy_config(self):
        with self.assertRaises(ValueError):create_server('127.0.0.1',0,dict(self.config,log_requests='false'))
    def test_oauth_readiness_requires_configured_secret_without_remote_calls(self):
        config=dict(mode='oauth',public_url='https://rumbo.example/mcp',issuer='https://auth.example',introspection_url='https://auth.example/introspect',introspection_client_id='fixture',introspection_secret_env='RUMBO_UNSET_FIXTURE_SECRET',principals=[dict(subject='subject',actor='worker',role='worker',root=str(self.root))])
        server=create_server('127.0.0.1',0,config);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.dict(os.environ,{},clear=True),patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Health cannot contact issuer')):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                connection.request('GET','/health/ready',headers={'Host':'rumbo.example'})
                response=connection.getresponse();self.assertEqual(response.status,503);response.read();connection.close()
        finally:server.shutdown();server.server_close();thread.join()
