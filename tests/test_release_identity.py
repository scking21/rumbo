import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

from rumbo import __version__
from scripts.package_release import build_local, build_source

ROOT = Path(__file__).resolve().parents[1]


class ReleaseIdentityTests(unittest.TestCase):
    def test_changed_distributions_have_new_consistent_identities(self):
        project = (ROOT/'pyproject.toml').read_text()
        self.assertEqual(re.search(r'^version = "([^"]+)"$', project, re.M).group(1), __version__)
        self.assertEqual(__version__, '0.3.2')
        portable = json.loads((ROOT/'openai-plugin/rumbo/plugin.json').read_text())
        codex = json.loads((ROOT/'openai-plugin/rumbo/.codex-plugin/plugin.json').read_text())
        claude = json.loads((ROOT/'rumbo/.claude-plugin/plugin.json').read_text())
        self.assertEqual(portable['version'], '0.3.3')
        self.assertEqual(codex['version'], portable['version'])
        self.assertEqual(claude['version'], '0.3.4')
        self.assertTrue(portable['extensions']['com.openai']['publication']['release_notes'].startswith('0.3.3 '))

    def test_source_archive_version_and_claude_hook_execution(self):
        with tempfile.TemporaryDirectory(prefix='rumbo release ') as temp:
            folder = Path(temp).resolve()
            archive_path = folder/'source.zip'
            build_source(ROOT, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                prefix = 'rumbo-'+__version__+'-source/'
                self.assertTrue(all(name.startswith(prefix) for name in archive.namelist()))
                archive.extractall(folder/'unpacked')
                for name in ('show.sh', 'stop-gate.sh'):
                    member = archive.getinfo(prefix+'rumbo/scripts/'+name)
                    self.assertEqual((member.external_attr >> 16) & 0o777, 0o755)
                    (folder/'unpacked'/member.filename).chmod(0o755)
            source = folder/'unpacked'/prefix
            marketplace = json.loads((source/'.claude-plugin/marketplace.json').read_text())
            entry = marketplace['plugins'][0]
            plugin = source/entry['source']
            self.assertEqual(json.loads((plugin/'.claude-plugin/plugin.json').read_text())['name'], entry['name'])
            project = folder/'project space'; project.mkdir()
            env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(plugin), CLAUDE_PROJECT_DIR=str(project),
                       RUMBO_STATE_DIR=str(folder/'marker state'))
            env.pop('PYTHONPATH', None)
            env.pop('PYTHONHOME', None)
            hooks = json.loads((plugin/'hooks/hooks.json').read_text())['hooks']
            for event in ('UserPromptSubmit', 'Stop'):
                command = hooks[event][0]['hooks'][0]['command']
                result = subprocess.run(['/bin/sh', '-c', command], input='{}', text=True,
                                        capture_output=True, cwd=project, env=env, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, '')
            self.assertFalse((project/'.rumbo').exists())

    def test_local_zip_bundles_matching_engine_and_adapter_identities(self):
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp)/'local.zip'
            build_local(ROOT, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.read('rumbo/rumbo/__init__.py'), (ROOT/'rumbo/__init__.py').read_bytes())
                self.assertEqual(json.loads(archive.read('rumbo/plugin.json'))['version'],
                                 json.loads(archive.read('rumbo/.codex-plugin/plugin.json'))['version'])

                archive.extractall(Path(temp)/'plugin with spaces')
            plugin = Path(temp)/'plugin with spaces/rumbo'
            data = Path(temp).resolve()/'private data'; data.mkdir(mode=0o700)
            env = dict(os.environ, PLUGIN_DATA=str(data))
            env.pop('PYTHONPATH', None)
            env.pop('PYTHONHOME', None)
            request = json.dumps(dict(jsonrpc='2.0', id=1, method='initialize',
                                      params=dict(protocolVersion='2025-03-26'))) + '\n'
            result = subprocess.run([sys.executable, '-I', '-S', str(plugin/'scripts/run_mcp.py')],
                                    input=request, text=True, capture_output=True,
                                    cwd=temp, env=env, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['result']['serverInfo']['version'], __version__)
            self.assertEqual(list(data.iterdir()), [])
