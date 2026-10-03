import json
import os
from pathlib import Path
import subprocess
import shutil
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
            (root/'docs').mkdir()
            for path in (ROOT/'docs').glob('reviewer-cases-*.json'):
                shutil.copy(path,root/'docs'/path.name)
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


class PackageCompletenessTests(unittest.TestCase):
    def copy_source(self, destination):
        root = Path(destination)/'source'
        for folder in ('openai-plugin', 'rumbo', 'docs'):
            shutil.copytree(ROOT/folder, root/folder,
                            ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy(ROOT/'LICENSE', root/'LICENSE')
        return root

    def test_local_package_rejects_each_missing_required_plugin_input(self):
        required = ['plugin.json', 'mcp.json', 'README.md',
                    '.codex-plugin/plugin.json', 'assets/icon.svg',
                    'scripts/run_mcp.py', 'skills/coordinate-work/SKILL.md',
                    'skills/review-evidence/SKILL.md']
        for relative in required:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                root = self.copy_source(tmp)
                (root/'openai-plugin/rumbo'/relative).unlink()
                target = Path(tmp)/'local.zip'
                with self.assertRaisesRegex(ValueError, 'Missing required plugin input'):
                    build_local(root, target)
                self.assertFalse(target.exists())

    def test_local_package_rejects_each_missing_launcher_runtime_module(self):
        for module in ('__init__.py', 'core.py', 'protocol.py', 'registry.py', 'installed.py'):
            with self.subTest(module=module), tempfile.TemporaryDirectory() as tmp:
                root = self.copy_source(tmp)
                (root/'rumbo'/module).unlink()
                target = Path(tmp)/'local.zip'
                with self.assertRaisesRegex(ValueError, 'Missing required local runtime input'):
                    build_local(root, target)
                self.assertFalse(target.exists())

    def test_submission_rejects_missing_remote_workflow_files(self):
        from scripts.package_release import GATES
        config = {key: 'https://rumbo.company.dev/'+key for key in
                  ('website_url', 'support_url', 'privacy_url', 'terms_url', 'video_url')}
        config.update(mcp_url='https://rumbo.company.dev/mcp',
                      attestations={gate: True for gate in GATES})
        for relative in ('assets/icon.svg', 'skills/coordinate-work/SKILL.md',
                         'skills/review-evidence/SKILL.md'):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                root = self.copy_source(tmp)
                (root/'openai-plugin/rumbo'/relative).unlink()
                target = Path(tmp)/'submission.zip'
                with self.assertRaisesRegex(ValueError, 'Missing required plugin input'):
                    build_submission(root, target, config)
                self.assertFalse(target.exists())


class DistributionMetadataTests(unittest.TestCase):
    def test_claude_spec_uses_current_marketplace_source(self):
        marketplace = json.loads((ROOT/'.claude-plugin/marketplace.json').read_text())
        plugin = next(item for item in marketplace['plugins'] if item['name'] == 'rumbo')
        self.assertTrue((ROOT/plugin['source']/'.claude-plugin/plugin.json').is_file())
        self.assertIn('source `'+plugin['source']+'`',
                      (ROOT/'claude-plugin/rumbo/SPEC.md').read_text())

    def test_claude_spec_uses_independent_manifest_version(self):
        manifest = json.loads((ROOT/'claude-plugin/rumbo/.claude-plugin/plugin.json').read_text())
        self.assertIn('version `'+manifest['version']+'`',
                      (ROOT/'claude-plugin/rumbo/SPEC.md').read_text())


class ExtractedDistributionTests(unittest.TestCase):
    def test_local_archive_contains_canonical_runtime_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'local.zip'
            build_local(ROOT, target)
            with zipfile.ZipFile(target) as archive:
                runtime = {'rumbo/rumbo/'+path.name: path.read_bytes()
                           for path in (ROOT/'rumbo').glob('*.py')}
                runtime['rumbo/rumbo/web/board.html'] = (ROOT/'rumbo/web/board.html').read_bytes()
                packaged = {name: archive.read(name) for name in archive.namelist()
                            if name.startswith('rumbo/rumbo/')}
                self.assertEqual(packaged, runtime)
                self.assertFalse(any('claude' in name or '/hooks/' in name
                                     for name in archive.namelist()))

    def test_source_archive_runs_preserved_independent_claude_hooks(self):
        from scripts.package_release import build_source
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            target = directory/'source.zip'
            build_source(ROOT, target)
            with zipfile.ZipFile(target) as archive:
                archive.extractall(directory/'extracted')
                root = directory/'extracted'/archive.namelist()[0].split('/')[0]
                plugin = root/'claude-plugin/rumbo'
                for script in ('show.sh', 'stop-gate.sh'):
                    path = plugin/'scripts'/script
                    member = path.relative_to(directory/'extracted').as_posix()
                    mode = archive.getinfo(member).external_attr >> 16
                    self.assertEqual(mode & 0o777, 0o755)
                    # zipfile does not restore Unix modes; ordinary unzip does.
                    path.chmod(mode & 0o777)
                self.assertEqual((plugin/'scripts/record.py').read_bytes(),
                                 (ROOT/'claude-plugin/rumbo/scripts/record.py').read_bytes())
                manifest = json.loads((plugin/'.claude-plugin/plugin.json').read_text())
                self.assertEqual(manifest, json.loads((ROOT/'claude-plugin/rumbo/.claude-plugin/plugin.json').read_text()))
            project = directory/'synthetic-project'
            (project/'.rumbo').mkdir(parents=True)
            shutil.copy(plugin/'tests/fixtures/workshop.json', project/'.rumbo/record.json')
            env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(plugin),
                       CLAUDE_PROJECT_DIR=str(project), RUMBO_STATE_DIR=str(directory/'state'))
            shown = subprocess.run([str(plugin/'scripts/show.sh')], input='{}',
                                   text=True, capture_output=True, env=env, cwd=directory, timeout=10)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertIn('CONFLICT C1', shown.stdout)
            self.assertIn('CONFLICT C2', shown.stdout)
            stopped = subprocess.run([str(plugin/'scripts/stop-gate.sh')],
                input=json.dumps({'session_id': 'packaging-smoke',
                                  'transcript_path': str(plugin/'tests/fixtures/transcript.jsonl')}),
                text=True, capture_output=True, env=env, cwd=directory, timeout=10)
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertEqual(json.loads(stopped.stdout)['decision'], 'block')


class SitesSourceCompletenessTests(unittest.TestCase):
    def test_source_archive_includes_reviewed_sites_workflow_tests(self):
        from scripts.package_release import build_source
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'source'
            path = root/'openai-sites/tests/workflows.test.mjs'
            path.parent.mkdir(parents=True)
            path.write_text('// Reviewed workflow regression fixture.\n')
            target = Path(tmp)/'source.zip'
            try:
                build_source(root, target)
            except ValueError as error:
                self.fail('Reviewed Sites workflow tests must be distributable: '+str(error))
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.read('rumbo-0.3.0-source/openai-sites/tests/workflows.test.mjs'),
                                 path.read_bytes())
