import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from scripts.package_release import build_local, build_submission, validate_public_config

ROOT=Path(__file__).resolve().parents[1]
class PackageTests(unittest.TestCase):
    def test_local_zip_reproducible_and_hook_free(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a.zip';b=Path(d)/'b.zip'
            build_local(ROOT,a);build_local(ROOT,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            with zipfile.ZipFile(a) as z:
                names=z.namelist()
                self.assertIn('rumbo/plugin.json',names)
                self.assertIn('rumbo/mcp.json',names)
                self.assertIn('rumbo/rumbo/core.py',names)
                self.assertFalse(any('hooks' in x or '.app.json' in x or '.sqlite' in x or '__pycache__' in x for x in names))
                manifest=json.loads(z.read('rumbo/plugin.json'))
                self.assertEqual(manifest['name'],'rumbo')
                self.assertEqual(len(manifest['extensions']['com.openai']['review']['test_cases']['positive']),5)
                self.assertEqual(len(manifest['extensions']['com.openai']['review']['test_cases']['negative']),3)
                z.extractall(Path(d)/'extracted')
            project=Path(d)/'project';project.mkdir()
            env=dict(os.environ,RUMBO_PROJECT_ROOT=str(project))
            request=json.dumps(dict(jsonrpc='2.0',id=1,method='tools/list'))+'\n'
            p=subprocess.run([sys.executable,str(Path(d)/'extracted/rumbo/scripts/run_mcp.py')],input=request,text=True,capture_output=True,env=env)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn('open_project_board',p.stdout)

    def test_submission_refuses_missing_or_placeholder_configuration(self):
        for config in [{},dict(mcp_url='http://localhost:8765/mcp'),dict(mcp_url='https://example.com/mcp')]:
            with self.assertRaises(ValueError):validate_public_config(config)
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'submission.zip'
            with self.assertRaises(ValueError):build_submission(ROOT,target,{})
            self.assertFalse(target.exists())

    def test_submission_rejects_private_ips_and_reserved_subdomains(self):
        from scripts.package_release import GATES
        config={k:'https://rumbo.company.dev/'+k for k in ['website_url','support_url','privacy_url','terms_url','video_url']}
        config.update(mcp_url='https://rumbo.company.dev/mcp',attestations={k:True for k in GATES})
        validate_public_config(config) # structural fixture, no real endpoint assertion
        for url in ['https://127.0.0.1/mcp','https://10.2.3.4/mcp','https://private.example.com/mcp','https://docs.example.com./mcp','https://production.invalid./mcp','https://0177.0.0.1/mcp','https://2130706433/mcp','https://0x7f000001/mcp']:
            with self.subTest(url=url),self.assertRaises(ValueError):
                validate_public_config(dict(config,mcp_url=url))

    def test_package_rejects_unexpected_secret_or_hook_files(self):
        import shutil
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            shutil.copytree(ROOT/'openai-plugin',root/'openai-plugin')
            (root/'docs').mkdir();shutil.copy(ROOT/'docs/reviewer-cases.json',root/'docs/reviewer-cases.json')
            shutil.copy(ROOT/'LICENSE',root/'LICENSE')
            for name in ['.env','hooks.json','.app.json']:
                planted=root/'openai-plugin/rumbo'/name;planted.write_text('synthetic unsafe package input')
                with self.subTest(name=name),self.assertRaises(ValueError):
                    build_local(root,root/'out.zip')
                planted.unlink()

    def test_portable_manifests_validate_against_pinned_official_schemas(self):
        try:import jsonschema
        except ImportError:self.skipTest('Optional jsonschema developer tool not installed')
        for name in ['plugin','mcp']:
            schema=json.loads((ROOT/'schemas'/f'{name}.schema.json').read_text())
            data=json.loads((ROOT/'openai-plugin/rumbo'/f'{name}.json').read_text())
            jsonschema.Draft202012Validator(schema).validate(data)
