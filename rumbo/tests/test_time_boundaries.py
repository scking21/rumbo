"""Malformed clock input is a content fault, not an uncaught exception."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'record.py'
SPEC = importlib.util.spec_from_file_location('time_record', SCRIPT)
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)


class TimeBoundaryTests(unittest.TestCase):
    def test_non_decimal_digits_are_invalid_times(self):
        for value in ('²²:00', '00:²²', '❶❷:00', '00:₀₀'):
            with self.subTest(value=value):
                self.assertIsNone(record.parse_time(value))

    def test_cli_reports_bad_time_without_traceback(self):
        document = dict(version=1, objective=dict(text='Synthetic schedule', quote='Start 09:00 end 10:00'),
                        items=[], checks=[dict(id='time', kind='fits_window', start='²²:00', end='10:00', segments_min=[1])])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text(json.dumps(document))
            result = subprocess.run([sys.executable, str(SCRIPT), 'validate', '--record', str(path)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn('start: CHECK_BAD_VALUE', result.stdout)
            self.assertNotIn('Traceback', result.stderr)

    def test_existing_decimal_digits_and_valid_edges_still_parse(self):
        for value, expected in [('00:00', 0), ('23:59', 1439), ('٠٩:٣٠', 570)]:
            with self.subTest(value=value):
                self.assertEqual(record.parse_time(value), expected)


if __name__ == '__main__':
    unittest.main()
