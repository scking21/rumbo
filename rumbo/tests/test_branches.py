"""Level 3 of the part-by-part pass: single functions and branches, found by mutation testing.

Each test here kills mutants of record.py that the rest of the suite let live: a
comparison, constant or connective changed in one place, and every test that runs
that line still passing. Most are boundaries no test stood on.
"""
from decimal import Decimal as decimal
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record.py"
SPEC = importlib.util.spec_from_file_location("branches_record", SCRIPT)
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)


def document(check, said):
    return {"version": 1, "objective": {"text": "Plan", "quote": said}, "items": [], "checks": [check]}


def budget(amounts, total_cap=600, item_cap=None):
    check = {"id": "B", "kind": "within_budget", "amounts": amounts, "total_cap": total_cap}
    if item_cap is not None:
        check["item_cap"] = item_cap
    return check


class FractionAtTheStartTests(unittest.TestCase):
    """_after_fraction_prefix walks back from an amount; a fraction can sit at index 0."""

    def test_a_fraction_that_opens_the_quote_still_keeps_its_amount_unsourced(self):
        for said in ("½ a million for the venue", "½ of 1 million", "1/2 of a million for the venue",
                     "3 fifths of a million", "50% of one million", "% of a million"):
            with self.subTest(said=said):
                self.assertFalse(record._is_number_sourced(1000000, said))
                self.assertFalse(record._is_money_sourced(1000000, said))
        self.assertTrue(record._is_money_sourced(1000000, "1 million for the venue"))


class ClockValueBoundaryTests(unittest.TestCase):
    """_clock_time: a clock value is above 0 and below 13."""

    def test_the_ends_of_the_twelve_hour_clock(self):
        for said, value, money in (("Doors at 1pm. Budget 600.", 1, False), ("Doors at 12pm. Budget 600.", 12, False),
                                   ("Doors 12.30pm. Budget 600.", 12.30, False), ("Rent 13 pm. Budget 600.", 13, True),
                                   ("Doors 1-2pm. Budget 600.", 1, False), ("Rooms 13-14pm. Budget 600.", 13, True)):
            with self.subTest(said=said):
                self.assertEqual(record._is_money_sourced(value, said), money)


class ArtifactLimitTests(unittest.TestCase):
    """_artifact_observation: a file exactly at the hook's limit is read."""

    def test_a_file_at_the_limit_is_hashed_and_one_byte_over_is_not(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "report.txt")
            with open(path, "wb") as handle:
                handle.write(b"1234567")
            digest = hashlib.sha256(b"1234567").hexdigest()
            at_limit = record._artifact_observation(root, {"path": "report.txt", "sha256": digest}, max_bytes=7)
            over = record._artifact_observation(root, {"path": "report.txt", "sha256": digest}, max_bytes=6)
            self.assertEqual((at_limit["state"], over["state"]), ("current", "too_large_for_hook"))


class OwnValueTests(unittest.TestCase):
    """_calls_own: the user's word before an assumption word gives the value to the user."""

    def test_a_user_word_that_opens_the_line_counts(self):
        self.assertFalse(record._calls_own("Your estimate of $50 holds."))
        self.assertFalse(record._calls_own("You estimated $50 for printing."))
        self.assertTrue(record._calls_own("My estimate is $50."))
        self.assertTrue(record._calls_own("Estimate: $50."))


class CountNounTests(unittest.TestCase):
    """_count_stems: a zero count meets its price per unit in either number."""

    def test_no_plural_meets_its_price_per_singular(self):
        # One guess per plural made "cooky", "classe", "boxe" and "py", which met no
        # "per cookie", "per class", "per box" or "a pie" (found by mutating _count_stem).
        for said in ("Cookies are $2 per cookie. No cookies sold.", "$20 per class. No classes yet.",
                     "$2 per box. No boxes left.", "$2 a pie. No pies sold.", "$2 per bus. No buses booked.",
                     "$2 per party. No parties yet.", "$2 per person. No people yet."):
            with self.subTest(said=said):
                unit = int(said.split("$")[1].split()[0])
                check = budget([{"unit": unit, "quantity": 0}])
                self.assertEqual(record.unsourced_values(document(check, "Budget $600. " + said), check), [])
        check = budget([{"unit": 2, "quantity": 0}])
        self.assertEqual(record.unsourced_values(document(check, "Budget $600. $2 per seat. No tables sold."), check),
                         ["amounts quantity 0"])


