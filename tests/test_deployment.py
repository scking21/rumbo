import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location('deploy_'+name,ROOT/'deploy'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class DeploymentTests(unittest.TestCase):
    def test_proxy_renderer_refuses_placeholders_and_injection(self):
        render=load('render')
        for hostname in ['', 'localhost','127.0.0.1','example.com','x.example.com','host.invalid','bad;include /tmp/x','abc.test','https://app.good-domain.net','good-domain.net.']:
            with self.subTest(hostname=hostname),self.assertRaises(ValueError):render.render_nginx(hostname)
        text=render.render_nginx('approved.rumbo-service.net')
        self.assertIn('server_name approved.rumbo-service.net;',text)
        self.assertIn('proxy_set_header Host approved.rumbo-service.net;',text)
        self.assertNotIn('__APP_HOST__',text)
        self.assertIn('limit_req_status 429',text)
        self.assertIn('client_max_body_size 1m',text)
        self.assertIn('location ^~ /health/ { return 404; }',text)
        self.assertIn('access_log off',text)
        self.assertNotIn('$request_uri',text)
        self.assertNotIn('$http_cookie',text)
        self.assertIn('error_log /dev/null',text)

    def test_entrypoint_loads_only_explicit_existing_secret_files(self):
        entry=load('entrypoint')
        with tempfile.TemporaryDirectory() as root:
            secret=Path(root)/'mcp';secret.write_text('synthetic-secret\n');secret.chmod(0o600)
            config={'mode':'oauth','introspection_secret_env':'MCP_SECRET'}
            with patch.dict(os.environ,{'MCP_SECRET_FILE':str(secret)},clear=True):
                entry.load_secret_files(config)
                self.assertEqual(os.environ['MCP_SECRET'],'synthetic-secret')
                self.assertNotIn('OWNER_SECRET',os.environ)
            with patch.dict(os.environ,{'MCP_SECRET_FILE':str(secret),'MCP_SECRET':'already-set'},clear=True):
                with self.assertRaises(ValueError):entry.load_secret_files(config)
            linked=Path(root)/'link';linked.symlink_to(secret)
            with patch.dict(os.environ,{'MCP_SECRET_FILE':str(linked)},clear=True):
                with self.assertRaises(ValueError):entry.load_secret_files(config)
            secret.write_bytes(b'x'*16385)
            with patch.dict(os.environ,{'MCP_SECRET_FILE':str(secret)},clear=True):
                with self.assertRaises(ValueError):entry.load_secret_files(config)

    def test_managed_host_port_is_explicit_and_bounded(self):
        entry=load('entrypoint');health=load('healthcheck')
        for module in [entry,health]:
            with patch.dict(os.environ,{'PORT':'10000'},clear=True):self.assertEqual(module.port(),10000)
            with patch.dict(os.environ,{},clear=True):self.assertEqual(module.port(),8765)
            for invalid in ['0','80','65536','nan','10000;nginx']:
                with patch.dict(os.environ,{'PORT':invalid},clear=True),self.assertRaises(ValueError):module.port()
        template=(ROOT/'deploy/render.yaml.template').read_text()
        self.assertIn('autoDeployTrigger: off',template)
        self.assertIn('mountPath: /var/lib/rumbo/projects/default',template)
        self.assertIn('healthCheckPath: /health/ready',template)

    def test_container_recipe_has_no_public_backend_or_baked_credentials(self):
        docker=(ROOT/'deploy/Dockerfile').read_text();compose=(ROOT/'deploy/compose.yml').read_text();ignore=(ROOT/'.dockerignore').read_text()
        self.assertIn('USER 10001:10001',docker)
        self.assertIn('requirements-authkit.txt',docker)
        self.assertIn('read_only: true',compose)
        self.assertIn('no-new-privileges:true',compose)
        self.assertIn('condition: service_healthy',compose)
        self.assertIn('create_host_path: false',compose)
        self.assertNotIn('8765:8765',compose)
        self.assertIn('secrets:',compose)
        self.assertIn('!rumbo/**',ignore)
        self.assertNotIn('COPY . .',docker)
        self.assertIn('healthcheck.py',docker)

    def test_health_helper_uses_configured_host_without_authentication(self):
        health=load('healthcheck')
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'config.json';path.write_text(json.dumps({'public_url':'https://approved.rumbo-service.net/mcp'}))
            seen=[]
            class Response:
                status=200
                def read(self):return b'{"status":"ok"}'
            class Connection:
                def __init__(self,host,port,timeout):self.args=(host,port,timeout)
                def request(self,method,path,headers):seen.append((method,path,headers))
                def getresponse(self):return Response()
                def close(self):pass
            with patch.object(health.http.client,'HTTPConnection',Connection):self.assertTrue(health.check(path))
            self.assertEqual(seen,[('GET','/health/ready',{'Host':'approved.rumbo-service.net'})])

if __name__=='__main__':unittest.main()
