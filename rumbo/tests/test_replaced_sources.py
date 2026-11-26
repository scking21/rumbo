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
import time
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

    def test_a_replaced_quote_that_says_one_is_read(self):
        # Review: the skip for quotes that name no value must not skip "one", which the source check reads as 1.
        doc = {"version": 1, "objective": {"text": "Tickets", "quote": "Tickets are $50 each, and the cap is $100."},
               "items": [item("I1", "We need one."), item("I2", "Let's go ahead.", "commitment", replaces=["I1"])],
               "checks": [{"id": "C1", "kind": "within_budget", "amounts": [{"unit": 50, "quantity": 1}],
                           "total_cap": 100, "refs": ["I2"]}]}
        self.assertEqual(record.validate_record(doc), [])
        self.assertEqual([line.split(" -> ")[0] for line in record.open_problem_lines(doc)],
                         ["SOURCE C1: amounts quantity 1 is only in the words of I1, which I2 replaced"])

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


class ReplacedSourcesSpeedTests(unittest.TestCase):
    """0.3.22 read a check's sources again with each replaced item's quote, for every check.

    On a record whose replaced items held long quotes that took 42 seconds,
    against the hooks' 10 second timeout. Each quote is now read once, and only
    when it names a value of the check's kind.
    """
    FILLER = " ".join("We discussed option %d at $%d with %d people on March %d." % (i, 100 + i, 10 + i, 1 + i % 28)
                      for i in range(200))

    def large_record(self):
        items = []
        for n in range(1, 41):
            # Every fourth item is replaced and holds a long quote.
            quote = "Option %d costs $%d. %s" % (n, 1000 + n, self.FILLER if n % 4 == 1 else "")
            entry = item("I%d" % n, quote)
            if n % 2 == 0:
                entry.update(status="commitment", replaces=["I%d" % (n - 1)])
            items.append(entry)
        checks = [check("C%d" % k, amounts=[1000 + j for j in range(1, 21, 2)] + [7777],
                        refs=["I%d" % m for m in range(1, 41, 3)]) for k in range(1, 11)]
        for each in checks:
            each["total_cap"] = 10 ** 7
        return document(checks, items)

    def test_problem_lines_stay_fast_when_replaced_items_hold_long_quotes(self):
        doc = self.large_record()
        self.assertEqual(record.validate_record(doc), [])
        started = time.monotonic()
        lines = record.open_problem_lines(doc)
        parts = record.record_problems(doc)[0]
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(any(line.startswith("SOURCE C1: ") for line in lines), lines[:3])
        self.assertEqual(len(parts), 10)

    def test_the_hooks_stay_fast_on_that_record(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, ".rumbo", "record.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.large_record(), handle)
        env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(tmp.name, "state"))
        for command, payload in (("check", None), ("pre-write", {"session_id": "s1", "cwd": tmp.name,
                                                                 "tool_input": {"file_path": os.path.join(tmp.name, "plan.md")}})):
            with self.subTest(command=command):
                started = time.monotonic()
                subprocess.run([sys.executable, SCRIPT, command, "--record", path], capture_output=True, text=True,
                               input=None if payload is None else json.dumps(payload), env=env, timeout=30)
                self.assertLess(time.monotonic() - started, 5)

    def test_numbers_read_from_a_text_are_kept_for_a_bounded_number_of_texts(self):
        self.assertTrue(record._is_number_sourced(650, "The rate went up to $650."))
        self.assertFalse(record._is_number_sourced(500, "The rate went up to $650."))
        # Minutes are read without an hour unit's numbers; the two readings are kept apart.
        self.assertTrue(record._is_number_sourced(2, "2 hours"))
        self.assertFalse(record._is_number_sourced(2, "2 hours", excluded_unit=record.NON_MINUTE_TIME_UNIT))
        for n in range(record._SOURCED_NUMBERS_KEPT + 10):
            record._is_number_sourced(n + 1, "We have %d chairs." % n)
        self.assertLessEqual(len(record._SOURCED_NUMBERS), record._SOURCED_NUMBERS_KEPT)