class CurrencyCodeTests(unittest.TestCase):
    """_currency_before: the position it returns is where a sign is looked for."""

    def test_a_sign_before_a_currency_code_stays_with_the_amount(self):
        for said in ("A refund of -USD 50.", "A refund of −EUR 50.", "A refund of - USD 50."):
            with self.subTest(said=said):
                self.assertFalse(record._is_money_sourced(50, said))
                self.assertTrue(record._is_money_sourced(-50, said))
        self.assertTrue(record._is_money_sourced(50, "A USD 50 fee."))


class DroppedCheckTests(unittest.TestCase):
    """_dropped_value_faults: every refused drop is named, not only the first."""

    def test_two_refused_drops_are_both_named(self):
        def item(item_id, quote, status="commitment", **extra):
            return dict({"id": item_id, "text": quote, "quote": quote, "status": status}, **extra)
        items = [item("I1", "It's the morning of March 12"),
                 item("I2", "Dr. Okafor says the foundation must approve his slides by March 20.", "uncertain"),
                 item("I3", "I think we should go with just the maker-space team.", replaces=["I2"]),
                 item("I4", "The printer needs the handout files by March 1.", "uncertain"),
                 item("I5", "Skip the printer, we'll print the handouts ourselves by March 5.", replaces=["I4"])]
        checks = [{"id": "C2", "kind": "before", "first": "03-01", "second": "03-12", "refs": ["I1", "I4"], "dropped_by": "I5"},
                  {"id": "C3", "kind": "before", "first": "03-01", "second": "03-12", "refs": ["I1", "I2", "I4"],
                   "dropped_by": "I3"}]
        faults = record.validate_record({"version": 1, "objective": {"text": "Workshop", "quote": "Plan the workshop."},
                                         "items": items, "checks": checks})
        self.assertEqual([fault.split(":")[0] for fault in faults], ["checks[0].dropped_by", "checks[1].dropped_by"])
        self.assertIn('I5\'s words name a value ("March 5")', faults[0])
        self.assertIn("no value of this check comes only from the items I3 replaced", faults[1])


class IdListTests(unittest.TestCase):
    def test_ids_are_listed_in_order_with_and_before_the_last(self):
        self.assertEqual([record._id_list(ids) for ids in (["I1"], ["I1", "I2"], ["I1", "I2", "I3"])],
                         ["I1", "I1 and I2", "I1, I2 and I3"])


class HandoffRootTests(unittest.TestCase):
    """_handoff_root_matches: a path that spells .rumbo/record.json in another case."""

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_a_case_variant_that_is_the_standard_record_must_match_its_project(self):
        with tempfile.TemporaryDirectory() as parent:
            project, sibling = os.path.join(parent, "project"), os.path.join(parent, "sibling")
            os.makedirs(os.path.join(project, ".rumbo"))
            os.mkdir(sibling)
            with open(os.path.join(project, ".rumbo", "record.json"), "w", encoding="utf-8") as handle:
                handle.write("{}")
            variant_dir = os.path.join(project, ".RUMBO")
            if not os.path.exists(variant_dir):
                os.symlink(".rumbo", variant_dir)
            variant = os.path.join(variant_dir, "record.json")
            self.assertTrue(record._handoff_root_matches(variant, project))
            self.assertFalse(record._handoff_root_matches(variant, sibling))


class JsonDepthTests(unittest.TestCase):
    """_loads: the nesting limit is 64 levels, counted as the brackets open and close."""

    def test_sixty_four_levels_load_and_sixty_five_do_not(self):
        expected = []
        for _ in range(63):
            expected = [expected]
        self.assertEqual(record._loads("[" * 64 + "]" * 64), expected)
        with self.assertRaises(ValueError):
            record._loads("[" * 65 + "]" * 65)
        # A closed sibling gives its level back once: the deep branch still counts 65.
        with self.assertRaises(ValueError):
            record._loads("[[]," + "[" * 64 + "]" * 64 + "]")
        self.assertIsInstance(record._loads("[[]," + "[" * 63 + "]" * 63 + "]"), list)
        # Brackets inside strings are text, not nesting.
        self.assertEqual(record._loads('{"a": "' + "[" * 100 + '"}'), {"a": "[" * 100})


