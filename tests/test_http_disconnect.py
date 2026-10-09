"""Expected response disconnects must not obscure committed local writes."""
import contextlib
import hashlib
import http.client
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from rumbo.core import Engine
from rumbo.server import create_server
from test_core import contract


class HttpDisconnectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        Engine(self.root, 'owner', 'human').execute('create_contract', contract())
        self.worker = Engine(self.root, 'synthetic-worker', 'worker')
        self.worker.execute('claim_task', dict(task_id='export', contract_revision=1, lease_seconds=300))
        self.server = create_server('127.0.0.1', 0, dict(mode='development', principals=[
            dict(token='synthetic-disconnect-token', actor='synthetic-worker', role='worker', root=str(self.root)),
        ]))
        self.addCleanup(self.server.server_close)

    def test_incomplete_request_body_never_commits_even_when_received_json_is_valid(self):
        body = json.dumps(dict(jsonrpc='2.0', id=75, method='tools/call', params=dict(
            name='rumbo_ingest_artifact', arguments=dict(task_id='export', contract_revision=1,
                                                       filename='proof.csv', content='name,amount\nSynthetic,7')))).encode()
        before = self.worker.snapshot()
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        try:
            for missing in (1, 5):
                with self.subTest(missing=missing), socket.create_connection(
                        ('127.0.0.1', self.server.server_port), timeout=5) as client:
                    headers = (f'POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
                               'Authorization: Bearer synthetic-disconnect-token\r\nContent-Type: application/json\r\n'
                               f'Content-Length: {len(body) + missing}\r\nConnection: close\r\n\r\n').encode()
                    client.sendall(headers + body)
                    client.shutdown(socket.SHUT_WR)
                    with http.client.HTTPResponse(client) as response:
                        response.begin()
                        self.assertEqual(response.status, 400)
                        response.read()
                    after = self.worker.snapshot()
                    self.assertEqual(after['events_count'], before['events_count'])
                    self.assertEqual(after['ledger_head'], before['ledger_head'])
                    self.assertIsNone(next(task for task in after['tasks'] if task['id'] == 'export')['artifact'])
        finally:
            self.server.shutdown()
            thread.join(5)

    def test_reset_after_commit_preserves_upload_and_next_request_without_traceback(self):
        response_ready, client_closed, request_finished = (threading.Event() for _ in range(3))
        handler_class = self.server.RequestHandlerClass
        original_send = handler_class.send
        original_process = self.server.process_request_thread

        def delayed_response(handler, status, value=None, *args, **kwargs):
            if isinstance(value, dict) and value.get('id') == 73:
                # send is reached only after the real engine transaction exits.
                response_ready.set()
                if not client_closed.wait(5):
                    raise AssertionError('Client did not close before response')
            return original_send(handler, status, value, *args, **kwargs)

        def observed_process(*args):
            try:
                original_process(*args)
            finally:
                request_finished.set()

        text = 'name,amount\nSynthetic lost response,7\n'
        body = json.dumps(dict(jsonrpc='2.0', id=73, method='tools/call', params=dict(
            name='rumbo_ingest_artifact', arguments=dict(task_id='export', contract_revision=1,
                                                       filename='proof.csv', content=text)))).encode()
        headers = (f'POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
                   'Authorization: Bearer synthetic-disconnect-token\r\nContent-Type: application/json\r\n'
                   f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode()
        logs = io.StringIO()
        with patch.object(handler_class, 'send', delayed_response), \
                patch.object(self.server, 'process_request_thread', observed_process), \
                contextlib.redirect_stderr(logs):
            thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            thread.start()
            try:
                with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=5) as client:
                    client.sendall(headers + body)
                    self.assertTrue(response_ready.wait(5), 'Upload response must reach the barrier')
                    self.assertEqual(self.worker.snapshot()['events_count'], 3)
                    # Reset the actual socket while the committed response is held.
                    client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
                client_closed.set()
                self.assertTrue(request_finished.wait(5), 'Disconnected request must finish')
                conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
                try:
                    conn.request('POST', '/mcp', json.dumps(dict(jsonrpc='2.0', id=74, method='tools/call',
                        params=dict(name='rumbo_state', arguments={}))), headers={
                            'Authorization': 'Bearer synthetic-disconnect-token', 'Content-Type': 'application/json'})
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    state = json.loads(response.read())['result']['structuredContent']
                finally:
                    conn.close()
                self.assertEqual(state['events_count'], 3)
                self.assertTrue(state['integrity']['valid'])
                artifact = next(t for t in state['tasks'] if t['id'] == 'export')['artifact']
                self.assertEqual(artifact['revision'], 1)
                self.assertEqual(artifact['sha256'], hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(self.worker.artifact_view(dict(task_id='export', contract_revision=1,
                                                               artifact_revision=1))['text'], text)
            finally:
                client_closed.set()
                self.server.shutdown()
                thread.join(5)
        self.assertNotIn('Traceback', logs.getvalue())
        self.assertEqual(logs.getvalue(), '')

    def response_handler(self, failure, fail_write):
        class FailingOutput(io.BytesIO):
            writes = 0
            def write(self, data):
                self.writes += 1
                if self.writes == fail_write:
                    raise failure
                return super().write(data)

        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.request_version = 'HTTP/1.1'
        handler.command = 'POST'
        handler.path = '/mcp'
        handler.requestline = 'POST /mcp HTTP/1.1'
        handler.close_connection = False
        handler.started = time.monotonic()
        handler.logged = False
        handler.server = self.server
        handler.wfile = FailingOutput()
        return handler

    def test_expected_disconnects_during_header_flush_or_body_close_connection(self):
        for error in (BrokenPipeError, ConnectionResetError):
            for write in (1, 2):
                with self.subTest(error=error.__name__, write=write):
                    handler = self.response_handler(error('Synthetic closed peer'), write)
                    try:
                        handler.send(200, {'status': 'ok'})
                    except (BrokenPipeError, ConnectionResetError) as exc:
                        self.fail('Expected response disconnect escaped: ' + type(exc).__name__)
                    self.assertTrue(handler.close_connection)

    def test_unrelated_output_and_serialization_errors_are_not_suppressed(self):
        for write in (1, 2):
            with self.subTest(write=write):
                handler = self.response_handler(OSError('Synthetic unexpected I/O failure'), write)
                with self.assertRaisesRegex(OSError, 'unexpected I/O failure'):
                    handler.send(200, {'status': 'ok'})
        handler = self.response_handler(BrokenPipeError('Must not reach socket'), 1)
        with self.assertRaises(TypeError):
            handler.send(200, {'not_serializable': object()})
