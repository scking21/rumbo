"""Values that only a replaced item's words give are named as such, not as the agent's assumption.

In a live 0.3.21 session of 02-launch-full the user said "I want to do both
marketing options". Haiku recorded that as a commitment replacing the items that
quoted the $650 newsletter rate and the $300 ads, so their words no longer
sourced the budget checks. Every hook then called the user's prices the agent's
assumption, and the hold before the plan asked haiku to tell the user so. A
replacement that drops an option should take its values away (dropped_by); one
that only chooses it should not. The problem lines now say whose words the
values were, and give both ways to resolve them.
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

BUDGET = "The launch budget is $1,200 total."
OPTIONS = "Marketing options: $500 for a local newsletter sponsorship, or $300 for social media ads, or both."
RATE = "The newsletter came back: their sponsorship rate went up to $650, not $500."
BOTH = "I want to do both marketing options."
SAID = [BUDGET, OPTIONS, RATE, BOTH]


def item(item_id, quote, status="uncertain", **extra):
    return dict({"id": item_id, "text": quote[:40], "quote": quote, "status": status}, **extra)


def items():
    return [item("I1", BUDGET, "commitment"), item("I2", OPTIONS), item("I7", RATE),
            item("I10", BOTH, "commitment", replaces=["I2", "I7"])]


def document(checks, record_items=None):
    return {"version": 1, "objective": {"text": "Launch", "quote": BUDGET},
            "items": items() if record_items is None else record_items, "checks": checks}


def check(check_id="C3", amounts=(650, 300), refs=("I1", "I2", "I7"), **extra):
    return dict({"id": check_id, "kind": "within_budget", "label": "both marketing options",
                 "amounts": list(amounts), "total_cap": 1200, "refs": None if refs is None else list(refs)}, **extra)


class ReplacedSourcesTests(unittest.TestCase):
    def test_values_only_in_replaced_words_get_a_source_line_not_an_assumption_line(self):
        lines = record.open_problem_lines(document([check()]))
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith(
            "SOURCE C3: amounts 650, amounts 300 are only in the words of I2 and I7, which I10 replaced -> "
            "if the user kept these values, they are not your assumption: source them from an item in this "
            "check's refs that is not replaced (take I2 and I7 out of I10's replaces, or quote the user's words "
            "that keep them); if the user dropped them, update the check without them, or set its dropped_by"),
            lines[0])

    def test_a_check_that_cites_the_replacing_item_finds_the_words_it_replaced(self):
        # Haiku's later checks listed I10, the choice, rather than the items with the prices.
        lines = record.open_problem_lines(document([check(refs=("I1", "I10"))]))
        self.assertEqual([line.split(" -> ")[0] for line in lines],
                         ["SOURCE C3: amounts 650, amounts 300 are only in the words of I2 and I7, which I10 replaced"])

    def test_the_agents_own_values_still_get_an_assumption_line(self):
        doc = document([check(amounts=(650, 300, 250), refs=("I1", "I10"))])
        lines = record.open_problem_lines(doc)
        self.assertEqual([line.split(" -> ")[0] for line in lines], [
            "ASSUMPTION C3: amounts 250 not in the user's quoted words",
            "SOURCE C3: amounts 650, amounts 300 are only in the words of I2 and I7, which I10 replaced"])
        self.assertEqual(record.record_problems(doc)[0], [
            "C3: UNSOURCED within_budget both marketing options: amounts 650, amounts 300, amounts 250 not in the "
            "user's quoted words (amounts 650, amounts 300 only in the words of I2 and I7, which I10 replaced: "
            + record.SOURCE_ACTION % ("I2 and I7", "I10's replaces") + ")"])

    def test_a_failing_check_keeps_its_conflict_and_names_the_replaced_words(self):
        doc = document([check(amounts=(650, 300, 180, 100), refs=("I1", "I10"))])
        lines = record.open_problem_lines(doc)
        self.assertTrue(lines[0].startswith("CONFLICT C3: total 1230 exceeds total_cap 1200 by 30 -> "), lines)
        self.assertTrue(lines[1].startswith("SOURCE C3: amounts 650, amounts 300 are only in the words of I2 and I7"))
        self.assertEqual(lines[2:], [])
        part = record.record_problems(doc)[0][0]
        self.assertIn("(also unsourced: amounts 650, amounts 300, amounts 180, amounts 100; amounts 650, "
                      "amounts 300 only in the words of I2 and I7, which I10 replaced: ", part)

    def test_values_sourced_from_a_live_item_need_nothing(self):
        live = items()[:3] + [item("I10", BOTH, "commitment")]
        self.assertEqual(record.open_problem_lines(document([check()], live)), [])

    def test_no_note_for_words_the_check_never_cited_or_a_rejected_item(self):
        # Neither the replaced item nor its replacement is among the refs.
        self.assertEqual([line.split(":")[0] for line in record.open_problem_lines(document([check(refs=("I1",))]))],
                         ["ASSUMPTION C3"])
        # A rejected option's words are not offered back as a source.
        rejected = [item("I1", BUDGET, "commitment"), item("I2", OPTIONS, "rejected"),
                    item("I10", BOTH, "commitment", replaces=["I2"])]
        lines = record.open_problem_lines(document([check(amounts=(300,), refs=("I1", "I10"))], rejected))
        self.assertEqual([line.split(":")[0] for line in lines], ["ASSUMPTION C3"])

    def test_without_refs_every_replaced_item_is_looked_at(self):
        lines = record.open_problem_lines(document([check(refs=None)]))
        self.assertEqual([line.split(" -> ")[0] for line in lines],
                         ["SOURCE C3: amounts 650, amounts 300 are only in the words of I2 and I7, which I10 replaced"])

    def test_a_dropped_check_needs_nothing(self):
        dropped = check(amounts=(500,), refs=("I1", "I2"), dropped_by="I10")
        doc = document([dropped], [item("I1", BUDGET, "commitment"), item("I2", OPTIONS),
                                   item("I10", "Let's skip the newsletter.", "commitment", replaces=["I2"])])
        self.assertEqual(record.validate_record(doc), [])
        self.assertEqual(record.open_problem_lines(doc), [])


class ReplacedSourcesHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "project")
        self.record = os.path.join(self.project, ".rumbo", "record.json")
        os.makedirs(os.path.dirname(self.record))
        self.env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(self.tmp.name, "state"))
        self.transcript = os.path.join(self.tmp.name, "t.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            for text in SAID:
                handle.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                         "message": {"role": "user", "content": text}}) + "\n")
        with open(self.record, "w", encoding="utf-8") as handle:
            json.dump(document([check()]), handle)

    def tearDown(self):
        self.tmp.cleanup()

    def run_record(self, command, payload):
        proc = subprocess.run([sys.executable, SCRIPT, command, "--record", self.record], input=json.dumps(payload),
                              text=True, capture_output=True, env=self.env, timeout=10)
        self.assertEqual(proc.stderr, "")
        return proc.returncode, proc.stdout

    def test_check_names_the_replaced_words(self):
        proc = subprocess.run([sys.executable, SCRIPT, "check", "--record", self.record], text=True,
                              capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout.strip(),
                         "C3: UNSOURCED within_budget both marketing options: amounts 650, amounts 300 not in the "
                         "user's quoted words (only in the words of I2 and I7, which I10 replaced: "
                         + record.SOURCE_ACTION % ("I2 and I7", "I10's replaces") + ")")

    def test_the_hold_before_a_write_and_the_stop_block_name_them(self):
        code, out = self.run_record("pre-write", {"session_id": "s1", "cwd": self.project,
                                                  "tool_input": {"file_path": os.path.join(self.project, "plan.md")}})
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("SOURCE C3: amounts 650, amounts 300 are only in the words of I2 and I7", reason)
        self.assertNotIn("ASSUMPTION C3", reason)
        code, out = self.run_record("stop-gate", {"session_id": "s1", "transcript_path": self.transcript,
                                                  "last_assistant_message": "Both options fit."})
        self.assertIn("only in the words of I2 and I7, which I10 replaced", json.loads(out)["reason"])


if __name__ == "__main__":
    unittest.main()