class ReplacementCycleTests(unittest.TestCase):
    """_on_a_cycle: every root is walked, also after one an earlier walk reached."""

    def test_a_cycle_after_a_chain_is_found(self):
        self.assertEqual(record._on_a_cycle({"A": ["B"], "B": [], "C": ["D"], "D": ["C"]}), {"C", "D"})
        self.assertEqual(record._on_a_cycle({"A": ["B"], "B": ["C"], "C": []}), set())
        self.assertEqual(record._on_a_cycle({"A": ["A"]}), set())


class DateRangeOrderTests(unittest.TestCase):
    """_is_date_sourced: a day-first range whose start has a month of its own is skipped, not the rest."""

    def test_a_later_range_counts_after_an_earlier_one_is_skipped(self):
        said = "June 3-5 July is the first try; the second is 3-5 July."
        self.assertTrue(record._is_date_sourced("07-03", said)[0])
        self.assertFalse(record._is_date_sourced("07-03", "June 3-5 July is the only try.")[0])


class MinutesPhraseTests(unittest.TestCase):
    """_minutes_phrase: the number said must itself carry the minute unit."""

    def test_a_number_without_its_unit_is_no_minutes(self):
        self.assertTrue(record._minutes_phrase(20, "It runs twenty minutes over."))
        self.assertFalse(record._minutes_phrase(20, "It runs five minutes over, with twenty people."))
        self.assertFalse(record._minutes_phrase(20, "It runs 5 minutes over, with 20 people."))


class ReplyRangeTests(unittest.TestCase):
    """_range_spans: a clock has no hour 24."""

    def test_an_hour_past_23_spans_nothing(self):
        self.assertEqual(record._range_spans("Talk 23:00-23:30."), {30})
        self.assertEqual(record._range_spans("Talk 23:30-24:30."), set())


class MarkerTests(unittest.TestCase):
    """_open_marker: only a write creates the state directory."""

    def test_reading_a_marker_in_a_missing_directory_creates_nothing(self):
        with tempfile.TemporaryDirectory() as parent:
            path = os.path.join(parent, "state", "s1-abc.prompts")
            with self.assertRaises(OSError):
                record._open_marker(path)
            self.assertFalse(os.path.exists(os.path.join(parent, "state")))
            with record._open_marker(path, "w") as handle:
                handle.write("1")
            with record._open_marker(path) as handle:
                self.assertEqual(handle.read(), "1")


class PreWriteTargetTests(unittest.TestCase):
    """_pre_write: a target that is no path still gets the record's lines."""

    def test_a_file_path_that_is_not_a_string_is_ignored(self):
        import json
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "record.json")
            check = {"id": "B", "kind": "within_budget", "amounts": [700], "total_cap": 600}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(document(check, "Budget 600, catering 700."), handle)
            env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(directory, "state"))
            for target in (7, ["plan.md"], None):
                with self.subTest(target=target):
                    payload = {"session_id": "s-%s" % type(target).__name__, "tool_name": "Write",
                               "tool_input": {"file_path": target}}
                    result = subprocess.run([sys.executable, str(SCRIPT), "pre-write", "--record", path],
                                            input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=20)
                    self.assertIn("CONFLICT B", result.stdout)


