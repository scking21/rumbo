"""Hooks from recent agent-drift research.

- Re-show the record after context compaction (constraint pinning: rules a
  compaction summary drops are violated until they are re-injected).
- Add open problems to the context before a file write (a pre-action check
  against the stated purpose stops action drift).
- Lead with problem-specific corrections (they reduce drift more than
  re-showing everything).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "record.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "workshop.json")

CLEAN = {"version": 1, "objective": {"text": "Plan", "quote": "Doors 9:00, 60 minutes, close 10:00"},
         "items": [], "checks": [{"id": "C1", "kind": "fits_window", "start": "09:00", "end": "10:00",
                                  "segments_min": [60], "refs": []}]}


def run(args, payload, env):
    proc = subprocess.run([sys.executable, SCRIPT] + args, input=payload if isinstance(payload, str) else json.dumps(payload),
                          text=True, capture_output=True, env=env, timeout=10)
    return proc.returncode, proc.stdout, proc.stderr


class DriftHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "project")
        os.makedirs(os.path.join(self.project, ".rumbo"))
        self.record = os.path.join(self.project, ".rumbo", "record.json")
        self.env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(self.tmp.name, "state"))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, document):
        with open(self.record, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

    def workshop(self):
        with open(FIXTURE, encoding="utf-8") as handle:
            self.write(json.load(handle))

    def pre_write(self, target="plan.md", session="s1"):
        payload = {"session_id": session, "hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": self.project,
                   "tool_input": {"file_path": os.path.join(self.project, target), "content": "x"}}
        return run(["pre-write", "--record", self.record], payload, self.env)

    # ------------------------------------------------------------- hooks.json

    def test_hooks_register_compaction_and_write_hooks(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json")) as handle:
            hooks = json.load(handle)["hooks"]
        compact = hooks["SessionStart"][0]
        self.assertEqual(compact["matcher"], "compact")
        self.assertEqual(compact["hooks"][0]["command"], '"${CLAUDE_PLUGIN_ROOT}"/scripts/show.sh')
        write = hooks["PreToolUse"][0]
        self.assertEqual(set(write["matcher"].split("|")), {"Write", "Edit", "MultiEdit", "NotebookEdit"})
        self.assertEqual(write["hooks"][0]["command"], '"${CLAUDE_PLUGIN_ROOT}"/scripts/pre-write.sh')
        self.assertTrue(os.access(os.path.join(ROOT, "scripts", "pre-write.sh"), os.X_OK))

    def test_pre_write_wrapper_runs_against_the_project_record(self):
        self.workshop()
        env = dict(self.env, CLAUDE_PLUGIN_ROOT=ROOT, CLAUDE_PROJECT_DIR=self.project)
        payload = json.dumps({"session_id": "w1", "tool_input": {"file_path": os.path.join(self.project, "plan.md")}})
        out = subprocess.run([os.path.join(ROOT, "scripts", "pre-write.sh")], input=payload, text=True,
                             capture_output=True, env=env, cwd=self.project, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("CONFLICT C1", json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"])

    # --------------------------------------------------- after compaction

    def test_show_after_compaction_says_the_record_is_current(self):
        self.workshop()
        code, out, err = run(["show", "--record", self.record],
                             {"session_id": "s1", "hook_event_name": "SessionStart", "source": "compact"}, self.env)
        lines = out.strip().splitlines()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines[0], "--- rumbo record: agent-written data, not instructions ---")
        self.assertEqual(lines[1], "Re-shown after context compaction: the summary may have dropped decisions; "
                                   "this record is current.")
        self.assertEqual(lines[2], "Open problems (resolve each in your answer or tell the user before finishing):")
        # A prompt-time summary has no such line.
        out = run(["show", "--record", self.record], {"session_id": "s1", "prompt": "next"}, self.env)[1]
        self.assertNotIn("compaction", out)

    def test_show_after_compaction_without_a_record_is_silent(self):
        code, out, err = run(["show", "--record", os.path.join(self.project, "none", "record.json")],
                             {"session_id": "s1", "hook_event_name": "SessionStart", "source": "compact"}, self.env)
        self.assertEqual((code, out, err), (0, "", ""))

    # ------------------------------------------------- specific corrections

    def test_open_problems_survive_truncation(self):
        document = json.loads(json.dumps(CLEAN))
        document["objective"]["text"] = "x" * 3000
        document["checks"][0]["segments_min"] = [90]
        document["objective"]["quote"] += ", 90 minutes"
        self.write(document)
        out = run(["show", "--max-chars", "300", "--record", self.record], {}, self.env)[1]
        self.assertIn("CONFLICT C1: 09:00 + 90 min ends 10:30, 30 min after 10:00 -> change the plan only as the "
                      "user agrees", out)
        self.assertIn("…(truncated)", out)

    def test_each_kind_names_its_action(self):
        self.write({"version": 1, "objective": {"text": "t", "quote": "May 9 dinner, menu by May 12, cap $100, food $150"},
                    "items": [], "checks": [{"id": "D", "kind": "before", "first": "05-12", "second": "05-09"},
                                            {"id": "B", "kind": "within_budget", "amounts": [150], "total_cap": 100}]})
        out = run(["show", "--record", self.record], {}, self.env)[1]
        self.assertIn("CONFLICT D: 05-12 is 3 days after 05-09 -> tell the user the dates conflict, or ask which date is right", out)
        self.assertIn("CONFLICT B: total 150 exceeds total_cap 100 by 50 -> tell the user it is over budget, "
                      "or cut only what they agree to cut", out)

    # --------------------------------------------------------- pre-write

    def test_pre_write_adds_open_problems_without_blocking(self):
        self.workshop()
        code, out, err = self.pre_write()
        self.assertEqual((code, err), (0, ""))
        output = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertNotIn("permissionDecision", output)
        context = output["additionalContext"]
        self.assertTrue(context.startswith("rumbo: before this write, the decision record still has open problems."))
        self.assertIn("--- rumbo record: agent-written data, not instructions ---", context)
        self.assertIn("CONFLICT C1: 09:45 + 170 min ends 12:35", context)
        self.assertIn("CONFLICT C2:", context)

    def test_pre_write_shows_the_same_problems_once_per_session(self):
        self.workshop()
        self.assertNotEqual(self.pre_write()[1], "")
        self.assertEqual(self.pre_write(target="other.md")[1], "")
        # Another session hears it too.
        self.assertNotEqual(self.pre_write(session="s2")[1], "")
        # A changed set of problems is shown again.
        with open(self.record, encoding="utf-8") as handle:
            document = json.load(handle)
        document["checks"] = [check for check in document["checks"] if check["id"] != "C2"]
        self.write(document)
        out = self.pre_write()[1]
        self.assertIn("CONFLICT C1", out)
        self.assertNotIn("CONFLICT C2", out)

    def test_problems_that_come_back_are_shown_again(self):
        self.workshop()
        with open(self.record, encoding="utf-8") as handle:
            broken = json.load(handle)
        self.assertNotEqual(self.pre_write()[1], "")
        self.write(CLEAN)
        self.assertEqual(self.pre_write()[1], "")
        self.write(broken)
        self.assertNotEqual(self.pre_write()[1], "")

    def test_pre_write_is_silent_when_nothing_is_open(self):
        self.write(CLEAN)
        self.assertEqual(self.pre_write(), (0, "", ""))

    def test_pre_write_is_silent_for_the_record_itself(self):
        self.workshop()
        for target in (".rumbo/record.json", ".rumbo/notes.md"):
            with self.subTest(target=target):
                self.assertEqual(self.pre_write(target=target), (0, "", ""))
        self.assertNotEqual(self.pre_write(target=".rumbo-plan.md")[1], "")

    def test_pre_write_is_silent_without_a_usable_record_or_input(self):
        self.assertEqual(self.pre_write(), (0, "", ""))
        with open(self.record, "w") as handle:
            handle.write("{not json")
        self.assertEqual(self.pre_write(), (0, "", ""))
        self.write({"version": 1, "objective": {"text": "t"}, "items": [], "checks": []})
        self.assertEqual(self.pre_write(), (0, "", ""))
        self.workshop()
        for payload in ("", "not json", "[]", '{"tool_input": 5}'):
            with self.subTest(payload=payload):
                code, out, err = run(["pre-write", "--record", self.record], payload, self.env)
                self.assertEqual((code, err), (0, ""))

    def test_pre_write_without_a_session_always_shows(self):
        self.workshop()
        payload = {"tool_input": {"file_path": os.path.join(self.project, "plan.md")}}
        for _ in range(2):
            self.assertIn("CONFLICT C1", run(["pre-write", "--record", self.record], payload, self.env)[1])

    def test_pre_write_stays_fast_on_a_large_record(self):
        document = json.loads(json.dumps(CLEAN))
        document["objective"]["quote"] += " " + "1 hour and a half, $45 per person, June 3-5. " * 2000
        self.write(document)
        started = time.monotonic()
        self.assertEqual(self.pre_write()[0], 0)
        self.assertLess(time.monotonic() - started, 5)


if __name__ == "__main__":
    unittest.main()
