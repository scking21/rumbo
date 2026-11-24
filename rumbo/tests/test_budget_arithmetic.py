"""Budget arithmetic follows the decimal values shown in JSON records."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'record.py'
SPEC = importlib.util.spec_from_file_location('budget_record', SCRIPT)
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)


class BudgetArithmeticTests(unittest.TestCase):
    def check(self, amounts, cap, item_cap=None):
        check = dict(kind='within_budget', amounts=amounts, total_cap=cap)
        if item_cap is not None:
            check['item_cap'] = item_cap
        return record.evaluate_check(check)

    def test_decimal_sum_at_cap_passes(self):
        self.assertEqual(self.check([0.1, 0.2], 0.3), (True, None))
        self.assertEqual(self.check([0.01] * 100, 1), (True, None))

    def test_small_real_excess_is_not_rounded_away(self):
        self.assertEqual(self.check([0.1, 0.20000000000000004], 0.3),
                         (False, 'total 0.30000000000000004 exceeds total_cap 0.3 by 0.00000000000000004'))

    def test_huge_integer_and_fraction_remain_exact(self):
        huge = 10 ** 400
        self.assertEqual(self.check([huge, 0.5], huge + 1), (True, None))
        self.assertEqual(self.check([huge, 0.5], huge),
                         (False, 'total '+str(huge)+'.5 exceeds total_cap '+str(huge)+' by 0.5'))

    def test_finite_float_sum_does_not_overflow(self):
        passed, detail = self.check([1e308, 1e308], 1e308)
        self.assertFalse(passed)
        self.assertNotIn('inf', detail)

    def test_individual_cap_keeps_exact_decimal_excess(self):
        self.assertEqual(self.check([0.30000000000000004], 1, 0.3),
                         (False, 'amount 0.30000000000000004 exceeds item_cap 0.3'))

    def test_a_named_amount_is_refused_with_how_to_name_it(self):
        # A live agent wrote {"label": "Paid social", "amount": 300}; the old message
        # pointed it at unit and quantity, which is not what a plain amount needs.
        base = dict(version=1, objective=dict(text='Budget', quote='$300 ads, $500 cap'), items=[])
        named = dict(base, checks=[dict(id='C1', kind='within_budget', total_cap=500,
                                        amounts=[{'label': 'Paid social', 'amount': 300}])])
        self.assertEqual(record.validate_record(named), [
            'checks[0].amounts[0]: CHECK_BAD_VALUE: use the amount as a plain number and name the lines '
            'in the check\'s label, or {"unit": N, "quantity": N} for a price per unit'])
        priced = dict(base, checks=[dict(id='C1', kind='within_budget', total_cap=500,
                                         amounts=[{'unit': 30, 'quantity': 10, 'label': 'ads'}])])
        self.assertEqual(record.validate_record(priced), [
            'checks[0].amounts[0]: CHECK_BAD_VALUE: use {"unit": N, "quantity": N} with exactly those two keys'])

    def test_cli_reports_decimal_budget_pass(self):
        document = dict(version=1, objective=dict(text='Synthetic budget', quote='Items 0.1 and 0.2, total cap 0.3'),
                        items=[], checks=[dict(id='budget', kind='within_budget', amounts=[0.1, 0.2], total_cap=0.3)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text(json.dumps(document))
            result = subprocess.run([sys.executable, str(SCRIPT), 'check', '--record', str(path)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual((result.returncode, result.stdout.strip(), result.stderr),
                             (0, 'budget: PASS within_budget', ''))


if __name__ == '__main__':
    unittest.main()
