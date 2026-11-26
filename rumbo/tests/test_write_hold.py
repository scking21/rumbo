"""The pre-write hook holds a write once, so the agent reads its lines before writing.

A PreToolUse hook's added context reaches the model with the tool's result,
after the file is written. In the saved eval runs on 0.3.15 and 0.3.18 agents
changed the file again after 11 of the 42 contexts the hook added (haiku after
none of 5 on 0.3.18). In every haiku session of 11-rejected-option on 0.3.15, 0.3.18
and 0.3.20 that wrote the plan before any record existed, the plan listed the
remaining venue as decided. So the hook now denies a write once when it has
lines the session has not been shown, at most three times per session, and
holds the first write of a planning session that has no record, in place of
the Stop gate's one no-record block.
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

SAID = "Two venues: the hotel ballroom at $1,800 or the community center at $900. No, don't use the ballroom."
GOAL = ("I'm planning our team offsite on June 4 for 20 people with a $3,000 budget. There are two venue "
        "options: the hotel ballroom at $1,800 or the community center at $900. Can you help me plan it?")
WRITE_PLAN = "Please write the plan as plan.md in the current folder: what's decided and what's still open."


def item(n, status="exploring"):
    return {"id": "I%d" % n, "text": "Option %d" % n, "quote": SAID, "status": status}


class WriteHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "project")
        self.record = os.path.join(self.project, ".rumbo", "record.json")
        os.makedirs(os.path.dirname(self.record))
        self.env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(self.tmp.name, "state"))
        self.transcript = os.path.join(self.tmp.name, "t.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            for text in (GOAL, "No, don't use the hotel ballroom. It's too formal for us.", WRITE_PLAN):
                handle.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                         "message": {"role": "user", "content": text}}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, items):
        with open(self.record, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "objective": {"text": "Offsite", "quote": SAID}, "items": items,
                       "checks": []}, handle)

    def run_record(self, command, payload, env=None):
        proc = subprocess.run([sys.executable, SCRIPT, command, "--record", self.record], input=json.dumps(payload),
                              text=True, capture_output=True, env=env or self.env, timeout=10)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None

    def pre_write(self, session="s1", target="plan.md", env=None):
        return self.run_record("pre-write", {"session_id": session, "cwd": self.project, "tool_name": "Write",
                                             "tool_input": {"file_path": os.path.join(self.project, target)}}, env)

    def prompt(self, text, session="s1"):
        subprocess.run([sys.executable, SCRIPT, "show", "--record", self.record],
                       input=json.dumps({"prompt": text, "session_id": session}), text=True, capture_output=True,
                       env=self.env, timeout=10, check=True)

    def stop(self, session="s1"):
        proc = subprocess.run([sys.executable, SCRIPT, "stop-gate", "--record", self.record],
                              input=json.dumps({"session_id": session, "transcript_path": self.transcript,
                                                "last_assistant_message": "Here is the plan."}),
                              text=True, capture_output=True, env=self.env, timeout=10)
        return json.loads(proc.stdout)["reason"] if proc.stdout.strip() else None

    # ------------------------------------------------ lines from the record

    def test_a_write_is_held_once_per_new_line_and_three_times_a_session(self):
        self.write([item(1)])
        held = self.pre_write()
        self.assertEqual(held["permissionDecision"], "deny")
        self.assertIn("NOT DECIDED I1 [exploring]: Option 1", held["permissionDecisionReason"])
        self.assertIsNone(self.pre_write(), "the same lines do not hold a write again")
        # Each new undecided item holds the next write, with every line shown.
        for n in (2, 3):
            self.write([item(k) for k in range(1, n + 1)])
            held = self.pre_write()
            self.assertEqual(held["permissionDecision"], "deny")
            self.assertIn("NOT DECIDED I1 ", held["permissionDecisionReason"])
            self.assertIn("NOT DECIDED I%d " % n, held["permissionDecisionReason"])
        # After three holds, new lines are added as context and the write goes on.
        self.write([item(k) for k in range(1, 5)])
        context = self.pre_write()
        self.assertNotIn("permissionDecision", context)
        self.assertIn("NOT DECIDED I4 ", context["additionalContext"])
        self.assertNotIn(record.PRE_WRITE_AGAIN, context["additionalContext"])
        # Another session has its own holds.
        self.assertEqual(self.pre_write(session="s2")["permissionDecision"], "deny")

    def test_lines_that_come_back_hold_again_and_fewer_lines_do_not(self):
        self.write([item(1), item(2)])
        self.assertEqual(self.pre_write()["permissionDecision"], "deny")
        self.write([item(1), item(2, "commitment")])
        self.assertIsNone(self.pre_write())
        self.write([item(1, "commitment"), item(2, "commitment")])
        self.assertIsNone(self.pre_write())
        self.write([item(1)])
        self.assertEqual(self.pre_write()["permissionDecision"], "deny")

    def test_a_write_is_never_held_when_the_session_marker_cannot_be_kept(self):
        # Without its marker every write would be held again: the lines go in as context instead.
        blocked = os.path.join(self.tmp.name, "not-a-directory")
        with open(blocked, "w") as handle:
            handle.write("")
        env = dict(self.env, RUMBO_STATE_DIR=blocked)
        self.write([item(1)])
        for _ in range(2):
            output = self.pre_write(env=env)
            self.assertNotIn("permissionDecision", output)
            self.assertIn("NOT DECIDED I1 ", output["additionalContext"])

    # ------------------------------------------------------- no record yet

    def test_the_first_write_of_a_planning_session_without_a_record_is_held_once(self):
        self.prompt(GOAL)
        self.prompt("No, don't use the hotel ballroom. It's too formal for us.")
        self.assertIsNone(self.pre_write(), "one planning prompt may be a one-off request")
        self.prompt(WRITE_PLAN)
        self.assertIsNone(self.pre_write(target=".rumbo/record.json"), "writing the record itself is not held")
        held = self.pre_write()
        self.assertEqual(held, {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                "permissionDecisionReason": record.PRE_WRITE_NO_RECORD})
        self.assertIn("a no to one option rules it out; it does not choose the others", record.PRE_WRITE_NO_RECORD)
        self.assertIsNone(self.pre_write(), "held once")
        # The hold is the session's one no-record enforcement: the Stop gate does not block for it again.
        self.assertIsNone(self.stop())
        # Another session is counted on its own.
        self.prompt(GOAL, session="s2")
        self.prompt(WRITE_PLAN, session="s2")
        self.assertEqual(self.pre_write(session="s2")["permissionDecision"], "deny")

    def test_a_session_the_stop_gate_already_blocked_is_not_held(self):
        self.prompt(GOAL)
        self.prompt(WRITE_PLAN)
        self.assertIn("there is no decision record", self.stop())
        self.assertIsNone(self.pre_write())

    def test_without_a_session_a_write_is_never_held_for_a_missing_record(self):
        self.prompt(GOAL, session=None)
        self.prompt(WRITE_PLAN, session=None)
        self.assertIsNone(self.pre_write(session=None))


if __name__ == "__main__":
    unittest.main()
