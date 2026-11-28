"""Exercise the local-only interface as distributed to Codex."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from scripts.package_release import GATES, build_local, build_submission


class UploadPreparationTests(unittest.TestCase):
    def test_local_helper_honors_review_and_preserves_exact_bytes(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            archive = temp / 'local.zip'
            build_local(root, archive)
            with ZipFile(archive) as package:
                package.extractall(temp)
            command = [sys.executable, '-I', '-B', str(temp / 'rumbo/skills/coordinate-work/prepare_upload.py')]
            for payload in (b'', b'\xef\xbb\xbfA\x00B\r\n', 'cafe\u0301\r'.encode(), b'x' * (128 * 1024)):
                digest = hashlib.sha256(payload).hexdigest()
                for options in ([], ['--reviewed-sha256', digest]):
                    result = subprocess.run(command + options, input=payload, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), {'content': payload.decode(), 'expected_sha256': digest})
            for options, payload, code in ((['--reviewed-sha256', digest], b'edited', 3),
                                          (['--reviewed-sha256', 'broken'], b'body', 2),
                                          ([], b'\xff', 2), ([], b'x' * (128 * 1024 + 1), 2)):
                result = subprocess.run(command + options, input=payload, capture_output=True)
                self.assertEqual(result.returncode, code)
                self.assertEqual(result.stdout, b'')

    def test_hosted_skill_retains_shared_text(self):
        root = Path(__file__).resolve().parents[1]
        config = {k: 'https://rumbo.company.dev/' + k for k in ('website_url','support_url','privacy_url','terms_url','video_url')}
        config.update(mcp_url='https://rumbo.company.dev/mcp', attestations={k: True for k in GATES})
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'fixture.zip'
            build_submission(root, archive, config)
            with ZipFile(archive) as package:
                self.assertFalse(any('prepare_upload' in k for k in package.namelist()))
                skill = 'skills/coordinate-work/SKILL.md'
                self.assertEqual(package.read('rumbo/' + skill), (root / 'openai-plugin/rumbo' / skill).read_bytes())
