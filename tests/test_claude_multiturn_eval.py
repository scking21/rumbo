"""The multi-turn eval runner, driven by a stand-in claude CLI that spends nothing.

The stand-in answers each turn with a fixed reply and keeps a transcript where
the real CLI does, and answers the judge with PASS when the text it is shown
holds that reply. HOME points at a temporary folder, so nothing touches the
real ~/.claude.
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "scripts", "claude_multiturn_eval.py")
STAND_IN = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, re, sys
    args = sys.argv[1:]
    if "--tools" in args:
        prompt = sys.stdin.read()
        verdict = "PASS" if "[reply in turn" in prompt and "16:50" in prompt else "FAIL"
        print(json.dumps({"type": "result", "is_error": False, "result": verdict}))
        sys.exit()
    turn = args[args.index("-p") + 1]
    session = args[args.index("--resume") + 1] if "--resume" in args else "stand-in-session"
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(os.getcwd()))
    folder = os.path.expanduser("~/.claude/projects/" + slug)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, session + ".jsonl"), "a") as handle:
        handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": turn}}) + "\\n")
        handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "That agenda ends at 16:50, past your 16:15 stop."}]}}) + "\\n")
    print(json.dumps({"type": "result", "is_error": False, "result": "ok", "session_id": session,
                      "total_cost_usd": 0.01}))
''')
GRADER = textwrap.dedent('''\
    ---
    type: llm
    focus: trace
    weight: 1
    ---
    PASS only if the assistant says when the agenda ends.
''')


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.bin = os.path.join(base, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "claude"), "w") as handle:
            handle.write(STAND_IN)
        os.chmod(os.path.join(self.bin, "claude"), 0o755)
        self.case = os.path.join(base, "cases", "agenda")
        os.makedirs(os.path.join(self.case, "graders"))
        with open(os.path.join(self.case, "prompt.md"), "w") as handle:
            handle.write("---\nmax_turns: 5\n---\nPlan the afternoon.\n\nWhen does it end?\n")
        with open(os.path.join(self.case, "graders", "says-the-end.md"), "w") as handle:
            handle.write(GRADER)
        self.env = dict(os.environ, HOME=os.path.join(base, "home"), PATH=self.bin + os.pathsep + os.environ["PATH"])
        self.out = os.path.join(base, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, *args):
        return subprocess.run([sys.executable, RUNNER] + list(args), capture_output=True, text=True,
                              env=self.env, cwd=self.tmp.name, timeout=60)

    def summary(self):
        with open(os.path.join(self.out, "summary.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_a_run_is_graded_and_a_new_grader_is_added_by_regrading(self):
        done = self.runner("--allow-shell", "--grade", "--out", self.out, self.case)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("agenda run 1: 2 turns, $0.010, 0 Stop blocks", done.stdout)
        self.assertEqual(self.summary()["sessions"][0]["graders"], {"says-the-end": "PASS"})
        with open(os.path.join(self.case, "graders", "names-the-stop.md"), "w") as handle:
            handle.write(GRADER.replace("says when the agenda ends", "names the 16:15 stop"))
        done = self.runner("--regrade", self.out)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("graders 2/2", done.stdout)
        self.assertEqual(self.summary()["sessions"][0]["graders"],
                         {"names-the-stop": "PASS", "says-the-end": "PASS"})

    def test_regrading_leaves_incomplete_sessions_and_missing_cases_as_they_were(self):
        self.assertEqual(self.runner("--allow-shell", "--out", self.out, self.case).returncode, 0)
        summary = self.summary()
        good = summary["sessions"][0]
        summary["sessions"] = [dict(good, run=2, failure="turn 2: You've hit your limit"),
                               dict(good, run=3, case=os.path.join(self.tmp.name, "gone")), good,
                               dict(good, transcript=None)]
        with open(os.path.join(self.out, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(summary, handle)
        done = self.runner("--regrade", self.out)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("no graders at", done.stderr)
        rows = self.summary()["sessions"]
        self.assertNotIn("graders", rows[0])
        self.assertNotIn("graders", rows[1])
        self.assertEqual(rows[2]["graders"], {"says-the-end": "PASS"})
        # Review of this change: a complete session whose transcript was not saved
        # is graded in a run, so regrading grades it too; its trace grader has no evidence.
        self.assertEqual(rows[3]["graders"], {"says-the-end": "MISSING"})

    def test_regrading_errors_only_asks_the_judge_again_for_those_verdicts(self):
        self.assertEqual(self.runner("--allow-shell", "--grade", "--out", self.out, self.case).returncode, 0)
        with open(os.path.join(self.case, "graders", "names-the-stop.md"), "w") as handle:
            handle.write(GRADER.replace("says when the agenda ends", "names the 16:15 stop"))
        summary = self.summary()
        # As when a usage limit cut the judge off: one verdict is ERROR, one is a
        # verdict to keep, and the grader added since was never asked.
        summary["sessions"][0]["graders"] = {"says-the-end": "ERROR", "names-the-stop": "FAIL"}
        with open(os.path.join(self.out, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(summary, handle)
        votes = os.path.join(self.out, "agenda-1", "judge-votes.json")
        with open(votes, "w", encoding="utf-8") as handle:
            json.dump({"says-the-end": ["ERROR"] * 3, "names-the-stop": ["FAIL"] * 3}, handle)
        done = self.runner("--regrade", self.out, "--errors-only")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.summary()["sessions"][0]["graders"],
                         {"says-the-end": "PASS", "names-the-stop": "FAIL"})
        with open(votes, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"says-the-end": ["PASS"] * 3, "names-the-stop": ["FAIL"] * 3})
        done = self.runner("--allow-shell", "--errors-only", "--out", os.path.join(self.tmp.name, "new"), self.case)
        self.assertEqual(done.returncode, 2)
        self.assertIn("--errors-only goes with --regrade DIR", done.stderr)

    def test_rerun_runs_only_the_incomplete_sessions_again_in_place(self):
        self.assertEqual(self.runner("--allow-shell", "--grade", "--runs", "2", "--out", self.out, self.case).returncode, 0)
        summary = self.summary()
        # As when a usage limit cut the second session short.
        summary["sessions"][1] = dict(summary["sessions"][1], failure="turn 2: You've hit your weekly limit",
                                      turns=1, graders=None)
        with open(os.path.join(self.out, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(summary, handle)
        leftover = os.path.join(self.out, "agenda-2", "project", "half-written.md")
        with open(leftover, "w", encoding="utf-8") as handle:
            handle.write("partial")
        kept = summary["sessions"][0]
        done = self.runner("--rerun", self.out, "--allow-shell", "--grade")
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = self.summary()["sessions"]
        self.assertEqual(rows[0], kept)
        self.assertIsNone(rows[1]["failure"])
        self.assertEqual((rows[1]["turns"], rows[1]["graders"]), (2, {"says-the-end": "PASS"}))
        self.assertFalse(os.path.exists(leftover), "a rerun starts in a fresh project")
        for args in (["--rerun", self.out], ["--rerun", self.out, "--allow-shell", self.case]):
            done = self.runner(*args)
            self.assertEqual(done.returncode, 2)

    def test_regrade_takes_only_the_run_directory(self):
        for args in (["--regrade", self.out, self.case], ["--regrade", self.out, "--out", self.out]):
            done = self.runner(*args)
            self.assertEqual(done.returncode, 2)
            self.assertIn("--regrade takes the run's directory only", done.stderr)
        done = self.runner("--allow-shell", self.case)
        self.assertEqual(done.returncode, 2)
        self.assertIn("give the case directories and --out, --regrade DIR or --rerun DIR", done.stderr)


if __name__ == "__main__":
    unittest.main()