class NumberReaderEdgeTests(unittest.TestCase):
    """_read_numbers: what follows an unreadable amount, a sign at index 0, a sign after a word."""

    def test_reading_goes_on_after_an_amount_too_large_to_hold(self):
        self.assertEqual(record._sourced_numbers("Maybe $1e999999k, or 50."), frozenset({decimal("50")}))

    def test_a_sign_that_opens_the_quote_is_kept(self):
        self.assertEqual(record._sourced_numbers("-$50 refund", record.MONEY_EXCLUDED_UNIT), frozenset({decimal("-50")}))
        self.assertEqual(record._sourced_numbers("-50 refund"), frozenset({decimal("-50")}))

    def test_a_hyphen_after_a_word_is_no_minus(self):
        self.assertTrue(record._is_number_sourced(6, "a four-to-six-person team"))
        self.assertEqual(record._sourced_numbers("a refund of -six dollars"), frozenset({decimal("-6")}))


class RangeHourEdgeTests(unittest.TestCase):
    """_range_starts and _range_spans: the 12 and the 1 of a twelve-hour clock."""

    def test_the_twelve_and_the_one(self):
        for said, time, sourced in (("Runs 12-1:30.", "00:00", True), ("Runs 1-2:30.", "13:00", True),
                                    ("Runs 1-2pm.", "13:00", True), ("Runs 11-12pm.", "11:00", True),
                                    ("Runs 13-2pm.", "13:00", False), ("Runs 13-2pm.", "01:00", False),
                                    ("Runs 2-13pm.", "02:00", False)):
            with self.subTest(said=said, time=time):
                self.assertEqual(record._is_time_sourced(time, said), sourced)
        self.assertEqual(record._range_spans("12:00pm-1:00pm"), {60})
        self.assertEqual(record._range_spans("12pm-1pm"), {60})
        self.assertEqual(record._range_spans("0:30am-1am"), set())


class ReplyReaderShortcutTests(unittest.TestCase):
    """_says: the quick tests before each reading must not reject what the reading accepts, or accept on their own."""

    def test_noon_and_a_day_number(self):
        self.assertTrue(record._says("time", "12:00", "Lunch at noon."))
        self.assertTrue(record._says("time", "00:00", "Doors close at midnight."))
        self.assertFalse(record._says("date", "03-20", "We have 20 people."))
        self.assertTrue(record._says("date", "03-20", "It is on March 20."))


class RetractionTests(unittest.TestCase):
    """_retraction_for: a retraction is quoted whole up to 120 characters."""

    def test_the_quote_is_cut_after_120_characters(self):
        item = {"text": "Use the ruby theme", "quote": "Use the ruby theme"}
        # No space near the cut: the reader collapses spaces, which would shorten the message.
        words = "Cancel the ruby theme: " + "x" * 200
        self.assertEqual(record._retraction_for(item, [words[:120]]), words[:120])
        cut = record._retraction_for(item, [words[:121]])
        self.assertEqual(cut, words[:117] + "...")
        self.assertEqual(len(cut), 120)
        self.assertIsNone(record._retraction_for(item, ["Use bullets instead of a table."]))


class OutcomeListTests(unittest.TestCase):
    """_recorded_outcome_lines: eight outcomes are listed, the ninth is counted."""

    def test_eight_and_nine_outcomes(self):
        def row(number):
            return {"id": "O%d" % number, "text": "Outcome %d" % number, "owner": "worker", "acceptance": "done",
                    "status": "verified", "evidence": "read back"}
        for count, last in ((8, "OUTCOME O8 [verified] owner worker: Outcome 8"), (9, "... and 1 more outcomes")):
            with self.subTest(count=count):
                lines = record._recorded_outcome_lines({"target": "t", "outcomes": [row(n) for n in range(1, count + 1)]})
                self.assertEqual(lines[-1], last)
                self.assertEqual(len(lines), 10 if count == 8 else 11)


class ArtifactPathTests(unittest.TestCase):
    """_relative_artifact_path: only a nonblank relative path that stays inside the project."""

    def test_paths(self):
        self.assertEqual([record._relative_artifact_path(value) for value in (7, None, "", "   ", "a.txt", "/x", "../y", "a/../b")],
                         [None, None, None, None, "a.txt", None, None, "b"])


