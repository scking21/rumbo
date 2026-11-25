"""The no-record nudge asks the agent to keep dates without a year when the user gave none.

A one-turn request starts no record, so the commitments skill and its rule
against adding a year are never read. In repeated eval runs on 0.3.15, every
haiku and opus reply to "Our fundraiser dinner is on May 9 ..." put the dates
in 2027, while no sonnet reply did. The prompt-time nudge is the only text the
plugin adds to such a session.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "record.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import record  # noqa: E402


class NudgeYearTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(self.tmp.name, "state"))
        self.record = os.path.join(self.tmp.name, ".rumbo", "record.json")

    def tearDown(self):
        self.tmp.cleanup()

    def show(self, prompt, session="s1"):
        proc = subprocess.run([sys.executable, SCRIPT, "show", "--record", self.record],
                              input=json.dumps({"prompt": prompt, "session_id": session}),
                              text=True, capture_output=True, env=self.env, timeout=10)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        return proc.stdout

    def test_dates_without_a_year_get_the_line(self):
        for n, prompt in enumerate(("Our fundraiser dinner is on May 9. The venue needs the deposit by April 25.",
                                    "The printer deadline is the 20th of March.",
                                    "Kickoff is 3 June, budget $400.")):
            with self.subTest(prompt=prompt):
                out = self.show(prompt, session="s%d" % n)
                self.assertTrue(out.startswith("rumbo: no decision record yet."), out)
                self.assertTrue(out.rstrip("\n").endswith(record.NUDGE_NO_YEAR), out)

    def test_no_line_with_a_year_without_a_date_or_without_the_nudge(self):
        for n, prompt in enumerate(("Dinner on May 9, 2027; deposit by April 25.", "Plan the 2026 offsite on June 4.",
                                    "Our budget is $600.", "may 3 people join the planning call?")):
            with self.subTest(prompt=prompt):
                out = self.show(prompt, session="t%d" % n)
                self.assertTrue(out.startswith("rumbo: no decision record yet."), out)
                self.assertNotIn(record.NUDGE_NO_YEAR, out)
        # Once the nudge has been shown in a session, the line is not shown again either.
        self.show("Planning a dinner.", session="u")
        self.assertEqual(self.show("It is on May 9.", session="u"), "")


if __name__ == "__main__":
    unittest.main()
