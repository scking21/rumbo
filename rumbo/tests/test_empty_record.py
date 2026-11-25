"""A record that holds only its objective checks nothing.

In repeated eval runs on 0.3.15, four planning sessions (three on haiku, one
on opus) started a record and never added an item over up to 15 turns, so the
Stop gate had no decision, time or amount to check. Two of them account for
7 of the 8 failed gradings of the launch case on those two models. While a
record is empty, the prompt hook says so and counts planning prompts, and the
Stop gate blocks once per session after two of them, as it does when there is
no record at all.
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

GOAL = "We're launching our community garden app on the first Saturday of October. Can you help me plan the launch?"
BUDGET = "Our budget is $1,200 for everything."
EMPTY = {"version": 1, "objective": {"text": "Plan the app launch", "quote": GOAL}, "items": [], "checks": []}


class EmptyRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.record = os.path.join(self.tmp.name, "project", ".rumbo", "record.json")
        os.makedirs(os.path.dirname(self.record))
        self.state = os.path.join(self.tmp.name, "state")
        self.env = dict(os.environ, RUMBO_STATE_DIR=self.state)
        self.transcript = os.path.join(self.tmp.name, "t.jsonl")
        self.write(EMPTY)
        self.said(GOAL, BUDGET)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, document):
        with open(self.record, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

    def said(self, *messages):
        with open(self.transcript, "w", encoding="utf-8") as handle:
            for text in messages:
                handle.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                         "message": {"role": "user", "content": text}}) + "\n")

    def run_record(self, command, payload):
        proc = subprocess.run([sys.executable, SCRIPT, command, "--record", self.record], input=json.dumps(payload),
                              text=True, capture_output=True, env=self.env, timeout=10)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        return proc.stdout

    def prompt(self, text, session="s1"):
        return self.run_record("show", {"prompt": text, "session_id": session})

    def stop(self, session="s1", chained=False):
        out = self.run_record("stop-gate", {"session_id": session, "transcript_path": self.transcript,
                                            "stop_hook_active": chained, "last_assistant_message": "Here is a plan."})
        return json.loads(out)["reason"] if out.strip() else None

    def test_the_prompt_hook_says_the_record_is_empty(self):
        out = self.prompt(BUDGET)
        self.assertIn("Objective: Plan the app launch\n" + record.EMPTY_NOTE, out)
        document = dict(EMPTY, items=[{"id": "I1", "text": "Budget", "quote": BUDGET, "status": "commitment"}])
        self.write(document)
        self.assertNotIn(record.EMPTY_NOTE, self.prompt(BUDGET))

    def test_the_stop_gate_nudges_once_after_two_planning_prompts(self):
        self.prompt(GOAL)
        self.assertIsNone(self.stop())
        self.prompt("Can we fit 100 flyers?")
        self.assertIsNone(self.stop(), "a prompt that does not look like planning is not counted")
        self.prompt(BUDGET)
        # A stop right after a block was answered is never nudged, and does not use the nudge up.
        self.assertIsNone(self.stop(chained=True))
        self.assertEqual(self.stop(), record.EMPTY_REASON)
        self.assertIsNone(self.stop())
        self.prompt("The insurance quote is $180.")
        self.assertIsNone(self.stop())
        # Another session is counted on its own.
        self.prompt(BUDGET, session="s2")
        self.assertIsNone(self.stop(session="s2"))

    def test_a_record_with_an_item_or_a_check_is_not_nudged(self):
        self.prompt(GOAL)
        self.prompt(BUDGET)
        item = {"id": "I1", "text": "Budget", "quote": BUDGET, "status": "commitment"}
        self.write(dict(EMPTY, items=[item]))
        self.assertIsNone(self.stop())
        check = {"id": "C1", "kind": "within_budget", "amounts": [300], "total_cap": 1200, "refs": []}
        self.write(dict(EMPTY, checks=[check]))
        self.assertIn("C1: UNSOURCED", self.stop())

    def test_other_problems_come_first(self):
        self.prompt(GOAL)
        self.prompt(BUDGET)
        self.said(BUDGET)
        self.assertIn("UNVERIFIED", self.stop())

    def test_without_a_session_id_there_is_no_nudge(self):
        self.prompt(GOAL, session=None)
        self.prompt(BUDGET, session=None)
        self.assertIsNone(self.stop(session=None))


if __name__ == "__main__":
    unittest.main()