class ToldStateTests(unittest.TestCase):
    """_remember_told: a label told again is not counted again; one told more often is."""

    def test_counts_merge_to_the_most_told(self):
        with tempfile.TemporaryDirectory() as directory:
            before = os.environ.get("RUMBO_STATE_DIR")
            os.environ["RUMBO_STATE_DIR"] = directory
            try:
                record._remember_told("s1", {}, {"C1": ["x", "x"]})
                self.assertEqual(record._read_told("s1"), {"C1": ["x", "x"]})
                record._remember_told("s1", record._read_told("s1"), {"C1": ["x"]})
                self.assertEqual(record._read_told("s1"), {"C1": ["x", "x"]})
                record._remember_told("s1", record._read_told("s1"), {"C1": ["x", "x", "x"], "C2": ["y"]})
                self.assertEqual(record._read_told("s1"), {"C1": ["x", "x", "x"], "C2": ["y"]})
            finally:
                if before is None:
                    del os.environ["RUMBO_STATE_DIR"]
                else:
                    os.environ["RUMBO_STATE_DIR"] = before


def item(item_id, quote, status="commitment", **extra):
    return dict({"id": item_id, "text": quote, "quote": quote, "status": status}, **extra)


class SkipNotStopTests(unittest.TestCase):
    """Loops that pass over one entry must go on to the next, not stop."""

    def test_an_item_after_a_closed_or_replaced_one_still_sources_a_check(self):
        check = {"id": "B", "kind": "within_budget", "amounts": [250], "total_cap": 600}
        for first in (item("I1", "Venue was 300.", "rejected"), item("I1", "Venue was 300.", "done")):
            with self.subTest(status=first["status"]):
                said = {"version": 1, "objective": {"text": "x", "quote": "Budget 600."},
                        "items": [first, item("I2", "Catering is 250.")], "checks": [check]}
                self.assertEqual(record.unsourced_values(said, check), [])
        said = {"version": 1, "objective": {"text": "x", "quote": "Budget 600."},
                "items": [item("I0", "Old: 100."), item("I1", "Venue 300.", replaces=["I0"]), item("I2", "Catering is 250.")],
                "checks": [check]}
        self.assertEqual(record.unsourced_values(said, check), [])
        narrowed = dict(check, refs=["I2"])
        said = {"version": 1, "objective": {"text": "x", "quote": "Budget 600."},
                "items": [item("I1", "Venue 300."), item("I2", "Catering is 250.")], "checks": [narrowed]}
        self.assertEqual(record.unsourced_values(said, narrowed), [])

    def test_a_failing_check_after_a_retired_one_is_still_failing(self):
        checks = [{"id": "C1", "kind": "within_budget", "amounts": [700], "total_cap": 600},
                  {"id": "C2", "kind": "within_budget", "amounts": [800], "total_cap": 600, "replaces": ["C1"]},
                  {"id": "C3", "kind": "before", "first": "03-20", "second": "03-12"}]
        said = {"version": 1, "objective": {"text": "x", "quote": "Budget 600, 700, 800; March 20 then March 12."},
                "items": [], "checks": checks}
        self.assertEqual([check["id"] for check, _detail in record.failing_checks(said)], ["C2", "C3"])

    def test_every_bad_reference_is_named(self):
        def faults(checks, items=()):
            return [fault.split(":")[0] for fault in record.validate_record(
                {"version": 1, "objective": {"text": "x", "quote": "1 2"}, "items": list(items), "checks": checks})]

        def budget_check(check_id, **extra):
            return dict({"id": check_id, "kind": "within_budget", "amounts": [1], "total_cap": 2}, **extra)
        decision = [item("I1", "1 2")]
        # Each order matters: a check skipped, or refused, first must not end the walk.
        self.assertEqual(faults([budget_check("C1", dropped_by="I1"), budget_check("C2", dropped_by="nope")], decision),
                         ["checks[0].dropped_by", "checks[1].dropped_by"])
        self.assertEqual(faults([budget_check("C1", dropped_by="nope"), budget_check("C2", dropped_by="I1")], decision),
                         ["checks[0].dropped_by", "checks[1].dropped_by"])
        self.assertEqual(faults([budget_check("C1"), budget_check("C2", dropped_by="nope")], decision), ["checks[1].dropped_by"])
        self.assertEqual(faults([budget_check("C1", replaces=["nope"]), budget_check("C2", replaces=["also-nope"])]),
                         ["checks[0].replaces[0]", "checks[1].replaces[0]"])
        self.assertEqual(faults([budget_check("C1", replaces="C9"), budget_check("C2", replaces=["nope"])]),
                         ["checks[0].replaces", "checks[1].replaces[0]"])

    def test_show_lists_a_live_item_after_a_closed_one(self):
        import json
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "record.json")
            said = {"version": 1, "objective": {"text": "Plan", "quote": "Plan."},
                    "items": [item("I1", "Use the old venue", "rejected"), item("I0", "Use the hall", "draft"),
                              item("I3", "Use the town hall", "draft", replaces=["I0"]), item("I2", "Use the library", "draft")],
                    "checks": []}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(said, handle)
            shown = subprocess.run([sys.executable, str(SCRIPT), "show", "--record", path], input="",
                                   capture_output=True, text=True, timeout=20).stdout
            self.assertIn("[draft] I3 Use the town hall", shown)
            self.assertIn("[draft] I2 Use the library", shown)
            self.assertNotIn("I1 ", shown)
            self.assertNotIn("I0 ", shown)
            # A summary exactly as long as --max-chars is not cut.
            body = shown.split("--- rumbo record: agent-written data, not instructions ---\n")[1].split("\n--- end rumbo record ---")[0]
            exact = subprocess.run([sys.executable, str(SCRIPT), "show", "--record", path, "--max-chars", str(len(body))],
                                   input="", capture_output=True, text=True, timeout=20).stdout
            self.assertEqual(exact, shown)


