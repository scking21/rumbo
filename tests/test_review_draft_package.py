"""A local draft archive precedes portal verification; it never certifies release."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from scripts import package_release

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://rumbo-review-candidate.aggie-king21.chatgpt.site/mcp'


class ReviewDraftPackageTests(unittest.TestCase):
    def draft(self, root, target, config):
        builder = getattr(package_release, 'build_review_draft', None)
        self.assertTrue(callable(builder), 'A review-draft builder must not require final portal attestations')
        return builder(root, target, config)

    def test_draft_without_portal_attestations_uses_actual_sites_contract(self):
        # Fails if packaging again gates local draft creation on external review.
        config = {'mcp_url': ENDPOINT}
        original = copy.deepcopy(config)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'review-draft.zip'
            digest = self.draft(ROOT, target, config)
            self.assertEqual(config, original)
            self.assertEqual(digest, hashlib.sha256(target.read_bytes()).hexdigest())
            report = json.loads(target.with_suffix('.readiness.json').read_text())
            self.assertEqual(report['status'], 'review-draft-not-submission-ready')
            self.assertFalse(report['uploaded'])
            self.assertFalse(report['submitted'])
            self.assertEqual(report['omitted_optional_fields'], ['author'])
            self.assertEqual(report['operator_attestations'], {gate: False for gate in package_release.GATES})
            self.assertEqual(set(report['pending_external_gates']), package_release.GATES)
            self.assertEqual(set(report['pending_review_fields']), {
                'interface.developerName', 'interface.websiteURL',
                'interface.supportURL', 'interface.privacyPolicyURL',
                'interface.termsOfServiceURL', 'review.demo_recording_url'})
            with zipfile.ZipFile(target) as archive:
                manifest = json.loads(archive.read('rumbo/plugin.json'))
                mcp = json.loads(archive.read('rumbo/mcp.json'))
                names = archive.namelist()
                skills = '\n'.join(archive.read(name).decode() for name in names if name.endswith('SKILL.md'))
                self.assertFalse(any(name.startswith(('rumbo/scripts/', 'rumbo/.codex-plugin/', 'rumbo/rumbo/')) for name in names))
                self.assertEqual(mcp['mcpServers']['rumbo']['url'], ENDPOINT)
                self.assertNotIn('author', manifest)
                ext = manifest['extensions']['com.openai']
                self.assertNotIn('developerName', ext['interface'])
                self.assertNotIn('demo_recording_url', ext['review'])
                self.assertNotIn('countries', ext['publication'])
                self.assertIn('review draft', ext['publication']['release_notes'])
                cases = ext['review']['test_cases']
                source = json.loads((ROOT/'openai-sites/reviewer-cases.json').read_text())
                self.assertEqual(len(cases['positive']), len(source['positive_cases']))
                for actual, expected in zip(cases['positive'], source['positive_cases']):
                    self.assertEqual(actual['prompt'], expected['prompt'])
                    self.assertEqual(actual['tools_triggered'], ', '.join(expected['tools']))
                    self.assertEqual(actual['expected_behavior'], expected['expected'])
                self.assertEqual(len(cases['negative']), len(source['negative_cases']))
                self.assertIn('rumbo_open_worker', skills)
                self.assertIn('project_key', skills)
                self.assertIn('`content`', skills)
                self.assertNotIn('UTF-8 `text`', skills)
                self.assertNotIn('rumbo_connect_project', skills)
                self.assertNotIn('rumbo_submit_artifact', skills)
            self.assertIn('rumbo_open_worker', report['source_tool_names'])
            self.assertNotIn('rumbo_submit_artifact', report['source_tool_names'])
            self.assertNotIn('rumbo_decide', report['source_tool_names'])
            again = Path(tmp)/'again.zip'
            self.draft(ROOT, again, config)
            self.assertEqual(target.read_bytes(), again.read_bytes())
            self.assertEqual(report, json.loads(again.with_suffix('.readiness.json').read_text()))

    def test_draft_preserves_explicit_attestations_and_optional_fields(self):
        config = {'mcp_url': ENDPOINT, 'website_url': 'https://rumbo.company.dev',
                  'attestations': {'host_qa_verified': True, 'oauth_verified': False}}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'draft.zip'
            self.draft(ROOT, target, config)
            report = json.loads(target.with_suffix('.readiness.json').read_text())
            self.assertTrue(report['operator_attestations']['host_qa_verified'])
            self.assertFalse(report['operator_attestations']['oauth_verified'])
            self.assertNotIn('interface.websiteURL', report['pending_review_fields'])
            self.assertIn('oauth_verified', report['pending_external_gates'])

    def test_final_submission_still_requires_every_external_gate(self):
        config = {key: 'https://rumbo.company.dev/'+key for key in package_release.PUBLIC_FIELDS-{'attestations'}}
        config['mcp_url'] = ENDPOINT
        for missing in package_release.GATES:
            config['attestations'] = {gate: gate != missing for gate in package_release.GATES}
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)/'final.zip'
                with self.assertRaises(ValueError):
                    package_release.build_submission(ROOT, target, config)
                self.assertFalse(target.exists())

    def test_draft_rejects_placeholders_secrets_and_untyped_attestations(self):
        for extra in [{'mcp_url': 'https://example.com/mcp'}, {'token': 'synthetic-secret'},
                      {'reviewer_instructions': 'sign in'}, {'terms_url': 'http://localhost/terms'},
                      {'attestations': {'oauth_verified': 'false'}},
                      {'attestations': {'invented_gate': True}}]:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)/'draft.zip'
                with self.assertRaises(ValueError):
                    self.draft(ROOT, target, {'mcp_url': ENDPOINT, **extra})
                self.assertFalse(target.exists())

    def test_draft_validates_manifest_case_tools_and_source_allowlist(self):
        for mutation in ('manifest', 'case_tool', 'secret_file'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)/'source'
                for folder in ('openai-plugin', 'openai-sites/worker', 'schemas'):
                    shutil.copytree(ROOT/folder, root/folder)
                shutil.copy(ROOT/'openai-sites/package.json', root/'openai-sites/package.json')
                shutil.copy(ROOT/'openai-sites/reviewer-cases.json', root/'openai-sites/reviewer-cases.json')
                shutil.copy(ROOT/'LICENSE', root/'LICENSE')
                if mutation == 'manifest':
                    path = root/'openai-plugin/rumbo/plugin.json'
                    value = json.loads(path.read_text()); value['name'] = '../invalid'
                    path.write_text(json.dumps(value))
                elif mutation == 'case_tool':
                    path = root/'openai-sites/reviewer-cases.json'
                    value = json.loads(path.read_text()); value['positive_cases'][0]['tools'] = ['rumbo_submit_artifact']
                    path.write_text(json.dumps(value))
                else:
                    (root/'openai-plugin/sites-skills').mkdir(exist_ok=True)
                    (root/'openai-plugin/sites-skills/.env').write_text('synthetic secret')
                target = Path(tmp)/'draft.zip'
                with self.assertRaises(ValueError):
                    self.draft(root, target, {'mcp_url': ENDPOINT})
                self.assertFalse(target.exists())

    def test_cli_supports_draft_without_production_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'draft.zip'
            result = subprocess.run([sys.executable, str(ROOT/'scripts/package_release.py'),
                '--kind', 'review-draft', '--mcp-url', ENDPOINT, '--output', str(target)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = json.loads(result.stdout)
            self.assertEqual(result['kind'], 'review-draft')
            self.assertFalse(result['submitted'])
            self.assertEqual(result['readiness_report'], str(target.with_suffix('.readiness.json')))

    def test_source_archive_can_rebuild_review_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source.zip'
            package_release.build_source(ROOT, source)
            with zipfile.ZipFile(source) as archive:
                self.assertIn('rumbo-0.3.0-source/openai-sites/worker/protocol.js', archive.namelist())
                for name in ('tests/test_json_check_cache.py', 'openai-sites/tests/json-check-cache.test.mjs'):
                    self.assertEqual(archive.read('rumbo-0.3.0-source/'+name), (ROOT/name).read_bytes())
                self.assertFalse(any('/node_modules/' in name or '/dist/' in name for name in archive.namelist()))
                archive.extractall(Path(tmp)/'extracted')
            extracted = Path(tmp)/'extracted/rumbo-0.3.0-source'
            self.draft(extracted, Path(tmp)/'draft.zip', {'mcp_url': ENDPOINT})

    def test_cli_rejects_mcp_url_for_other_kinds(self):
        for kind in ('local', 'source', 'submission'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)/'wrong.zip'
                result = subprocess.run([sys.executable, str(ROOT/'scripts/package_release.py'),
                    '--kind', kind, '--mcp-url', ENDPOINT, '--output', str(target)],
                    capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(target.exists())

    def test_source_rejects_unreviewed_sites_inputs(self):
        for name in ('openai-sites/credentials.json', 'openai-sites/worker/private.js'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)/'source'; planted = root/name
                planted.parent.mkdir(parents=True); planted.write_text('synthetic private input')
                target = Path(tmp)/'source.zip'
                with self.assertRaises(ValueError):
                    package_release.build_source(root, target)
                self.assertFalse(target.exists())
