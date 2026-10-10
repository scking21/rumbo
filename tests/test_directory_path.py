"""The Claude directory submission reads the plugin from `rumbo/` on main; that path is fixed there."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY_PLUGIN_PATH = ROOT/'rumbo'


class DirectoryPathTests(unittest.TestCase):
    def test_directory_path_holds_the_plugin_the_marketplace_installs(self):
        manifest = json.loads((DIRECTORY_PLUGIN_PATH/'.claude-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], 'rumbo')
        entry = json.loads((ROOT/'.claude-plugin/marketplace.json').read_text())['plugins'][0]
        self.assertEqual((ROOT/entry['source']).resolve(), DIRECTORY_PLUGIN_PATH)
        self.assertTrue((DIRECTORY_PLUGIN_PATH/'skills/commitments/SKILL.md').is_file())

    def test_hooks_run_from_the_directory_path(self):
        hooks = json.loads((DIRECTORY_PLUGIN_PATH/'hooks/hooks.json').read_text())['hooks']
        with tempfile.TemporaryDirectory(prefix='rumbo directory ') as temp:
            project = Path(temp)/'project'; project.mkdir()
            env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(DIRECTORY_PLUGIN_PATH), CLAUDE_PROJECT_DIR=str(project),
                       RUMBO_STATE_DIR=str(Path(temp)/'state'))
            for event in ('UserPromptSubmit', 'Stop'):
                command = hooks[event][0]['hooks'][0]['command']
                result = subprocess.run(['/bin/sh', '-c', command], input='{}', text=True, capture_output=True,
                                        cwd=project, env=env, timeout=10)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))


if __name__ == '__main__':
    unittest.main()
