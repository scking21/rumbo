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
            project=Path(d).resolve()/'project';project.mkdir()
            plugin_data=Path(d).resolve()/'plugin-data';plugin_data.mkdir(mode=0o700)
            env=dict(os.environ,PLUGIN_DATA=str(plugin_data),RUMBO_PROJECT_ROOT=str(project),RUMBO_ROLE='human',RUMBO_ACTOR='owner')
            requests=[dict(jsonrpc='2.0',id=1,method='tools/list'),
                      dict(jsonrpc='2.0',id=2,method='tools/call',params=dict(name='rumbo_list_projects',arguments={})),
                      dict(jsonrpc='2.0',id=3,method='tools/call',params=dict(name='rumbo_state',arguments={}))]
            request=''.join(json.dumps(item)+'\n' for item in requests)
            p=subprocess.run([sys.executable,str(Path(d)/'extracted/rumbo/scripts/run_mcp.py')],input=request,text=True,capture_output=True,env=env)
            self.assertEqual(p.returncode,0,p.stderr)
            listed,projects,state=map(json.loads,p.stdout.splitlines())
            names={tool['name'] for tool in listed['result']['tools']}
            self.assertIn('open_project_board',names)
            self.assertIn('rumbo_connect_project',names)
            self.assertNotIn('rumbo_submit_review',names)
            self.assertEqual(projects['result']['structuredContent']['projects'],[])
            self.assertTrue(state['result']['isError'])
            self.assertIn('PROJECT_UNBOUND',state['result']['content'][0]['text'])
            self.assertEqual(list(plugin_data.iterdir()),[])
            self.assertFalse((project/'.rumbo').exists())

    def test_submission_refuses_missing_or_placeholder_configuration(self):
        for config in [{},dict(mcp_url='http://localhost:8765/mcp'),dict(mcp_url='https://example.com/mcp')]:
            with self.assertRaises(ValueError):validate_public_config(config)
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'submission.zip'
            with self.assertRaises(ValueError):build_submission(ROOT,target,{})
            self.assertFalse(target.exists())

    def test_submission_release_notes_follow_independent_adapter_version(self):
        from scripts.package_release import GATES
        config={k:'https://rumbo.company.dev/'+k for k in ['website_url','support_url','privacy_url','terms_url','video_url']}
        config.update(mcp_url='https://rumbo.company.dev/mcp',attestations={k:True for k in GATES})
        # Structural test fixture only: no endpoint or real verification claim.
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'submission.zip'
            build_submission(ROOT,target,config)
            with zipfile.ZipFile(target) as archive:
                manifest=json.loads(archive.read('rumbo/plugin.json'))
            expected=json.loads((ROOT/'openai-plugin/rumbo/plugin.json').read_text())['version']
            self.assertEqual(manifest['version'],expected)
            self.assertTrue(manifest['extensions']['com.openai']['publication']['release_notes'].startswith(expected+': '))

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

    def test_brand_color_meets_light_and_dark_listing_contrast(self):
        manifest=json.loads((ROOT/'openai-plugin/rumbo/plugin.json').read_text())
        color=manifest['extensions']['com.openai']['interface'].get('brandColor')
        if color is None:return # Optional metadata may be omitted instead.
        def luminance(hexvalue):
            values=[int(hexvalue[i:i+2],16)/255 for i in (1,3,5)]
            linear=[v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in values]
            return sum(v*w for v,w in zip(linear,[0.2126,0.7152,0.0722]))
        foreground=luminance(color)
        for background in ['#ffffff','#212121']:
            light,dark=sorted([foreground,luminance(background)],reverse=True)
            self.assertGreaterEqual((light+0.05)/(dark+0.05),2.0)

    def test_source_archive_excludes_backups_and_rejects_live_deployment_config(self):
        from scripts.package_release import build_source
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root);(folder/'docs').mkdir();(folder/'deploy').mkdir()
            (folder/'docs/operator-backup.zip').write_bytes(b'synthetic private backup')
            target=folder/'source.zip';build_source(folder,target)
            with zipfile.ZipFile(target) as archive:self.assertFalse(any(name.endswith('.zip') for name in archive.namelist()))
            (folder/'deploy/server.json').write_text('{"synthetic_private_config":true}')
            with self.assertRaises(ValueError):build_source(folder,target)

    def test_source_archive_rejects_secret_names_and_nested_deployment_inputs(self):
        from scripts.package_release import build_source
        for name in ['docs/.env', 'docs/.env.production', 'docs/credentials.json',
                     'rumbo/secrets.json', 'scripts/.netrc', 'scripts/.npmrc',
                     'tests/.pypirc', 'docs/.aws/config', 'docs/.ssh/config',
                     'deploy/live/server-config.template.json']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                folder=Path(root); planted=folder/name
                planted.parent.mkdir(parents=True);planted.write_text('synthetic private input')
                target=folder/'source.zip'
                with self.assertRaises(ValueError):build_source(folder,target)
                self.assertFalse(target.exists())

    def test_portable_manifests_validate_against_pinned_official_schemas(self):
        try:import jsonschema
        except ImportError:self.skipTest('Optional jsonschema developer tool not installed')
        for name in ['plugin','mcp']:
            schema=json.loads((ROOT/'schemas'/f'{name}.schema.json').read_text())
            data=json.loads((ROOT/'openai-plugin/rumbo'/f'{name}.json').read_text())
            jsonschema.Draft202012Validator(schema).validate(data)