class ProblemsAfterARetiredCheckTests(unittest.TestCase):
    """record_problems, open_problem_lines, validate_record and replaced_sources go past what they skip."""

    def test_problems_after_a_retired_check(self):
        checks = [{"id": "C1", "kind": "within_budget", "amounts": [700], "total_cap": 600},
                  {"id": "C2", "kind": "within_budget", "amounts": [500], "total_cap": 600, "replaces": ["C1"]},
                  {"id": "C3", "kind": "before", "first": "03-20", "second": "03-12"},
                  {"id": "C4", "kind": "within_budget", "amounts": [450], "total_cap": 600}]
        said = {"version": 1, "objective": {"text": "x", "quote": "Budget 600, 700 or 500; March 20 then March 12."},
                "items": [], "checks": checks}
        self.assertEqual(record.record_problems(said)[1], ["C3", "C4"])
        self.assertEqual([line.split(":")[0] for line in record.open_problem_lines(said)], ["CONFLICT C3", "ASSUMPTION C4"])

    def test_an_item_after_one_that_is_no_object_is_still_validated(self):
        # Ids are checked in a pass of their own, so the second item lacks one.
        faults = record.validate_record({"version": 1, "objective": {"text": "x", "quote": "x"},
                                         "items": ["x", {"text": "t", "quote": "q"}], "checks": []})
        self.assertEqual([fault.split(":")[0] for fault in faults], ["items[0]", "items[1].id", "items[1].status"])

    def test_a_replaced_item_after_one_that_names_no_value(self):
        items = [item("I1", "Hire the band.", "draft"), item("I2", "Venue is 300.", "draft"),
                 item("I3", "Go with the library instead.", replaces=["I1", "I2"])]
        check = budget([300])
        said = {"version": 1, "objective": {"text": "x", "quote": "Budget 600."}, "items": items, "checks": [check]}
        self.assertEqual(record.replaced_sources(said, check, record.unsourced_values(said, check)),
                         (["amounts 300"], ["I2"], ["I3"]))


