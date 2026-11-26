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


class QuoteExponentTests(unittest.TestCase):
    """A fuzz run found that "$1e999999k" in a quote raised decimal.Overflow while reading it."""

    def test_a_scaled_number_past_what_a_decimal_holds_is_read_as_no_amount(self):
        for text in ('$1e999999k', '1e999999 thousand', '£2.5e999999M'):
            with self.subTest(text=text):
                self.assertFalse(record._is_number_sourced(5, text))
                self.assertEqual(record._sourced_numbers(text), frozenset())
        self.assertTrue(record._is_number_sourced(1500, '$1.5k'))

    def test_check_and_the_stop_gate_read_such_a_quote_without_an_error(self):
        document = budget(1, 'total_cap')
        document['objective']['quote'] = 'Budget 1 and 2, maybe $1e999999k.'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text(json.dumps(document))
            result = subprocess.run([sys.executable, str(SCRIPT), 'check', '--record', str(path)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
            transcript = Path(directory) / 't.jsonl'
            transcript.write_text(json.dumps({'type': 'user', 'origin': {'kind': 'human'},
                                              'message': {'role': 'user', 'content': document['objective']['quote']}}) + '\n')
            gate = subprocess.run([sys.executable, str(SCRIPT), 'stop-gate', '--record', str(path)],
                                  input=json.dumps({'session_id': 's1', 'transcript_path': str(transcript),
                                                    'last_assistant_message': 'Done.'}),
                                  capture_output=True, text=True, timeout=10)
            self.assertNotIn('GATE_ERROR', gate.stdout)
            self.assertEqual(gate.stdout.strip(), '')


if __name__ == '__main__':
    unittest.main()
