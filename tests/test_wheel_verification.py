"""The wheel verifier must reject accidental checkout imports and missing tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WheelVerificationTests(unittest.TestCase):
    def verifier(self):
        path = ROOT/'scripts/verify_installed_wheel.py'
        self.assertTrue(path.is_file(), 'Missing isolated-wheel verification script')
        spec = importlib.util.spec_from_file_location('verify_installed_wheel', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_installed_wheel_exercises_cli_and_read_only_checkpoint_workflows(self):
        module = self.verifier()
        self.assertTrue({'test_cli_workflows.py', 'test_readonly_verify.py', 'test_artifact_json_policy.py', 'test_decision_clock.py', 'test_json_check_cache.py'} <= set(module.TEST_FILES))

    def test_import_paths_must_belong_to_isolated_environment(self):
        module = self.verifier()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source'; installed = root/'venv'
            paths = {'rumbo': str(installed/'lib/rumbo/__init__.py'),
                     'rumbo.core': str(installed/'lib/rumbo/core.py')}
            module.validate_import_paths(source, installed, paths)
            for invalid in (source/'rumbo/core.py', root/'unrelated/rumbo/core.py'):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'isolated wheel'):
                    module.validate_import_paths(source, installed, dict(paths, **{'rumbo.core': str(invalid)}))

    def test_source_checkout_inside_environment_is_still_rejected(self):
        module = self.verifier()
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            source = prefix/'source'
            with self.assertRaisesRegex(ValueError, 'source checkout'):
                module.validate_import_paths(source, prefix, {'rumbo': str(source/'rumbo/__init__.py')})

    def test_environment_removes_python_path_injection_and_disables_indexes(self):
        module = self.verifier()
        original = {'PATH': '/usr/bin', 'PYTHONPATH': '/checkout', 'PYTHONHOME': '/other',
                    'PIP_INDEX_URL': 'https://example.invalid/simple'}
        clean = module.isolated_environment(original)
        self.assertNotIn('PYTHONPATH', clean)
        self.assertNotIn('PYTHONHOME', clean)
        self.assertEqual(clean['PIP_NO_INDEX'], '1')
        self.assertEqual(clean['PIP_DISABLE_PIP_VERSION_CHECK'], '1')
        self.assertEqual(clean['PATH'], original['PATH'])
        self.assertEqual(original['PYTHONPATH'], '/checkout')
