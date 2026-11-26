"""scripts/hold_outcomes.py reports what an agent did after a held write, from saved transcripts."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "hold_outcomes.py")
NO_RECORD = "rumbo: this session looks like planning work and there is no decision record. This write was held once."
UNDECIDED = "rumbo: the user has not decided the items marked NOT DECIDED.\nNOT DECIDED I2 [uncertain]: Venue"


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def write(tool_id, path, content):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": "Write", "input": {"file_path": path, "content": content}}]}}


def result(tool_id, text, error=True):
    return {"type": "user", "toolUseResult": "x", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "is_error": error, "content": text}]}}


class HoldOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "u-haiku")

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, name, entries):
        folder = os.path.join(self.run_dir, name)
        os.makedirs(folder)
        with open(os.path.join(folder, "transcript.jsonl"), "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry) + "\n")

    def test_each_held_write_is_reported_with_what_came_next(self):
        self.session("11-a-1", [
            prompt("Plan the offsite."), prompt("Write plan.md."),
            write("t1", "/p/plan.md", "Venue: community center"),
            result("t1", "PreToolUse:Write hook error: " + NO_RECORD),
            write("t2", "/p/plan.md", "Venue: community center (proposed)"),
            result("t2", "File created", error=False),
            write("t3", "/p/notes.md", "x"),
            result("t3", "PreToolUse:Write hook error: " + UNDECIDED),
            write("t4", "/p/notes.md", "x"),
            result("t4", "File created", error=False),
        ])
        self.session("01-b-1", [
            prompt("Plan it."),
            write("t1", "/p/plan.md", "draft"),
            result("t1", "PreToolUse:Write hook error: " + UNDECIDED),
            prompt("Next turn."),
            write("t2", "/p/plan.md", "draft"),
            # Another hook's denial is not the plugin's hold.
            result("t2", "PreToolUse:Write hook error: blocked by policy"),
        ])
        done = subprocess.run([sys.executable, SCRIPT, self.run_dir], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertIn("u-haiku 01-b-1 turn 1: plan.md held (undecided), not written again", lines)
        self.assertIn("u-haiku 11-a-1 turn 2: plan.md held (no record), changed", lines)
        self.assertIn("u-haiku 11-a-1 turn 2: notes.md held (undecided), unchanged", lines)
        self.assertEqual(lines[-1], "u-haiku: 3 held writes, 1 changed, 1 unchanged, 1 not written again")

    def test_only_a_write_that_went_through_counts_as_written_again(self):
        # After a no-record hold the agent starts a record, and its next write is held for that record's lines.
        self.session("11-a-2", [
            prompt("Plan the offsite."), prompt("Write plan.md."),
            write("t1", "/p/plan.md", "Venue: community center"),
            result("t1", "PreToolUse:Write hook error: " + NO_RECORD),
            write("t2", "/p/plan.md", "Venue: community center, to confirm"),
            result("t2", "PreToolUse:Write hook error: " + UNDECIDED),
            write("t3", "/p/plan.md", "Venue: community center, to confirm"),
            result("t3", "File created", error=False),
        ])
        self.session("11-a-3", [
            prompt("Write plan.md."),
            write("t1", "/p/plan.md", "a"),
            result("t1", "PreToolUse:Write hook error: " + NO_RECORD),
            write("t2", "/p/plan.md", "b"),
            result("t2", "Error writing file: disk full"),
        ])
        done = subprocess.run([sys.executable, SCRIPT, self.run_dir], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertIn("u-haiku 11-a-2 turn 2: plan.md held (no record), changed", lines)
        self.assertIn("u-haiku 11-a-2 turn 2: plan.md held (undecided), unchanged", lines)
        self.assertIn("u-haiku 11-a-3 turn 1: plan.md held (no record), not written again", lines)
        self.assertEqual(lines[-1], "u-haiku: 3 held writes, 1 changed, 1 unchanged, 1 not written again")

    def test_usage(self):
        done = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 2)
        self.assertIn("usage: python3 scripts/hold_outcomes.py RUN_DIR", done.stderr)
        for flag in ("-h", "--help"):
            done = subprocess.run([sys.executable, SCRIPT, flag], capture_output=True, text=True, timeout=30)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            self.assertIn("usage: python3 scripts/hold_outcomes.py RUN_DIR", done.stdout)

    def test_a_missing_folder_is_reported_without_a_traceback(self):
        missing = os.path.join(self.tmp.name, "nope")
        done = subprocess.run([sys.executable, SCRIPT, self.tmp.name, missing], capture_output=True, text=True,
                              timeout=30)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stderr.strip(), "hold_outcomes.py: not a folder: " + missing)
        self.assertEqual(done.stdout, "")


if __name__ == "__main__":
    unittest.main()
