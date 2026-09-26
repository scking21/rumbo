#!/usr/bin/env python3
"""Unit tests for scripts/record.py"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------- helpers


def run_record(args, input_text="", cwd=None, env=None):
    """Run scripts/record.py with given args; return (exitcode, stdout, stderr)."""
    cmd = [sys.executable, "scripts/record.py"] + args
    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        cwd=cwd,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def make_temp_dir():
    td = tempfile.TemporaryDirectory()
    return td, td.name


class RecordTest(unittest.TestCase):
    # ----------------------------------------------------------------- fixtures

    def setUp(self):
        self.td, self.dir = make_temp_dir()
        self.addCleanup(self.td.cleanup)
        self.record_path = os.path.join(self.dir, ".rumbo", "record.json")
        os.makedirs(os.path.dirname(self.record_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.record_path), exist_ok=True)

    def workshop_record(self):
        """Return a deep copy of the workshop fixture."""
        fixture_path = os.path.join(
            os.path.dirname(__file__), "fixtures", "workshop.json"
        )
        with open(fixture_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    # --------------------------------------------------------------- validate

    def test_workshop_fixture_validation(self):
        record = self.workshop_record()
        os.makedirs(os.path.dirname(self.record_path), exist_ok=True)
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "RECORD_OK")
        self.assertEqual(err, "")

    def test_missing_file(self):
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(err.strip(), "RECORD_NOT_FOUND")

    def test_bad_json(self):
        with open(self.record_path, "w", encoding="utf-8") as handle:
            handle.write("{ not valid json")
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(err.strip(), "RECORD_UNREADABLE")

    # missing/empty fields
    def test_missing_objective(self):
        record = {"version": 1, "items": [], "checks": []}
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("objective: RECORD_MISSING_FIELD", out)
        self.assertEqual(err, "")

    def test_empty_objective_text(self):
        record = {
            "version": 1,
            "objective": {"text": "", "quote": "something"},
            "items": [],
            "checks": [],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("objective.text: RECORD_EMPTY_FIELD", out)

    def test_empty_objective_quote(self):
        record = {
            "version": 1,
            "objective": {"text": "something", "quote": ""},
            "items": [],
            "checks": [],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("objective.quote: RECORD_EMPTY_FIELD", out)

    def test_bad_status(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [{"id": "I1", "text": "t", "quote": "q", "status": "nope"}],
            "checks": [],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("items[0].status: RECORD_BAD_STATUS", out)

    def test_duplicate_item_id(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [
                {"id": "I1", "text": "t1", "quote": "q1", "status": "draft"},
                {"id": "I1", "text": "t2", "quote": "q2", "status": "draft"},
            ],
            "checks": [],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("items[1].id: RECORD_DUP_ID", out)

    def test_bad_ref_in_items(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [
                {"id": "I1", "text": "t1", "quote": "q1", "status": "draft"},
                {"id": "I2", "text": "t2", "quote": "q2", "status": "draft", "replaces": ["I9"]},
            ],
            "checks": [],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("items[1].replaces[0]: RECORD_BAD_REF", out)

    def test_bad_check_kind(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [],
            "checks": [{"id": "C1", "kind": "unknown"}],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("checks[0].kind: CHECK_BAD_KIND", out)

    def test_fits_window_bad_time(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "25:00",
                    "end": "12:30",
                    "segments_min": [60],
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("checks[0].start: CHECK_BAD_VALUE", out)

    def test_fits_window_bad_segments(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:00",
                    "end": "12:00",
                    "segments_min": [0],
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("checks[0].segments_min[0]: CHECK_BAD_VALUE", out)

    def test_before_bad_date(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "before",
                    "first": "not-a-date",
                    "second": "2026-03-12",
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("checks[0].first: CHECK_BAD_VALUE", out)

    def test_within_budget_bad_amounts(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "within_budget",
                    "amounts": [-5],
                    "total_cap": 100,
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["validate", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("checks[0].amounts[0]: CHECK_BAD_VALUE", out)

    # --------------------------------------------------------------- check

    def test_workshop_fixture_check_output_and_exit(self):
        record = self.workshop_record()
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # because checks fail
        lines = out.strip().splitlines()
        self.assertEqual(
            lines[0], "C1: FAIL fits_window session schedule: 09:45 + 170 min ends 12:35, 5 min after 12:30"
        )
        self.assertEqual(
            lines[1], "C2: FAIL before printer deadline precedes workshop: 2026-03-20 is 8 days after 2026-03-12 (also unsourced: first year 2026, second year 2026)"
        )
        self.assertEqual(lines[2], "C3: PASS within_budget budget")
        self.assertEqual(err, "")

    def test_check_missing_file(self):
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(err.strip(), "RECORD_NOT_FOUND")

    def test_check_invalid_json(self):
        with open(self.record_path, "w", encoding="utf-8") as handle:
            handle.write("{")
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(err.strip(), "RECORD_UNREADABLE")

    def test_check_passes_when_no_checks(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [],
            "checks": [],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        self.assertEqual(err, "")

    # --------------------------------------------------------------- show

    def test_show_missing_file_silent(self):
        code, out, err = run_record(["show", "--record", self.record_path])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        self.assertEqual(err, "")

    def test_show_invalid_record(self):
        with open(self.record_path, "w", encoding="utf-8") as handle:
            handle.write("{ invalid json")
        code, out, err = run_record(["show", "--record", self.record_path])
        self.assertEqual(code, 0)
        self.assertEqual(
            out.strip(), "rumbo: record invalid, run record.py validate"
        )
        self.assertEqual(err, "")

    def test_show_workshop_fixture(self):
        record = self.workshop_record()
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["show", "--record", self.record_path])
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(lines[0], "Objective: Plan a half-day workshop on March 12")
        # order: commitment, then draft
        self.assertTrue(lines[1].startswith("[commitment] I2"))
        self.assertTrue(lines[2].startswith("[commitment] I3"))
        self.assertTrue(lines[3].startswith("[commitment] I4"))
        self.assertTrue(lines[4].startswith("[commitment] I5"))
        self.assertTrue(lines[5].startswith("[draft] I1"))
        # conflict lines
        self.assertTrue(
            any(line.startswith("CONFLICT C1:") for line in lines),
            msg="missing C1 conflict line",
        )
        self.assertTrue(
            any(line.startswith("CONFLICT C2:") for line in lines),
            msg="missing C2 conflict line",
        )
        self.assertEqual(err, "")

    def test_show_omits_done_and_rejected_and_replaced(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [
                {"id": "I1", "text": "done item", "quote": "q", "status": "done"},
                {"id": "I2", "text": "rejected", "quote": "q", "status": "rejected"},
                {"id": "I3", "text": "replaced", "quote": "q", "status": "draft", "replaces": ["I4"]},
                {"id": "I4", "text": "replacement", "quote": "q", "status": "draft"},
            ],
            "checks": [],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["show", "--record", self.record_path])
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(lines[0], "Objective: x")
        # I3 replaces I4, so I4 (the replaced item) is omitted; I3 is shown.
        self.assertTrue(any(line.startswith("[draft] I3") for line in lines))
        self.assertFalse(any("I1" in line for line in lines))
        self.assertFalse(any("I2" in line for line in lines))
        self.assertFalse(any("I4" in line for line in lines))

    def test_show_orders_by_status(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "y"},
            "items": [
                {"id": "I1", "text": "exploring", "quote": "q", "status": "exploring"},
                {"id": "I2", "text": "commitment", "quote": "q", "status": "commitment"},
                {"id": "I3", "text": "draft", "quote": "q", "status": "draft"},
            ],
            "checks": [],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["show", "--record", self.record_path])
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()[1:]  # skip objective line
        self.assertTrue(lines[0].startswith("[commitment] I2"))
        self.assertTrue(lines[1].startswith("[draft] I3"))
        self.assertTrue(lines[2].startswith("[exploring] I1"))

    def test_show_truncation(self):
        record = {
            "version": 1,
            "objective": {"text": "x" * 2000, "quote": "y"},
            "items": [],
            "checks": [],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["show", "--max-chars", "10", "--record", self.record_path])
        self.assertEqual(code, 0)
        self.assertTrue(out.rstrip("\n").endswith("…(truncated)"))
        self.assertLessEqual(len(out.rstrip("\n")), 10 + len("…(truncated)"))

    def schedule_prompt(self):
        return json.dumps(
            {"prompt": "Please draft the schedule: 9:00 arrival, 12:30 close."}
        )

    def test_show_nudge_on_planning_prompt(self):
        code, out, err = run_record(
            ["show", "--record", self.record_path], input_text=self.schedule_prompt()
        )
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("rumbo: no decision record yet."))
        self.assertIn(self.record_path, out)
        self.assertEqual(err, "")

    def test_show_nudge_on_month_date_prompt(self):
        payload = json.dumps(
            {"prompt": "I'm organizing a workshop the morning of March 12"}
        )
        code, out, err = run_record(
            ["show", "--record", self.record_path], input_text=payload
        )
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("rumbo: no decision record yet."))
        self.assertIn(self.record_path, out)
        self.assertEqual(err, "")

    def test_show_silent_on_non_planning_prompt(self):
        payload = json.dumps({"prompt": "fix the typo in README.md"})
        code, out, err = run_record(
            ["show", "--record", self.record_path], input_text=payload
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_show_silent_on_non_json_stdin(self):
        code, out, err = run_record(
            ["show", "--record", self.record_path], input_text="not json"
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_show_existing_record_shows_summary_not_nudge(self):
        record = self.workshop_record()
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(
            ["show", "--record", self.record_path], input_text=self.schedule_prompt()
        )
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertTrue(lines[0].startswith("Objective: "))
        self.assertNotIn("no decision record yet", out)
        self.assertEqual(err, "")

    # --------------------------------------------------------------- init

    def test_init_creates_file_and_parent_dirs(self):
        deep = os.path.join(self.dir, "deep", "path", ".rumbo", "record.json")
        code, out, err = run_record(
            ["init", "--objective", "text", "--quote", "quote", "--record", deep]
        )
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(deep))
        with open(deep, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["objective"]["text"], "text")
        self.assertEqual(data["objective"]["quote"], "quote")
        self.assertEqual(data["items"], [])
        self.assertEqual(data["checks"], [])

    def test_init_refuses_to_overwrite(self):
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1}, handle)
        code, out, err = run_record(
            ["init", "--objective", "text", "--quote", "quote", "--record", self.record_path]
        )
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "")
        self.assertEqual(err.strip(), "RECORD_EXISTS")
        # file untouched
        with open(self.record_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data, {"version": 1})

    def test_init_quote_from_stdin_preserves_dollar_and_backtick(self):
        code, out, err = run_record(
            ["init", "--objective", "text", "--quote", "-", "--record", self.record_path],
            input_text="we've budgeted $600 total, `x`\n",
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertTrue(os.path.isfile(self.record_path))
        with open(self.record_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["objective"]["quote"], "we've budgeted $600 total, `x`")
        self.assertEqual(data["objective"]["text"], "text")

    def test_init_quote_from_stdin_empty_exits_1_and_writes_nothing(self):
        code, out, err = run_record(
            ["init", "--objective", "text", "--quote", "-", "--record", self.record_path],
            input_text="",
        )
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "")
        self.assertEqual(
            err.strip(), "RECORD_EMPTY_FIELD: quote from stdin was empty"
        )
        self.assertFalse(os.path.exists(self.record_path))

    # --------------------------------------------------------------- stop-gate

    def test_stop_gate_no_input_silent(self):
        code, out, err = run_record(["stop-gate", "--record", self.record_path], input_text="")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        self.assertEqual(err, "")

    def test_stop_gate_garbage_json_silent(self):
        code, out, err = run_record(["stop-gate", "--record", self.record_path], input_text="{ not valid")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        self.assertEqual(err, "")

    def test_stop_gate_stop_hook_active_true_silent(self):
        payload = {"stop_hook_active": True}
        code, out, err = run_record(
            ["stop-gate", "--record", self.record_path], input_text=json.dumps(payload)
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        self.assertEqual(err, "")

    def test_stop_gate_missing_record_silent(self):
        code, out, err = run_record(["stop-gate", "--record", self.record_path], input_text="{}")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        self.assertEqual(err, "")

    def test_stop_gate_blocks_on_failing_checks(self):
        record = self.workshop_record()
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["stop-gate", "--record", self.record_path], input_text="{}")
        self.assertEqual(code, 0)
        self.assertTrue(out.strip().startswith("{"))
        payload = json.loads(out.strip())
        self.assertEqual(payload["decision"], "block")
        self.assertIn("C1: FAIL", payload["reason"])
        self.assertIn("C2: FAIL", payload["reason"])
        self.assertIn("Before finishing", payload["reason"])
        self.assertEqual(err, "")

    def test_stop_gate_silent_when_checks_pass(self):
        record = {
            "version": 1,
            "objective": {"text": "x", "quote": "x 09:00 12:00 60"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:00",
                    "end": "12:00",
                    "segments_min": [60],
                    "label": "morning",
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["stop-gate", "--record", self.record_path], input_text="{}")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        self.assertEqual(err, "")

    # New tests as per ticket T5c
    def test_fits_window_unsourced_segment_15(self):
        """fits_window with a segment 15 absent from all quotes -> UNSOURCED line naming segments_min 15, exit 1, and stop-gate blocks"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Doors at 9:00, done by 12:00."},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:00",
                    "end": "12:00",
                    "segments_min": [15],  # 15 is not in the quote
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)

        # Test check command
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # fails due to unsourced
        self.assertIn("C1: UNSOURCED fits_window: segments_min 15 not in the user's quoted words", out)
        self.assertEqual(err, "")

        # Test stop-gate blocks
        code, out, err = run_record(["stop-gate", "--record", self.record_path], input_text="{}")
        self.assertEqual(code, 0)
        self.assertTrue(out.strip().startswith("{"))
        payload = json.loads(out.strip())
        self.assertEqual(payload["decision"], "block")
        self.assertIn("C1: UNSOURCED fits_window: segments_min 15 not in the user's quoted words", payload["reason"])

    def test_before_check_unsourced_year(self):
        """before check with first 2025-03-20 and quotes lacking '2025' -> names 'first year 2025'"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Printer by March 10, event on March 12"},  # lacks 2025 year
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "before",
                    "first": "2025-03-10",
                    "second": "2025-03-12",
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)

        # Test check command
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # fails due to unsourced
        self.assertIn("C1: UNSOURCED before: first year 2025, second year 2025 not in the user's quoted words", out)
        self.assertEqual(err, "")

    def test_fully_sourced_passing_record(self):
        """a fully sourced passing record -> 'PASS', exit 0, stop-gate silent"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Start at 09:00, end by 12:00, budget 500 total"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:00",
                    "end": "12:00",
                    "segments_min": [60, 60, 60],  # all sourced: 09:00, 12:00, 60 (from total 500? no wait...)
                }
            ],
        }
        # Actually let's make a better sourced example
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Start 09:00 until 12:00 with three 60-minute sessions"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:00",
                    "end": "12:00",
                    "segments_min": [60, 60, 60],
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)

        # Test check command - should pass
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 0)  # passes
        self.assertEqual(out.strip(), "C1: PASS fits_window")
        self.assertEqual(err, "")

        # Test stop-gate silent
        code, out, err = run_record(["stop-gate", "--record", self.record_path], input_text="{}")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        self.assertEqual(err, "")

    def test_within_budget_amount_zero_never_flagged(self):
        """within_budget with amount 0 never flagged"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "The cap is 1000 and the speaker is free"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "within_budget",
                    "amounts": [0],  # zero amount should never be flagged as unsourced
                    "total_cap": 1000,
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)

        # Test check command - should pass and not flag zero as unsourced
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 0)  # passes
        self.assertEqual(out.strip(), "C1: PASS within_budget")
        self.assertEqual(err, "")

    # Tests for ticket T7: before check accepts MM-DD format
    def test_before_mmdd_passes_when_first_leq_second(self):
        """MM-DD before check passes when first <= second"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "March 12 and March 20"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "before",
                    "first": "03-12",
                    "second": "03-20",
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 0)  # should pass
        self.assertEqual(out.strip(), "C1: PASS before")
        self.assertEqual(err, "")

    def test_before_mmdd_fails_with_correct_message(self):
        """MM-DD before check fails with correct day difference message"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "March 12 and March 20"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "before",
                    "first": "03-20",
                    "second": "03-12",
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # should fail
        self.assertEqual(out.strip(), "C1: FAIL before: 03-20 is 8 days after 03-12")
        self.assertEqual(err, "")

    def test_before_mixed_formats_rejected(self):
        """Mixed date formats (MM-DD and YYYY-MM-DD) are rejected"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "March 12, 2026 and March 20"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "before",
                    "first": "03-12",
                    "second": "2026-03-20",
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # should fail validation
        # Should be a validation error on second field
        self.assertIn("checks[0].second: CHECK_BAD_VALUE: use the same date format for first and second", out)
        self.assertEqual(err, "")

    def test_before_mmdd_no_unsourced_values_when_sourced(self):
        """MM-DD before check reports no unsourced values when month-day is sourced"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Printer by March 10, event on March 12"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "before",
                    "first": "03-10",
                    "second": "03-12",
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 0)  # should pass
        self.assertEqual(out.strip(), "C1: PASS before")
        self.assertEqual(err, "")

    def test_show_prints_assumption_line_for_unsourced_check(self):
        """show prints an 'ASSUMPTION' line for an UNSOURCED check"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Some text"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:00",  # not in quote
                    "end": "10:00",   # not in quote
                    "segments_min": [30],  # not in quote
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)

        code, out, err = run_record(["show", "--record", self.record_path])
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(lines[0], "Objective: Test")
        # Should have ASSUMPTION line for the unsourced check
        assumption_lines = [line for line in lines if line.startswith("ASSUMPTION C1:")]
        self.assertTrue(len(assumption_lines) > 0, "No ASSUMPTION line found")
        self.assertEqual(assumption_lines[0], "ASSUMPTION C1: start 09:00, end 10:00, segments_min 30 not in the user's quoted words")

    # Tests for ticket T6: Stop hook enforce the "no decision record yet" nudge once per session.
    def test_stop_gate_enforces_nudge_once_per_session(self):
        # Use a temporary directory for state
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env["RUMBO_STATE_DIR"] = tmpdir
            # Use a record path that does not exist to trigger the missing record path.
            record_path = os.path.join(tmpdir, ".rumbo", "record.json")

            # 1. Show with a planning prompt and session_id "s1" writes the marker.
            prompt_s1 = json.dumps({"prompt": "Let's meet at 9:00", "session_id": "s1"})
            code, out, err = run_record(["show", "--record", record_path], input_text=prompt_s1, env=env)
            self.assertEqual(code, 0)
            self.assertTrue(out.startswith("rumbo: no decision record yet."))
            # Check that marker file exists.
            marker_path = os.path.join(tmpdir, "s1.nudged")
            self.assertTrue(os.path.exists(marker_path), f"Marker not found at {marker_path}")

            # 2. Stop-gate with {"session_id":"s1"} and no record blocks with the reason.
            code2, out2, err2 = run_record(["stop-gate", "--record", record_path], input_text=json.dumps({"session_id": "s1"}), env=env)
            self.assertEqual(code2, 0)
            self.assertTrue(out2.strip().startswith("{"), f"Expected JSON output, got: {out2}")
            payload = json.loads(out2.strip())
            self.assertEqual(payload["decision"], "block")
            self.assertIn("This session looked like planning work", payload["reason"])
            # Check that marker was renamed to .enforced.
            enforced_path = os.path.join(tmpdir, "s1.enforced")
            self.assertTrue(os.path.exists(enforced_path), f"Enforced marker not found at {enforced_path}")
            self.assertFalse(os.path.exists(marker_path), f"Original marker still exists at {marker_path}")

            # 3. A second stop-gate call for s1 is silent.
            code3, out3, err3 = run_record(["stop-gate", "--record", record_path], input_text=json.dumps({"session_id": "s1"}), env=env)
            self.assertEqual(code3, 0)
            self.assertEqual(out3.strip(), "", f"Expected silent, got: {out3}")
            self.assertEqual(err3, "", f"Unexpected stderr: {err3}")

            # 4. Stop-gate for a session with no marker is silent.
            code4, out4, err4 = run_record(["stop-gate", "--record", record_path], input_text=json.dumps({"session_id": "s2"}), env=env)
            self.assertEqual(code4, 0)
            self.assertEqual(out4.strip(), "", f"Expected silent for s2, got: {out4}")
            self.assertEqual(err4, "", f"Unexpected stderr for s2: {err4}")

            # 5. stop_hook_active true is silent even with a marker.
            # Create a fresh marker for s3.
            prompt_s3 = json.dumps({"prompt": "Let's meet at 10:00", "session_id": "s3"})
            code5, out5, err5 = run_record(["show", "--record", record_path], input_text=prompt_s3, env=env)
            self.assertEqual(code5, 0)
            self.assertTrue(out5.startswith("rumbo: no decision record yet."))
            marker_s3 = os.path.join(tmpdir, "s3.nudged")
            self.assertTrue(os.path.exists(marker_s3))
            # Now call stop-gate with stop_hook_active true.
            code6, out6, err6 = run_record(["stop-gate", "--record", record_path], input_text=json.dumps({"session_id": "s3", "stop_hook_active": True}), env=env)
            self.assertEqual(code6, 0)
            self.assertEqual(out6.strip(), "", f"Expected silent with stop_hook_active true, got: {out6}")
            self.assertEqual(err6, "", f"Unexpected stderr: {err6}")
            # Marker should still exist (not renamed).
            self.assertTrue(os.path.exists(marker_s3), f"Marker for s3 was incorrectly removed or renamed")

            # 6. A non-planning prompt writes no marker.
            prompt_s4 = json.dumps({"prompt": "fix the typo", "session_id": "s4"})
            code7, out7, err7 = run_record(["show", "--record", record_path], input_text=prompt_s4, env=env)
            self.assertEqual(code7, 0)
            self.assertEqual(out7.strip(), "", f"Expected no output for non-planning prompt, got: {out7}")
            marker_s4 = os.path.join(tmpdir, "s4.nudged")
            self.assertFalse(os.path.exists(marker_s4), f"Marker incorrectly created for non-planning prompt: {marker_s4}")

    # Regression tests for ticket T9b
    def test_partial_token_number_not_sourced(self):
        """Defect 1: partial-token matches should not count as sourced.
        Quote: "Tickets cost $1.50 each; doors 19:45."
        Check: amounts [1], total_cap 1 should be UNSOURCED (1 is not the same as 1.50)
        """
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Tickets cost $1.50 each; doors 19:45."},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "within_budget",
                    "amounts": [1],
                    "total_cap": 1
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # fails due to unsourced
        self.assertIn("amounts 1", out)
        self.assertIn("total_cap 1", out)
        self.assertEqual(err, "")

    def test_partial_token_time_not_sourced(self):
        """Defect 1: partial-token matches should not count as sourced.
        Quote: "Tickets cost $1.50 each; doors 19:45."
        Check: start "09:45" should be UNSOURCED (09:45 is not the same as 19:45)
        """
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Tickets cost $1.50 each; doors 19:45."},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:45",
                    "end": "10:00",
                    "segments_min": [15]
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # fails due to unsourced
        self.assertIn("C1: UNSOURCED fits_window", out)
        self.assertIn("start 09:45", out)
        self.assertEqual(err, "")

    def test_items_null_does_not_crash(self):
        """Defect 2: "items": null should not cause TypeError in source check.
        Record with "items": null and a within_budget check whose values appear in quote
        should pass with no Traceback in stderr.
        """
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Budget is 500 dollars"},
            "items": None,  # This used to cause TypeError: 'NoneType' object is not iterable
            "checks": [
                {
                    "id": "C1",
                    "kind": "within_budget",
                    "amounts": [500],
                    "total_cap": 500  # sourced by "Budget is 500 dollars"
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 0)  # should pass
        self.assertEqual(out.strip(), "C1: PASS within_budget")
        self.assertEqual(err, "")  # no Traceback

    def test_positive_control_time_and_money_sourced(self):
        """Positive control: quote "doors 9:45, budget $600" with fits_window start "09:45"
        and within_budget total_cap 600 reports no unsourced values.
        """
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "doors 9:45, budget $600"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:45",
                    "end": "09:45",
                    "segments_min": [9]  # 9 is sourced by the "9" in "09:45"
                },
                {
                    "id": "C2",
                    "kind": "within_budget",
                    "amounts": [0],  # 0 is always sourced
                    "total_cap": 600   # 600 is sourced by "$600"
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        # We expect the check to fail due to arithmetic in C1, but there should be no unsourced values.
        self.assertEqual(code, 1)  # because C1 fails
        self.assertNotIn("UNSOURCED", out)
        self.assertIn("C1: FAIL fits_window", out)
        self.assertIn("C2: PASS within_budget", out)
        self.assertEqual(err, "")

    def test_number_1_5_sourced_by_1_50_and_600_by_600_00(self):
        """Positive test: within_budget amount 1.5 is sourced by quote "Tickets cost $1.50"
        and total_cap 600 by "600.00" (no unsourced values; check exits 0).
        """
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "Tickets cost $1.50 and the limit is 600.00"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "within_budget",
                    "amounts": [1.5],
                    "total_cap": 600
                }
            ],
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 0)  # should pass
        self.assertEqual(out.strip(), "C1: PASS within_budget")
        self.assertEqual(err, "")

    def test_before_impossible_mmdd_is_bad_value_not_crash(self):
        record = {"version": 1, "objective": {"text": "x", "quote": "y"}, "items": [],
                  "checks": [{"id": "C1", "kind": "before", "first": "02-30", "second": "03-12"}]}
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)
        self.assertIn("checks[0].first: CHECK_BAD_VALUE", out)
        self.assertNotIn("Traceback", err)

    # Tests for ticket T10: make the source check compare parsed VALUES instead of text patterns
    def test_refund_negative_number_unsourced(self):
        """quote "refund -$50": within_budget amounts [50], total_cap 50 -> output names "amounts 50" as unsourced."""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "refund -$50"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "within_budget",
                    "amounts": [50],
                    "total_cap": 50
                }
            ]
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # fails due to unsourced
        self.assertIn("C1: UNSOURCED", out)  # Should be UNSOURCED line
        self.assertIn("amounts 50", out)
        self.assertIn("total_cap 50", out)
        self.assertEqual(err, "")

    def test_the_30_50_range_cap_50_passes(self):
        """quote "the 30-50 range, cap 50": amounts [50], total_cap 50 -> PASS, no unsourced."""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "the 30-50 range, cap 50"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "within_budget",
                    "amounts": [50],
                    "total_cap": 50
                }
            ]
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 0)  # should pass
        self.assertEqual(out.strip(), "C1: PASS within_budget")
        self.assertEqual(err, "")

    def test_rate_1_23457_unsourced_for_1_234567(self):
        """quote "rate 1.23457": amounts [1.234567], total_cap 2 is unsourced for 1.234567"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "rate 1.23457"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "within_budget",
                    "amounts": [1.234567],
                    "total_cap": 2
                }
            ]
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # fails due to unsourced
        self.assertIn("amounts 1.23457", out)  # fmt_num formats 1.234567 as 1.23457
        self.assertEqual(err, "")

    def test_doors_9_45pm_close_11_30pm_unsourced_start(self):
        """quote "doors 9:45pm, close 11:30pm": fits_window start "09:45" -> "start 09:45" unsourced"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "doors 9:45pm, close 11:30pm"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:45",
                    "end": "11:30",
                    "segments_min": [60]  # 60 must be in the quote for the next test
                }
            ]
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # fails due to unsourced
        self.assertIn("start 09:45", out)
        self.assertEqual(err, "")

    def test_doors_9_45pm_60_minutes_close_11_30pm_passes(self):
        """quote "doors 9:45pm, 60 minutes, close 11:30pm": start "21:45", segments [60], end "23:30" -> no unsourced values"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "doors 9:45pm, 60 minutes, close 11:30pm"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "21:45",  # 9:45pm + 60 minutes = 21:45 + 60min = 22:45? Wait, let me recalculate
                    # 9:45pm = 21:45, plus 60 minutes = 22:45, but end is 23:30 (11:30pm)
                    # Actually the example says: start "21:45", segments [60], end "23:30"
                    # So 21:45 + 60min = 22:45, which is <= 23:30, so that works
                    "end": "23:30",
                    "segments_min": [60]
                }
            ]
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 0)  # should pass
        self.assertIn("C1: PASS fits_window", out)
        self.assertEqual(err, "")

    def test_at_09_45_30_unsourced_start(self):
        """quote "at 09:45:30": start "09:45" unsourced"""
        record = {
            "version": 1,
            "objective": {"text": "Test", "quote": "at 09:45:30"},
            "items": [],
            "checks": [
                {
                    "id": "C1",
                    "kind": "fits_window",
                    "start": "09:45",
                    "end": "10:00",
                    "segments_min": [15]  # arbitrary, just need to make the check valid
                }
            ]
        }
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        code, out, err = run_record(["check", "--record", self.record_path])
        self.assertEqual(code, 1)  # fails due to unsourced
        self.assertIn("start 09:45", out)
        self.assertEqual(err, "")

    def _check(self, quote, check):
        record = {"version": 1, "objective": {"text": "Test", "quote": quote}, "items": [], "checks": [check]}
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        return run_record(["check", "--record", self.record_path])

    def test_zero_seconds_time_is_sourced(self):
        code, out, err = self._check("doors 09:45:00, done 10:45, 60 minutes",
                                     {"id": "C1", "kind": "fits_window", "start": "09:45", "segments_min": [60], "end": "10:45"})
        self.assertEqual((code, out.strip(), err), (0, "C1: PASS fits_window", ""))

    def test_am_times_are_sourced(self):
        code, out, err = self._check("9:45am to 11:15am, 90 minutes",
                                     {"id": "C1", "kind": "fits_window", "start": "09:45", "segments_min": [90], "end": "11:15"})
        self.assertEqual((code, out.strip(), err), (0, "C1: PASS fits_window", ""))

    def test_midnight_am_sources_00_00(self):
        code, out, err = self._check("12:00am until 1:00am, 60 minutes",
                                     {"id": "C1", "kind": "fits_window", "start": "00:00", "segments_min": [60], "end": "01:00"})
        self.assertEqual((code, out.strip(), err), (0, "C1: PASS fits_window", ""))

    def test_digits_inside_a_time_do_not_source_a_number(self):
        code, out, err = self._check("doors 9:45",
                                     {"id": "C1", "kind": "within_budget", "amounts": [45], "total_cap": 45})
        self.assertEqual(code, 1)
        self.assertIn("amounts 45", out)

if __name__ == "__main__":
    unittest.main()