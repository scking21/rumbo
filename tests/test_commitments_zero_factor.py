"""Packaged Codex commitments must not accept invented zero price factors."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from scripts.package_release import build_local


ROOT = Path(__file__).resolve().parents[1]


class CommitmentsZeroFactorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rumbo zero factor ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        archive = self.base / "local.zip"
        build_local(ROOT, archive)
        with zipfile.ZipFile(archive) as package:
            package.extractall(self.base / "package")
        self.helper = self.base / "package/rumbo/scripts/commitments.py"
        self.record = self.base / "project/.rumbo/record.json"
        self.record.parent.mkdir(parents=True)

    def check(self, quote, amounts):
        document = {
            "version": 1,
            "objective": {"text": "Check catering budget", "quote": quote},
            "items": [],
            "checks": [{
                "id": "C1",
                "kind": "within_budget",
                "amounts": amounts,
                "total_cap": 500,
                "refs": [],
            }],
        }
        self.record.write_text(json.dumps(document), encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-I", "-S", str(self.helper),
             "check", "--record", str(self.record)],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_an_unstated_zero_quantity_is_unsourced(self):
        result = self.check(
            "Catering is $25 per attendee; the budget is $500.",
            [{"unit": 25, "quantity": 0}],
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("amounts quantity 0", result.stdout)
        self.assertIn("UNSOURCED", result.stdout)

    def test_an_explicit_zero_quantity_is_sourced(self):
        result = self.check(
            "Catering is $25 per attendee for 0 attendees; the budget is $500.",
            [{"unit": 25, "quantity": 0}],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "C1: PASS within_budget")

    def test_named_zero_quantities_are_sourced(self):
        for phrase, unit in (("zero attendees", "attendee"),
                             ("no attendees", "attendee"),
                             ("0 bicycles", "bicycle")):
            with self.subTest(phrase=phrase):
                result = self.check(
                    f"Catering is $25 per {unit} for {phrase}; the budget is $500.",
                    [{"unit": 25, "quantity": 0}],
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), "C1: PASS within_budget")

    def test_named_free_units_are_sourced(self):
        for phrase in ("free", "at no charge"):
            with self.subTest(phrase=phrase):
                result = self.check(
                    f"Catering is {phrase} for 12 attendees; the budget is $500.",
                    [{"unit": 0, "quantity": 12}],
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), "C1: PASS within_budget")

    def test_zero_for_a_different_line_item_does_not_source_quantity(self):
        result = self.check(
            "The venue fee is $0. Catering is $25 per attendee; the budget is $500.",
            [{"unit": 25, "quantity": 0}],
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("amounts quantity 0", result.stdout)

    def test_zero_count_can_follow_numeric_rate_in_the_next_clause(self):
        result = self.check(
            "Catering costs $25 per attendee. We now expect zero attendees. The budget is $500.",
            [{"unit": 25, "quantity": 0}],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "C1: PASS within_budget")

    def test_zero_count_for_another_unit_does_not_replace_attendees(self):
        result = self.check(
            "Catering costs $25 per attendee for 10 attendees and 0 bicycles; the budget is $500.",
            [{"unit": 25, "quantity": 0}],
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("amounts quantity 0", result.stdout)

    def test_free_different_line_item_does_not_source_unit(self):
        result = self.check(
            "The venue is free. Catering serves 12 attendees; the budget is $500.",
            [{"unit": 0, "quantity": 12}],
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("amounts unit 0", result.stdout)

    def test_decimal_unit_price_keeps_zero_quantity_in_the_same_clause(self):
        result = self.check(
            "Catering is $25.50 per attendee for 0 attendees; the budget is $500.",
            [{"unit": 25.50, "quantity": 0}],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "C1: PASS within_budget")

    def test_nonzero_decimal_price_does_not_source_a_zero_unit(self):
        result = self.check(
            "Catering costs $0.50 for 12 attendees; the budget is $500.",
            [{"unit": 0, "quantity": 12}],
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("amounts unit 0", result.stdout)

    def test_negated_free_does_not_source_a_zero_unit(self):
        result = self.check(
            "Catering is not free for 12 attendees; the budget is $500.",
            [{"unit": 0, "quantity": 12}],
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("amounts unit 0", result.stdout)

    def test_no_for_an_unrelated_noun_does_not_source_quantity(self):
        result = self.check(
            "Catering costs $25 per attendee with no discounts; the budget is $500.",
            [{"unit": 25, "quantity": 0}],
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("amounts quantity 0", result.stdout)

    def test_an_ordinary_nonzero_quantity_still_passes(self):
        result = self.check(
            "Catering is $25 per attendee for 12 attendees; the budget is $500.",
            [{"unit": 25, "quantity": 12}],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "C1: PASS within_budget")

    def test_a_scalar_free_cost_keeps_the_existing_zero_exception(self):
        result = self.check(
            "The venue is free; the budget is $500.",
            [0],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "C1: PASS within_budget")


if __name__ == "__main__":
    unittest.main()