class ReaderEdgeTests(unittest.TestCase):
    def test_a_contrast_starts_a_new_clause_for_negation(self):
        check = budget([{"unit": 0, "quantity": 12}])
        said = document(check, "Budget 600. Not at the hotel, but breakfast is free for 12 attendees.")
        self.assertEqual(record.unsourced_values(said, check), [])

    def test_an_article_at_the_end_of_the_text(self):
        self.assertEqual(record._sourced_numbers("Twelve guests, then a"), frozenset({decimal("12")}))
        self.assertEqual(record._sourced_numbers("an"), frozenset())

    def test_a_signed_duration_that_opens_the_text(self):
        self.assertFalse(record._is_minutes_sourced(120, "-2 hours of setup"))
        self.assertFalse(record._is_minutes_sourced(120, "minus 2 hours"))
        self.assertTrue(record._is_minutes_sourced(120, "2 hours of setup"))

    def test_one_thirty_pm_with_a_dot(self):
        self.assertTrue(record._is_time_sourced("13:30", "Doors 1.30pm."))

    def test_reply_ranges_across_noon(self):
        self.assertEqual(record._range_spans("11am-1pm"), {120})
        self.assertEqual(record._range_spans("12:30pm-1pm"), {30})

    def test_injected_blocks_are_removed_from_a_message(self):
        self.assertEqual(record._without_injected("<system-reminder>x</system-reminder> Budget 600"), "Budget 600")
        self.assertEqual(record._without_injected("<system-reminder>x</system-reminder>"), "")

    def test_a_retraction_can_share_a_four_letter_word(self):
        self.assertEqual(record._retraction_for({"text": "Use ruby", "quote": "Use ruby"}, ["Cancel the ruby."]),
                         "Cancel the ruby.")


class FormatTests(unittest.TestCase):
    def test_days_later(self):
        self.assertEqual([record.fmt_minutes(minutes) for minutes in (30, 1440 + 30, 2 * 1440 + 30)],
                         ["00:30", "00:30 next day", "00:30 2 days later"])


class ToldReplacedTests(unittest.TestCase):
    def test_a_check_seen_twice_does_not_end_the_walk(self):
        checks = [{"id": "C1"}, {"id": "C2", "replaces": ["C1"]}, {"id": "C3"}, {"id": "C4", "replaces": ["C3", "C1", "C2"]}]
        told = {"C1": ["a"], "C2": ["b"], "C3": ["c"]}
        self.assertEqual(record._told_counts(told, {"checks": checks}, checks[3]), {"a": 1, "b": 1, "c": 1})


class CommandLineTests(unittest.TestCase):
    """build_parser and cmd_init: required arguments, and the record init writes."""

    def test_required_arguments_and_the_record_version(self):
        import json
        import subprocess
        import sys
        for args, missing in ((["init", "--quote", "x"], "--objective"), (["init", "--objective", "x"], "--quote"),
                              (["handoff"], "--root"), ([], "command")):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, str(SCRIPT)] + args, input="", capture_output=True, text=True,
                                        timeout=20)
                self.assertEqual(result.returncode, 2)
                self.assertIn(missing, result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, ".rumbo", "record.json")
            subprocess.run([sys.executable, str(SCRIPT), "init", "--record", path, "--objective", "Plan", "--quote", "Plan it."],
                           capture_output=True, text=True, timeout=20, check=True)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle),
                                 {"version": 1, "objective": {"text": "Plan", "quote": "Plan it."}, "items": [], "checks": []})


class CheckValueEdgeTests(unittest.TestCase):
    """_validate_check_values: the smallest values that are still valid."""

    def test_a_one_minute_segment_and_a_zero_item_cap(self):
        def faults(check):
            return record.validate_record({"version": 1, "objective": {"text": "x", "quote": "x"}, "items": [], "checks": [check]})
        self.assertEqual(faults({"id": "W", "kind": "fits_window", "start": "09:00", "end": "10:00", "segments_min": [1]}), [])
        self.assertEqual(faults({"id": "B", "kind": "within_budget", "amounts": [0], "total_cap": 600, "item_cap": 0}), [])
        self.assertEqual(faults({"id": "D", "kind": "before", "first": "03-40", "second": "03-12"}),
                         ["checks[0].first: CHECK_BAD_VALUE: use YYYY-MM-DD or MM-DD, e.g. 2026-03-12 or 03-12"])


class ClockParseTests(unittest.TestCase):
    """parse_time: two digits, a colon, two digits, within a day."""

    def test_edges(self):
        self.assertEqual([record.parse_time(text) for text in ("00:00", "23:59", "9:00", "09:0", "24:00", "23:60", "09:00:00")],
                         [0, 1439, None, None, None, None, None])


