"""Execute the published quickstarts against disposable synthetic projects.

Only this test supplies terminal confirmations for its synthetic owner. It does
not change the CLI's real-user confirmation requirement or use a bypass flag.
"""
import json
import os
from pathlib import Path
import pty
import re
import select
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen

from rumbo.core import Engine


ROOT = Path(__file__).resolve().parents[1]


class QuickstartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rumbo quickstart ')
        self.addCleanup(self.tmp.cleanup)
        self.env = dict(os.environ, TMPDIR=self.tmp.name,
                        PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', ''))

    def blocks(self, relative_path, section=None):
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), 'The linked, runnable quickstart must exist')
        source = path.read_text(encoding='utf-8')
        if section:
            source = source.split('## ' + section + '\n', 1)[1].split('\n## ', 1)[0]
        blocks = re.findall(r'^```sh\n(.*?)^```', source, re.M | re.S)
        self.assertTrue(blocks, 'Quickstart needs executable shell commands')
        return '\n'.join(blocks)

    def read_until(self, process, output, predicate):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if predicate(output):
                return output
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    self.fail('Quickstart ended before the expected result:\n' + output.decode())
                output += chunk
        self.fail('Quickstart timed out:\n' + output.decode())

    def launch(self, script, stdin=subprocess.DEVNULL):
        # Terminate the whole shell/server group, including on assertion failure.
        import signal
        process = subprocess.Popen(
            ['sh', '-eu', '-c', script], cwd=ROOT, env=self.env, stdin=stdin,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )

        def close():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
            process.stdout.close()

        self.addCleanup(close)
        return process

    def test_readme_demo_uses_fresh_root_and_serves_synthetic_state(self):
        script = self.blocks('README.md', 'Try the deterministic demo')
        # Prevent an old fixed /tmp path from escaping this test's isolated fixture.
        self.assertIn('mktemp -d', script, 'Every demo run needs a fresh empty directory')
        roots = []
        for _ in range(2):
            process = self.launch(script)
            output = self.read_until(process, b'', lambda data: re.search(
                rb'Rumbo HTTP listening on 127\.0\.0\.1:\d+\n', data))
            port = re.search(rb'Rumbo HTTP listening on 127\.0\.0\.1:(\d+)', output)[1].decode()
            with urlopen('http://127.0.0.1:' + port + '/', timeout=5) as response:
                self.assertIn(b'<html', response.read())
            with urlopen('http://127.0.0.1:' + port + '/api/state', timeout=5) as response:
                state = json.load(response)
            self.assertTrue(state['demo'])
            self.assertEqual(state['project_id'], 'synthetic-csv-demo')
            self.assertEqual({task['status'] for task in state['tasks']},
                             {'accepted', 'produced', 'checks_passed', 'stale', 'unclaimed', 'blocked'})
            roots.append(set(Path(self.tmp.name).glob('rumbo-demo.*')))
        self.assertEqual(len(roots[0]), 1)
        self.assertEqual(len(roots[1] - roots[0]), 1)

    def test_local_quickstart_runs_from_contract_through_human_acceptance(self):
        script = self.blocks('docs/QUICKSTART.md')
        script += '\nprintf "\\nQUICKSTART_ROOT=%s\\n" "$project_root"\n'
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        try:
            process = self.launch(script, stdin=slave)
        finally:
            os.close(slave)
        output = b''
        for action in ('create_contract', 'decide'):
            prompt = ('As the human decision owner, type CONFIRM ' + action + ': ').encode()
            output = self.read_until(process, output, lambda data: prompt in data)
            os.write(master, ('CONFIRM ' + action + '\n').encode())
        remainder, _ = process.communicate(timeout=15)
        output += remainder
        self.assertEqual(process.returncode, 0, output.decode())
        root = Path(re.search(rb'\nQUICKSTART_ROOT=(.+)\n', output)[1].decode())
        self.assertEqual(root.parent, Path(self.tmp.name))
        self.assertIn('.rumbo/', (root / '.gitignore').read_text())
        state = Engine(root, 'test-observer', 'viewer').snapshot()
        self.assertEqual(state['project_id'], 'quickstart-csv')
        self.assertEqual(state['contract_revision'], 1)
        task, = state['tasks']
        self.assertEqual(task['id'], 'export')
        self.assertEqual(task['status'], 'accepted')
        self.assertEqual(task['artifact']['path'], 'export.csv')
        self.assertEqual(task['artifact']['revision'], 1)
        self.assertEqual((root / 'export.csv').read_text(), 'name,amount\nDemo,5\n')
        self.assertEqual(task['evidence'][0]['outcome'], 'pass')
        self.assertEqual(task['decisions'][-1]['actor'], 'quickstart-owner')
        # The local workflow observes later local-file changes without uploading.
        (root / 'export.csv').write_text('changed after the quickstart\n')
        self.assertEqual(Engine(root, 'test-observer', 'viewer').snapshot()['tasks'][0]['status'], 'stale')
