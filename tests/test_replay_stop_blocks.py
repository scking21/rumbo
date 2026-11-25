"""scripts/replay_stop_blocks.py replays saved Stop blocks against a reader, without running sessions."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "replay_stop_blocks.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import replay_stop_blocks as replay  # noqa: E402

AGENDA = ("C1: UNSOURCED fits_window draft agenda: start 09:00, end 12:30, segments_min 75, segments_min 20, "
          "segments_min 75 not in the user's quoted words")
IN_FULL = ("Every time here is my assumption.\n| 9:00–10:15 | Session 1 |\n| 10:15–10:35 | Break |\n"
           "| 10:35–11:50 | Session 2 |\nWe close at 12:30.")
STATUS = "Here are the speakers.\n\nStill my assumption: the 9:00 to 12:30 times."


def entry(kind, text=None):
    if kind == "prompt":
        return {"type": "user", "message": {"role": "user", "content": text}}
    if kind == "reply":
        return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    return {"type": "attachment", "attachment": {"type": "hook_blocking_error", "hookEvent": "Stop"}}


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = os.path.join(self.tmp.name, "run")
        os.makedirs(self.run)
        transcript = os.path.join(self.run, "t.jsonl")
        with open(transcript, "w", encoding="utf-8") as handle:
            for item in (entry("prompt", "Plan a workshop morning."), entry("reply", IN_FULL),
                         entry("prompt", "Which speaker?"), entry("reply", STATUS), entry("block"),
                         entry("reply", "Still open: the agenda times.")):
                handle.write(json.dumps(item) + "\n")
        with open(os.path.join(self.run, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"sessions": [{"case": "rumbo/evals/01-workshop-full", "run": 1, "transcript": transcript,
                                     "blocks": [{"turn": 2, "reason": AGENDA + "\nBefore finishing, ..."}]}]}, handle)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_status_line_passes_only_with_what_was_told(self):
        reader = replay.load_reader(os.path.join(ROOT, "rumbo", "scripts"))
        self.assertEqual(replay.replay(reader, [self.run]), (1, 1, 0, [], 0))
        self.assertEqual(replay.replay(reader, [self.run], told=True),
                         (1, 1, 1, ["run 01-workshop-full run 1 turn 2"], 0))
        done = subprocess.run([sys.executable, SCRIPT, "--told", self.run], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("with only assumed values: 1 rebuilt, 0 not; read as stated: 1", done.stdout)

    def test_skill_text_and_hook_feedback_are_not_prompts(self):
        # Review: an injected message after an intermediate reply was taken for
        # a prompt, so that reply counted as told although no Stop read it.
        transcript = os.path.join(self.run, "t.jsonl")
        with open(transcript, "w", encoding="utf-8") as handle:
            for item in (entry("prompt", "Plan a workshop morning."), entry("reply", IN_FULL),
                         dict(entry("prompt", "Base directory for this skill: /x"), isMeta=True),
                         entry("prompt", "Stop hook feedback: ..."),
                         {"type": "user", "toolUseResult": {}, "message": {"role": "user", "content": [
                             {"type": "tool_result", "content": "ok"}]}},
                         entry("reply", "Working on it."), entry("prompt", "Which speaker?"),
                         entry("reply", STATUS), entry("block")):
                handle.write(json.dumps(item) + "\n")
        # The last stop is the session's end, after the block.
        self.assertEqual(replay.stops(transcript), [(False, "Working on it."), (True, STATUS), (False, STATUS)])
        reader = replay.load_reader(os.path.join(ROOT, "rumbo", "scripts"))
        self.assertEqual(replay.replay(reader, [self.run], told=True), (1, 1, 0, [], 0))

    def test_each_stop_keeps_the_last_reply_and_blocks_stay_in_order(self):
        stops = replay.stops(os.path.join(self.run, "t.jsonl"))
        self.assertEqual(stops, [(False, IN_FULL), (True, STATUS), (False, "Still open: the agenda times.")])

    def test_a_block_line_is_rebuilt_with_its_named_values_unsourced(self):
        reader = replay.load_reader(os.path.join(ROOT, "rumbo", "scripts"))
        final_budget = {"id": "C2", "kind": "within_budget", "label": "catering",
                        "amounts": [{"unit": 7, "quantity": 40}, 50, 250], "total_cap": 600, "refs": ["I1"]}
        final_dates = {"id": "C3", "kind": "before", "first": "2026-03-12", "second": "2027-03-20", "refs": []}
        for line, final in ((AGENDA, None),
                            ("C2: UNSOURCED within_budget catering: amounts unit 7, amounts 50 not in the user's "
                             "quoted words", final_budget),
                            ("C3: UNSOURCED before launch: second month-day 10-03 not in the user's quoted words", None),
                            # Review: a year assumed on its own was dropped.
                            ("C3: UNSOURCED before deadline: second year 2027 not in the user's quoted words", final_dates),
                            ("C3: UNSOURCED before deadline: first year 2027 not in the user's quoted words", None)):
            with self.subTest(line=line):
                check_id, record = replay.rebuild(line, reader, final)
                self.assertEqual(reader.validate_record(record), [])
                self.assertTrue(reader.evaluate_check(record["checks"][0])[0])
                named = sorted(label for label, _reading, _value in reader._unsourced(record, record["checks"][0]))
                values = line.split(": ", 2)[2].rsplit(" not in", 1)[0]
                self.assertEqual(named, sorted(v.strip() for v in values.split(",")))
        # Review: with the head count from the final record, the $280 total states the $7 a head.
        _check_id, record = replay.rebuild("C2: UNSOURCED within_budget catering: amounts unit 7 not in the user's "
                                           "quoted words", reader, final_budget)
        self.assertEqual(record["checks"][0]["amounts"][0], {"unit": 7, "quantity": 40})
        self.assertEqual(reader.stated_checks(record, "My catering estimate is $280."), {"C2"})
        # Without the other factor a price per unit is not rebuilt, rather than judged as a different total.
        self.assertIsNone(replay.rebuild("C2: UNSOURCED within_budget catering: amounts unit 7 not in the user's "
                                         "quoted words", reader))
        self.assertIsNone(replay.rebuild("C4: FAIL fits_window agenda: 09:00 + 240 min ends 13:00, 30 min after 12:30",
                                         reader))

if __name__ == "__main__":
    unittest.main()
