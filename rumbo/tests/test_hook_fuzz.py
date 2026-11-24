"""Hooks must never crash, whatever record, hook input or reply they are given.

A hook that raises shows the user a traceback and, for the Stop gate, lets the
turn end unchecked. These records and inputs are random but seeded, so a
failure reproduces: each is malformed in a different way (wrong types, missing
fields, unknown kinds, bad ids, NaN and huge numbers, replaces cycles, odd
replies), and every command must still return through its own diagnostics.
"""
import contextlib
import io
import json
import os
import random
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import record  # noqa: E402

QUOTE = "Budget is $600 and close 12:30."
SCALARS = [None, True, False, 0, -1, 1.5, 1e308, -1e308, 10 ** 30, "", "x", "09:45", "12:30", "24:00", "03-20",
           "2026-02-29", "02-29", "C1", "I1", "$600", "−", [], {}, ["C1"], ["I1"], {"unit": 5, "quantity": 2},
           {"label": "a", "amount": 3}, float("nan"), float("inf")]
REPLIES = [None, "", 42, "Ends 12:35, after the 12:30 close.", "## Budget (my estimate)\n| x | $350 |", "?" * 100,
           "March 20, 2026 is after March 12, 2026.", "$0 budget, $350 over", "\x00 weird", "x" * 30000]
COMMANDS = (("validate", record.cmd_validate), ("check", record.cmd_check), ("show", record.cmd_show),
            ("pre-write", record.cmd_pre_write), ("stop-gate", record.cmd_stop_gate))


class Generator:
    def __init__(self, seed):
        self.random = random.Random(seed)

    def value(self):
        r = self.random
        return r.choice(SCALARS) if r.random() < 0.8 else [r.choice(SCALARS) for _ in range(r.randint(0, 3))]

    def item(self, i):
        r = self.random
        item = {"id": r.choice(["I%d" % i, "I%d" % (i % 2), 5, None]), "text": r.choice(["t", "", None, 3]),
                "quote": r.choice([QUOTE, "", None, "no", "We start 9:45 on March 20, 2026."]),
                "status": r.choice(record.STATUSES + ["nope", None])}
        for key in ("replaces", "scope", "ref"):
            if r.random() < 0.3:
                item[key] = self.value()
        return item

    def check(self, i):
        r = self.random
        kind = r.choice(["fits_window", "before", "within_budget", "bogus", None])
        check = {"id": r.choice(["C%d" % i, "C%d" % (i % 2), ["C1"], None, 7]), "kind": kind}
        fields = {"fits_window": ["start", "end", "segments_min", "end_next_day"], "before": ["first", "second"],
                  "within_budget": ["amounts", "total_cap", "item_cap"]}.get(kind, [])
        choices = {
            "segments_min": [[75, 20, 75], [], [0], [-5], ["x"], [10 ** 6], [1.5]],
            "amounts": [[200, 350], [{"unit": 45, "quantity": 15}], [], [-1], [1e308, 1e308]],
            "start": ["09:45", "12:30", "00:00", "23:59", "9:45", "25:00"], "end": ["12:30", "01:00", "9:45"],
            "first": ["03-20", "2026-03-20", "2027-01-01", "02-29", "13-01"], "second": ["03-12", "2026-03-12"],
            "total_cap": [600, 0, -5, 1e308], "item_cap": [300, 0, -1], "replaces": [["C0"], ["C1"], ["C%d" % i], []],
            "refs": [["I0"], ["I1", "I2"], [], None]}
        for field in fields + r.sample(["refs", "label", "replaces"], r.randint(0, 3)):
            if r.random() < 0.85:
                check[field] = r.choice(choices.get(field, []) + [self.value()])
        return check

    def document(self):
        r = self.random
        if r.random() < 0.05:
            return r.choice([[], 3, "x", None, {"objective": 1}])
        document = {"version": r.choice([1, 2, None]),
                    "objective": r.choice([{"text": "Plan", "quote": QUOTE}, {"text": "", "quote": ""}, None, "x"]),
                    "items": [self.item(i) for i in range(r.randint(0, 4))],
                    "checks": [self.check(i) for i in range(r.randint(0, 5))]}
        for key in ("items", "checks"):
            if r.random() < 0.05:
                document[key] = self.value()
        return document

    def hook(self, transcript):
        r = self.random
        hook = r.choice([{}, {"session_id": r.choice(["s1", "s/../2", "", None, 5])}])
        if r.random() < 0.8:
            hook["transcript_path"] = r.choice([transcript, "/nonexistent", None, 3])
        if r.random() < 0.5:
            hook["stop_hook_active"] = r.choice([True, False, "yes"])
        if r.random() < 0.7:
            hook["last_assistant_message"] = r.choice(REPLIES)
        if r.random() < 0.3:
            hook["prompt"] = r.choice(["plan the budget for March 12", "", None, "a[1:20]"])
        if r.random() < 0.2:
            hook["tool_input"] = r.choice([{"file_path": "/x/plan.md"}, {}, None, "x"])
        return hook


def run(command, args, stdin_text):
    out, err, previous = io.StringIO(), io.StringIO(), sys.stdin
    sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = command(args)
    except SystemExit as exit_:
        code = exit_.code
    finally:
        sys.stdin = previous
    return code, out.getvalue()


class HookFuzzTests(unittest.TestCase):
    def test_no_command_crashes_on_malformed_records_and_hook_input(self):
        generator = Generator(20261124)
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("RUMBO_STATE_DIR")
            os.environ["RUMBO_STATE_DIR"] = os.path.join(tmp, "state")
            try:
                transcript = os.path.join(tmp, "t.jsonl")
                with open(transcript, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                             "message": {"role": "user", "content": QUOTE}}) + "\nnot json\n")
                path = os.path.join(tmp, ".rumbo", "record.json")
                os.makedirs(os.path.dirname(path))
                for case in range(300):
                    text = json.dumps(generator.document())
                    hook = json.dumps(generator.hook(transcript))
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(text)
                    for name, command in COMMANDS:
                        with self.subTest(case=case, command=name):
                            code, out = run(command, record.build_parser().parse_args([name, "--record", path]), hook)
                            if name in ("show", "pre-write", "stop-gate"):
                                self.assertIn(code, (0, None), text)
                            self.assertNotIn("GATE_ERROR", out, text)
                            if name == "stop-gate" and out.strip():
                                decision = json.loads(out)
                                self.assertEqual(decision["decision"], "block")
                                self.assertIsInstance(decision["reason"], str)
            finally:
                if previous is None:
                    os.environ.pop("RUMBO_STATE_DIR", None)
                else:
                    os.environ["RUMBO_STATE_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