class UndecidedLinesTests(unittest.TestCase):
    """undecided_item_lines: eight undecided items are listed, more are counted; each text is cut at 200."""

    def test_eight_nine_and_a_long_text(self):
        def said(count, text="Maybe the library"):
            return {"items": [item("I%d" % n, text, "draft") for n in range(1, count + 1)]}
        self.assertEqual(len(record.undecided_item_lines(said(8))), 8)
        self.assertEqual(record.undecided_item_lines(said(9))[-1], "... and 1 more items not decided")
        line = record.undecided_item_lines(said(1, "x" * 300))[0]
        self.assertEqual(line, "NOT DECIDED I1 [draft]: " + "x" * 200)


class ReplyRangeEdgeTests(unittest.TestCase):
    """_range_spans: hours and minutes past a clock's, on either end, with or without am/pm."""

    def test_each_end(self):
        for line in ("24:00-24:30", "9:60-10:00", "9:00-9:60", "11:30pm-0:30am", "0:30am-1am", "13pm-2pm"):
            with self.subTest(line=line):
                self.assertEqual(record._range_spans("Talk " + line + "."), set())
        self.assertEqual(record._range_spans("Talk 11am-12pm."), {60})
        self.assertEqual(record._range_spans("Talk 12pm-1pm."), {60})


class DateFormatFaultTests(unittest.TestCase):
    def test_a_bad_date_is_not_also_called_the_wrong_format(self):
        check = {"id": "D", "kind": "before", "first": "2026-03-40", "second": "03-12"}
        faults = record.validate_record({"version": 1, "objective": {"text": "x", "quote": "x"}, "items": [], "checks": [check]})
        self.assertEqual(faults, ["checks[0].first: CHECK_BAD_VALUE: use YYYY-MM-DD or MM-DD, e.g. 2026-03-12 or 03-12"])


class ContinuedHoursTests(unittest.TestCase):
    """has_fraction: whole hours continued by a word that is no number or fraction keep their value."""

    def test_hours_and_some(self):
        self.assertTrue(record._is_minutes_sourced(120, "2 hours and some"))
        self.assertFalse(record._is_minutes_sourced(120, "2 hours and a third"))
        self.assertFalse(record._is_minutes_sourced(60, "1 hour and 20"))


class ConflictWaysTests(unittest.TestCase):
    """_conflict_ways: what a reply must say to tell a failing check."""

    def test_an_overnight_window_is_told_by_its_overrun(self):
        window = {"id": "W", "kind": "fits_window", "start": "22:00", "end": "01:00", "end_next_day": True,
                  "segments_min": [200]}
        said = document(window, "From 22:00 to 01:00, 200 minutes of talks.")
        self.assertEqual(record.stated_checks(said, "The plan runs 20 minutes over the end."), {"W"})
        self.assertEqual(record.stated_checks(said, "The plan runs 40 minutes over the end."), set())
        self.assertEqual(record.stated_checks(said, "It ends at 01:20, past the 01:00 end."), {"W"})

    def test_only_what_is_over_must_be_told(self):
        # The total exactly at the cap is not over it: telling the two items is enough.
        at_cap = budget([300, 300], total_cap=600, item_cap=250)
        said = document(at_cap, "Budget 600, no item over 250. Venue 300, food 300.")
        self.assertEqual(len(record._conflict_ways(at_cap)), 2)
        self.assertEqual(record.stated_checks(said, "The venue at $300 is $50 over the $250 item cap, and so is food at $300."),
                         {"B"})
        # An item exactly at the item cap is not over it: telling the total and the other item is enough.
        item_at_cap = budget([250, 400], total_cap=600, item_cap=250)
        said = document(item_at_cap, "Budget 600, no item over 250. Venue 250, food 400.")
        self.assertEqual(len(record._conflict_ways(item_at_cap)), 2)
        self.assertEqual(record.stated_checks(
            said, "The total of $650 is over the $600 budget, and food at $400 is $150 over the $250 item cap."), {"B"})


if __name__ == "__main__":
    unittest.main()
