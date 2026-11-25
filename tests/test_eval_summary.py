"""scripts/eval_summary.py tabulates eval runs without running anything."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "eval_summary.py")


def session(case, run, graders=None, blocks=0, naming=(), cost=0.5, failure=None):
    return {"case": "rumbo/evals/" + case, "run": run, "turns": 1, "cost": cost, "failure": failure,
            "blocks": [{"turn": 1, "reason": "x"}] * blocks, "naming_ids": list(naming), "graders": graders}


class EvalSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def arm(self, name, sessions):
        folder = os.path.join(self.tmp.name, name)
        os.makedirs(folder)
        with open(os.path.join(folder, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"plugin": "p", "model": "m", "sessions": sessions}, handle)
        return folder

    def run_summary(self, *args):
        return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, timeout=30)

    def test_counts_verdicts_blocks_and_cost_and_pools_a_label(self):
        first = self.arm("a", [session("01-x", 1, {"g": "PASS", "h": "FAIL"}, blocks=2, naming=[3]),
                               session("01-x", 2, {"g": "ERROR", "h": "PASS"}),
                               session("01-x", 3, None, failure="turn 2: limit", cost=0)])
        later = self.arm("b", [session("02-y", 1, {"k": "PASS", "f": "SKIPPED"}, cost=0.25)])
        other = self.arm("c", [session("01-x", 1, {"g": "FAIL"})])
        done = self.run_summary("one=" + first, "one=" + later, "two=" + other)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertEqual(lines[0], "| Case | Grader | one | two |")
        self.assertIn("| 01-x | g | 1/1 | 0/1 |", lines)
        self.assertIn("| 01-x | h | 1/2 | - |", lines)
        self.assertIn("| 02-y | k | 1/1 | - |", lines)
        self.assertFalse(any("| f |" in line for line in lines), "SKIPPED is not a verdict")
        self.assertIn("| 01-x | complete sessions | 2/3 | 1/1 |", lines)
        self.assertIn("| 01-x | Stop blocks | 2 | 0 |", lines)
        self.assertIn("| 01-x | sessions naming a record id | 1 | 0 |", lines)
        self.assertIn("one total cost: $1.25", lines)
        self.assertIn("INCOMPLETE one 01-x run 3: turn 2: limit", lines)

    def test_usage(self):
        for args in ([], ["no-equals-sign"], ["=dir"]):
            done = self.run_summary(*args)
            self.assertEqual(done.returncode, 2)
            self.assertIn("usage: python3 scripts/eval_summary.py LABEL=DIR", done.stderr)


if __name__ == "__main__":
    unittest.main()
