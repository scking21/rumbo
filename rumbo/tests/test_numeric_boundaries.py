"""Numeric inputs must be usable by the legacy planning checker."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'record.py'
SPEC = importlib.util.spec_from_file_location('numeric_record', SCRIPT)
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)


def budget(value, field):
    check = dict(id='budget', kind='within_budget', amounts=[1], total_cap=2, item_cap=2)
    check[field] = [value] if field == 'amounts' else value
    return dict(version=1, objective=dict(text='Synthetic budget', quote='Budget 1 and 2'),
                items=[], checks=[check])


class NumericBoundaryTests(unittest.TestCase):
    def test_nonfinite_budget_values_are_validation_faults(self):
        for value in (float('nan'), float('inf'), float('-inf')):
            for field in ('amounts', 'total_cap', 'item_cap'):
                with self.subTest(value=value, field=field):
                    faults = record.validate_record(budget(value, field))
                    self.assertTrue(any('CHECK_BAD_VALUE' in fault and field in fault for fault in faults), faults)

    def test_cli_rejects_overflowing_json_budget_before_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text(json.dumps(budget(1, 'total_cap')).replace('"total_cap": 1', '"total_cap": 1e999'))
            for command in ('validate', 'check'):
                with self.subTest(command=command):
                    result = subprocess.run([sys.executable, str(SCRIPT), command, '--record', str(path)],
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn('total_cap: CHECK_BAD_VALUE', result.stdout)
                    self.assertNotIn('Traceback', result.stderr)

    def test_finite_numbers_and_large_integers_remain_valid(self):
        for value in (0, 1, 1.5, 1e308, 10 ** 400):
            with self.subTest(value=value):
                self.assertEqual(record.validate_record(budget(value, 'total_cap')), [])


if __name__ == '__main__':
    unittest.main()
