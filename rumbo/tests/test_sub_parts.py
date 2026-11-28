"""Level 2 of the part-by-part pass: each part's sub-parts, on the branches no other test ran.

A coverage run of the suite on 0.3.28 listed the lines and branches its tests never
reached. These tests reach them through the commands and readers the hooks use, and
pin the reader changes 0.3.29 made where a sub-part read the user's words wrongly.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record.py"
SPEC = importlib.util.spec_from_file_location("sub_parts_record", SCRIPT)
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)


def budget(amounts, total_cap=600):
    return {"id": "B", "kind": "within_budget", "amounts": amounts, "total_cap": total_cap}


def unsourced(check, said):
    document = {"version": 1, "objective": {"text": "Plan", "quote": said}, "items": [], "checks": [check]}
    return record.unsourced_values(document, check)


def run_cli(*args, payload=None, env=None, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input="" if payload is None else payload,
                          capture_output=True, text=True, env=env, cwd=cwd, timeout=20)


class ZeroFactorTests(unittest.TestCase):
    """Readers: a zero price or a zero count in a {unit, quantity} amount."""

    def test_a_zero_price_needs_free_or_zero_money_beside_its_quantity(self):
        free = [{"unit": 0, "quantity": 12}]
        for said in ("Breakfast is free for 12 attendees.", "Breakfast is $0 for 12 attendees.",
                     "Zero dollars each for the 12 volunteers.", "The 12 volunteers eat at no charge.",
                     "It's free for twelve guests.", "Parking is rent-free for 12 cars.",
                     "Parking is free for 12 cars, but not free for buses."):
            with self.subTest(said=said):
                self.assertEqual(unsourced(budget(free), "Budget $600. " + said), [])
        for said in ("Breakfast is not free for 12 attendees.", "Breakfast is free. We have 12 attendees.",
                     "Parking isn't free, but 12 cars fit."):
            with self.subTest(said=said):
                self.assertEqual(unsourced(budget(free), "Budget $600. " + said), ["amounts unit 0"])

    def test_free_of_something_else_is_no_zero_price(self):
        # "sugar-free snacks" are snacks without sugar, not snacks at no cost.
        for said in ("Sugar-free snacks for 12 kids.", "Hands-free mics for 12 speakers.", "A gluten-free lunch for 12."):
            with self.subTest(said=said):
                self.assertEqual(unsourced(budget([{"unit": 0, "quantity": 12}]), "Budget $600. " + said),
                                 ["amounts unit 0"])
        for said in ("A cost-free room for 12.", "Fee-free entry for 12 guests."):
            with self.subTest(said=said):
                self.assertEqual(unsourced(budget([{"unit": 0, "quantity": 12}]), "Budget $600. " + said), [])

    def test_a_zero_count_needs_a_rate_for_the_same_unit(self):
        none_sold = [{"unit": 25, "quantity": 0}]
        for said in ("Tickets $25 per seat. No seats sold.", "Tickets $25 a seat. No seats sold.",
                     "Tickets $25/seat. No seats sold.", "Tickets are 25 dollars an attendee. Zero attendees so far.",
                     "Tickets $25 per person. No people yet.", "Tickets $25 per party. No parties yet.",
                     "Tickets $25 per seat. 0 seats sold."):
            with self.subTest(said=said):
                self.assertEqual(unsourced(budget(none_sold), "Budget $600. " + said), [])
        for said in ("Tickets $25 per seat. No tables sold.", "Tickets $25 per seat; we have not sold no seats.",
                     "Tickets $30 per seat. No seats sold."):
            with self.subTest(said=said):
                self.assertIn("amounts quantity 0", unsourced(budget(none_sold), "Budget $600. " + said))

    def test_count_stems(self):
        for word, singular in (("people", "person"), ("parties", "party"), ("seats", "seat"), ("class", "class"),
                               ("Attendees", "attendee"), ("cookies", "cookie"), ("classes", "class"), ("boxes", "box"),
                               ("pies", "pie"), ("buses", "bus")):
            with self.subTest(word=word):
                self.assertIn(singular, record._count_stems(word))
                self.assertTrue(record._count_stems(word) & record._count_stems(singular))


class ClockTimeTests(unittest.TestCase):
    """Readers: clock times, with a dot before the minutes and at the start of a range."""

    def test_a_dot_time_with_am_or_pm(self):
        for said, time, sourced in (("Doors 9.30pm.", "21:30", True), ("Doors 9.30 p.m.", "21:30", True),
                                    ("Doors 12.15am.", "00:15", True), ("Doors 9.30pm.", "09:30", False),
                                    ("Doors 9.30.", "09:30", False), ("Tickets $9.30pm.", "21:30", False),
                                    ("Doors 13.30pm.", "13:30", False)):
            with self.subTest(said=said, time=time):
                self.assertEqual(record._is_time_sourced(time, said), sourced)

    def test_the_start_of_a_range_shares_the_end_s_am_or_pm(self):
        for said, time, sourced in (("The workshop runs 2-4pm.", "14:00", True), ("The workshop runs 2-4pm.", "02:00", False),
                                    ("Runs 2 - 4 pm.", "14:00", True), ("Runs 2–4 p.m.", "14:00", True),
                                    ("Runs 9 to 11am.", "09:00", True), ("Runs 9 to 11am.", "21:00", False),
                                    ("Runs 11-1pm.", "11:00", True), ("Runs 8-1am.", "20:00", True),
                                    ("Runs 12-2pm.", "12:00", True), ("Runs from 9 until 5pm.", "09:00", True),
                                    ("Runs 2-4.30pm.", "14:00", True), ("Runs 2-13pm.", "14:00", False),
                                    ("Runs 0-2pm.", "12:00", False)):
            with self.subTest(said=said, time=time):
                self.assertEqual(record._is_time_sourced(time, said), sourced)

    def test_a_range_s_end_is_read_as_the_time_reader_reads_it_alone(self):
        # Codex review on 0.3.29: the end "4:00:00pm" lost its pm after the seconds, so
        # the start read in both halves and an invented 02:00 passed.
        for said, time, sourced in (("Ours 2-4:00:00pm.", "02:00", False), ("Ours 2-4:00:00pm.", "14:00", True),
                                    ("Ours 2-4:00:30pm.", "14:00", False), ("Ours 9-10:00:00.", "09:00", True),
                                    ("Ours 9-10:00:00.", "21:00", False), ("Ours 2-4\npm.", "14:00", True),
                                    ("Ours 2-4\npm.", "16:00", True)):
            with self.subTest(said=said, time=time):
                self.assertEqual(record._is_time_sourced(time, said), sourced)
        window = {"id": "W", "kind": "fits_window", "start": "02:00", "end": "16:00", "segments_min": [120]}
        self.assertEqual(unsourced(window, "The room is ours 2-4:00:00pm for a 120-minute workshop."), ["start 02:00"])

    def test_the_reply_reader_finds_a_24_hour_range_start(self):
        # Codex review on 0.3.29: the reply reader's quick test looked only for the
        # 12-hour digits of a whole hour, so "14-16:30" did not state 14:00.
        line = "I propose 14-16:30; please confirm."
        self.assertTrue(record._is_time_sourced("14:00", line))
        self.assertTrue(record._says("time", "14:00", line))
        window = {"id": "W", "kind": "fits_window", "start": "14:00", "end": "16:30", "segments_min": [150]}
        document = {"version": 1, "objective": {"text": "Plan", "quote": "We need 150 minutes, ending 16:30."},
                    "items": [], "checks": [window]}
        self.assertEqual(record.stated_checks(document, line), {"W"})

    def test_a_range_start_without_am_or_pm_reads_like_a_time_without_them(self):
        for said, time, sourced in (("Runs 9-10:30.", "09:00", True), ("Runs 9-10:30.", "21:00", True),
                                    ("Runs 09-10:30.", "21:00", False), ("Runs 13-15:30.", "13:00", True),
                                    ("Runs 9-10:30 in the morning.", "21:00", False), ("Runs 24-25:30.", "00:00", False),
                                    ("Runs 9-10:75.", "09:00", False)):
            with self.subTest(said=said, time=time):
                self.assertEqual(record._is_time_sourced(time, said), sourced)

    def test_no_time_without_minutes_or_am_or_pm_on_the_end(self):
        for said, time in (("June 3-5", "03:00"), ("Shifts 9 to 5", "09:00"), ("Sizes 2-4", "02:00"), ("$2-4pm", "14:00")):
            with self.subTest(said=said):
                self.assertFalse(record._is_time_sourced(time, said))

    def test_a_window_check_and_the_reply_reader_read_ranges_the_same_way(self):
        window = {"id": "W", "kind": "fits_window", "start": "14:00", "end": "16:00", "segments_min": [120]}
        self.assertEqual(unsourced(window, "The room is ours 2-4pm for a 120-minute workshop."), [])
        self.assertTrue(record._says("time", "14:00", "It runs 2-4pm."))
        self.assertTrue(record._says("time", "21:30", "Doors open at 9.30pm."))
        self.assertFalse(record._says("time", "09:30", "Doors open at 9.30."))

    def test_a_clock_time_is_no_money_at_the_start_of_a_range_either(self):
        for said in ("The workshop runs 2-4pm.", "The workshop runs 2 to 4pm.", "The workshop runs 9-10:30."):
            with self.subTest(said=said):
                number = int(said.split()[3].split("-")[0])
                self.assertEqual(unsourced(budget([number]), "Budget $600. " + said), ["amounts %d" % number])
                self.assertEqual(unsourced(budget([{"unit": 30, "quantity": number}]), "Budget $600, $30 each. " + said), [])
        self.assertEqual(unsourced(budget([2]), "Budget $600. Sizes 2-4 fit."), [])
        self.assertEqual(unsourced(budget([2]), "Budget $600. Tickets $2-4pm only."), [])


class DateFormTests(unittest.TestCase):
    """Readers: dates in an ISO timestamp, with slashes after the year, and ranges in words."""

    def test_an_iso_timestamp_and_a_slashed_iso_date(self):
        for said, date, sourced in (("Starts 2026-03-20T10:00.", "03-20", True), ("Starts 2026-03-20t10:00.", "03-20", True),
                                    ("Starts 2026-03-20Tue.", "03-20", False), ("Starts 2026/03/20.", "03-20", True),
                                    ("Starts 2026/3/5.", "03-05", True), ("Starts 12026/03/20.", "03-20", False),
                                    ("Starts 2026/03/201.", "03-20", False)):
            with self.subTest(said=said):
                self.assertEqual(record._is_date_sourced(date, said)[0], sourced)
        self.assertEqual(record._is_date_sourced("2026-03-20", "Starts 2026-03-20T10:00."), (True, True))

    def test_a_range_in_words_sources_both_ends_and_never_the_days_between(self):
        for said, date, sourced in (("June 3 to 5", "06-03", True), ("June 3 to 5", "06-05", True),
                                    ("June 3 to 5", "06-04", False), ("June 3 through 5", "06-05", True),
                                    ("June 3 thru 5", "06-05", True), ("June 3 until 5", "06-05", True),
                                    ("June 30 to 2 July", "07-02", True), ("June 30 to 2 July", "06-02", False),
                                    ("June 30 to 2 July", "07-30", False), ("3 to 5 July", "07-03", True),
                                    ("June 3 to 5 July", "07-03", False), ("June 3 to 50", "06-05", False)):
            with self.subTest(said=said, date=date):
                self.assertEqual(record._is_date_sourced(date, said)[0], sourced)


class RecordDigitsTests(unittest.TestCase):
    """Validation and readers: a record's clock time is read the same way by both."""

    def test_the_time_reader_takes_the_digits_validation_takes(self):
        # Validation takes decimal digits of any script ("٠٩:٣٠" is 09:30, see
        # test_time_boundaries), and the reader reads them by value. "²" is a digit
        # but no decimal one: int() cannot read it, and the reader raised on it.
        self.assertEqual(record.parse_time("١٢:٠٠"), 720)
        self.assertTrue(record._is_time_sourced("١٢:٠٠", "Starts 12:00"))
        for value in ("²:00", "00:²²", "❶❷:00"):
            with self.subTest(value=value):
                self.assertIsNone(record.parse_time(value))
                self.assertFalse(record._is_time_sourced(value, "Starts 12:00"))
                self.assertFalse(record._says("time", value, "Starts 12:00"))


class OutcomeLedgerTests(unittest.TestCase):
    """Outcomes: each rule of the ledger, its report and its handoff."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rumbo sub parts ")
        self.addCleanup(self.temp.cleanup)
        self.project = os.path.join(self.temp.name, "project")
        os.makedirs(os.path.join(self.project, ".rumbo"))
        self.record_path = os.path.join(self.project, ".rumbo", "record.json")
        self.env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(self.temp.name, "state"))
        self.report = os.path.join(self.project, "report.txt")
        with open(self.report, "w", encoding="utf-8") as handle:
            handle.write("report\n")
        with open(self.report, "rb") as handle:
            self.report_sha = hashlib.sha256(handle.read()).hexdigest()

    def document(self, outcomes, **extra):
        document = {"version": 1, "objective": {"text": "Ship the report", "quote": "Ship the report."},
                    "target": "the report in this project", "items": [], "checks": [], "outcomes": outcomes}
        document.update(extra)
        return document

    def row(self, number, status="verified", **fields):
        row = {"id": "O%d" % number, "text": "Outcome %d" % number, "owner": "worker", "acceptance": "it is done",
               "status": status}
        row.update({"verified": {"evidence": "read it back"}, "runnable": {"next_action": "do it"},
                    "blocked": {"blocker": "waiting on the owner", "restart_trigger": "the owner answers"}}.get(status, {}))
        row.update(fields)
        return row

    def write(self, document):
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

    def test_each_ledger_rule_names_its_field(self):
        good = self.row(1)
        cases = [
            (self.document([good], target=" "), "target: RECORD_MISSING_FIELD"),
            (self.document({"O1": good}), "outcomes: RECORD_MISSING_FIELD: outcomes must be a nonempty list"),
            (self.document([]), "outcomes: RECORD_EMPTY_FIELD"),
            (self.document(["O1"]), "outcomes[0]: RECORD_MISSING_FIELD: each outcome must be an object"),
            (self.document([dict(good, id=" ")]), "outcomes[0].id: RECORD_MISSING_FIELD"),
            (self.document([good, dict(good)]), "outcomes[1].id: RECORD_DUP_ID"),
            (self.document([dict(good, owner="")]), "outcomes[0].owner: RECORD_MISSING_FIELD"),
            (self.document([dict(good, status="done")]), "outcomes[0].status: RECORD_BAD_STATUS: use one of runnable, blocked, verified"),
            (self.document([dict(self.row(1, "runnable"), next_action=None)]), "outcomes[0].next_action: RECORD_MISSING_FIELD"),
            (self.document([dict(self.row(1, "blocked"), restart_trigger="")]),
             "outcomes[0].restart_trigger: RECORD_MISSING_FIELD: blocked work needs a specific restart trigger"),
            (self.document([dict(good, evidence=" ")]), "outcomes[0].evidence: RECORD_MISSING_FIELD: verified work needs exact evidence"),
            (self.document([dict(self.row(1, "runnable"), evidence=["log"])]),
             "outcomes[0].evidence: RECORD_MISSING_FIELD: evidence must be a string"),
            (self.document([dict(good, artifacts=[])]), "outcomes[0].artifacts: RECORD_EMPTY_FIELD"),
            (self.document([dict(good, artifacts="report.txt")]), "outcomes[0].artifacts: RECORD_EMPTY_FIELD"),
            (self.document([dict(good, artifacts=["report.txt"])]),
             "outcomes[0].artifacts[0]: RECORD_MISSING_FIELD: each artifact must be an object"),
            (self.document([dict(good, artifacts=[{"path": "/etc/hosts", "sha256": self.report_sha}])]),
             "outcomes[0].artifacts[0].path: RECORD_BAD_PATH"),
            (self.document([dict(good, artifacts=[{"path": ".", "sha256": self.report_sha}])]),
             "outcomes[0].artifacts[0].path: RECORD_BAD_PATH"),
            (self.document([dict(good, artifacts=[{"path": "report.txt", "sha256": self.report_sha.upper()}])]),
             "outcomes[0].artifacts[0].sha256: RECORD_BAD_VALUE"),
        ]
        for document, fault in cases:
            with self.subTest(fault=fault):
                faults = record.validate_record(document)
                self.assertTrue(any(line.startswith(fault) for line in faults), faults)
        self.assertEqual(record.validate_record(self.document([good])), [])

    def test_show_names_the_recorded_handoff_status(self):
        for rows, status in (([self.row(1), self.row(2, "blocked")], "BOUNDED"), ([self.row(1)], "COMPLETE"),
                             ([self.row(1, "runnable"), self.row(2, "blocked")], "CONTINUE")):
            with self.subTest(status=status):
                self.write(self.document(rows))
                result = run_cli("show", "--record", self.record_path, env=self.env)
                self.assertIn("Handoff (recorded status; run handoff to verify artifact hashes): %s" % status, result.stdout)
        self.write(self.document([self.row(1, "blocked")]))
        self.assertIn("OUTCOME O1 [blocked] owner worker: Outcome 1 -> waiting on the owner",
                      run_cli("show", "--record", self.record_path, env=self.env).stdout)

    def test_show_lists_eight_outcomes_then_counts_the_rest(self):
        self.write(self.document([self.row(number) for number in range(1, 12)]))
        result = run_cli("show", "--record", self.record_path, "--max-chars", "5000", env=self.env)
        self.assertIn("OUTCOME O8 [verified]", result.stdout)
        self.assertNotIn("OUTCOME O9 ", result.stdout)
        self.assertIn("... and 3 more outcomes", result.stdout)

    def test_each_artifact_state(self):
        os.mkdir(os.path.join(self.project, "folder"))
        outside = os.path.join(self.temp.name, "outside.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("report\n")
        os.symlink(outside, os.path.join(self.project, "link.txt"))
        states = {}
        for path in ("report.txt", "missing.txt", "folder", "link.txt"):
            observation = record._artifact_observation(self.project, {"path": path, "sha256": self.report_sha})
            states[path] = observation["state"]
        self.assertEqual(states, {"report.txt": "current", "missing.txt": "missing", "folder": "unreadable",
                                  "link.txt": "outside_root"})
        large = record._artifact_observation(self.project, {"path": "report.txt", "sha256": self.report_sha}, max_bytes=3)
        self.assertEqual((large["state"], large["size"]), ("too_large_for_hook", 7))
        stale = record._artifact_observation(self.project, {"path": "report.txt", "sha256": "0" * 64})
        self.assertEqual((stale["state"], stale["observed_sha256"]), ("stale", self.report_sha))

    def test_a_verified_row_whose_evidence_is_gone_reopens_with_its_state(self):
        self.write(self.document([self.row(1, artifacts=[{"path": "folder", "sha256": self.report_sha}])]))
        os.mkdir(os.path.join(self.project, "folder"))
        result = run_cli("stop-gate", "--record", self.record_path, env=self.env,
                         payload=json.dumps({"session_id": "s1", "transcript_path": os.path.join(self.temp.name, "none.jsonl")}))
        self.assertIn("OUTCOME O1: STALE_EVIDENCE: folder unreadable -> owner worker; Re-establish current evidence for folder",
                      json.loads(result.stdout)["reason"])

    def test_handoff_refuses_what_it_cannot_read(self):
        self.write(self.document([self.row(1)]))
        missing_root = run_cli("handoff", "--record", self.record_path, "--root", os.path.join(self.temp.name, "nowhere"), env=self.env)
        self.assertEqual((missing_root.returncode, missing_root.stderr.strip()), (2, "PROJECT_ROOT_UNREADABLE"))
        missing_record = run_cli("handoff", "--record", os.path.join(self.temp.name, "none.json"), "--root", self.project,
                                 env=self.env)
        self.assertEqual((missing_record.returncode, missing_record.stderr.strip()), (2, "RECORD_NOT_FOUND"))
        complete = run_cli("handoff", "--record", self.record_path, "--root", self.project, env=self.env)
        self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
        self.assertEqual(json.loads(complete.stdout)["status"], "COMPLETE")

    def test_the_standard_record_belongs_to_its_own_project(self):
        self.write(self.document([self.row(1)]))
        other = os.path.join(self.temp.name, "other")
        os.mkdir(other)
        self.assertTrue(record._handoff_root_matches(self.record_path, self.project))
        self.assertFalse(record._handoff_root_matches(self.record_path, other))
        # A record at any other path is a detached export: the explicit root is taken.
        detached = os.path.join(self.temp.name, "export.json")
        self.assertTrue(record._handoff_root_matches(detached, other))
        # A path that differs from .rumbo/record.json only in case is that record when it
        # is the same file, and a separate custom record otherwise.
        variant = os.path.join(self.project, ".Rumbo", "Record.json")
        same_file = os.path.exists(variant)
        if not same_file:
            os.makedirs(os.path.dirname(variant))
            with open(variant, "w", encoding="utf-8") as handle:
                handle.write("{}")
        self.assertEqual(record._handoff_root_matches(variant, other), not same_file)
        lone = os.path.join(self.temp.name, "lone", ".RUMBO", "RECORD.JSON")
        self.assertTrue(record._handoff_root_matches(lone, other))


class StopGateStateTests(unittest.TestCase):
    """Hooks: the Stop gate's loop guard and its per-session state."""

    @unittest.skipUnless(hasattr(os, "openpty"), "needs a pseudo-terminal")
    def test_show_on_a_terminal_reads_no_hook_input(self):
        # Run by hand in a terminal, show must not wait for hook JSON on stdin.
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "record.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "objective": {"text": "Plan the day", "quote": "Plan the day."},
                           "items": [], "checks": []}, handle)
            leader, follower = os.openpty()
            try:
                result = subprocess.run([sys.executable, str(SCRIPT), "show", "--record", path], stdin=follower,
                                        capture_output=True, text=True, timeout=20)
            finally:
                os.close(leader)
                os.close(follower)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Objective: Plan the day", result.stdout)

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "needs root to give the directory away")
    def test_a_state_directory_another_user_owns_keeps_no_state(self):
        # Nothing is read from or written to it, so the nudge repeats and the Stop
        # gate, which cannot count the session's planning prompts, enforces nothing.
        with tempfile.TemporaryDirectory() as directory:
            state = os.path.join(directory, "state")
            os.mkdir(state, 0o700)
            os.chown(state, 54321, 54321)
            env = dict(os.environ, RUMBO_STATE_DIR=state)
            record_path = os.path.join(directory, "none", "record.json")
            prompt = json.dumps({"session_id": "s1", "prompt": "Plan the budget: $600 by March 20."})
            for _ in range(2):
                shown = run_cli("show", "--record", record_path, env=env, payload=prompt)
                self.assertIn("rumbo:", shown.stdout)
            self.assertEqual(os.listdir(state), [])
            stop = run_cli("stop-gate", "--record", record_path, env=env,
                           payload=json.dumps({"session_id": "s1", "transcript_path": "t.jsonl"}))
            self.assertEqual((stop.returncode, stop.stdout), (0, ""))

    def test_a_chained_stop_without_a_session_is_let_through(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "record.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(directory, "state"))
            unchained = run_cli("stop-gate", "--record", path, env=env, payload=json.dumps({"transcript_path": "t.jsonl"}))
            self.assertEqual(json.loads(unchained.stdout)["decision"], "block")
            chained = run_cli("stop-gate", "--record", path, env=env,
                              payload=json.dumps({"stop_hook_active": True, "transcript_path": "t.jsonl"}))
            self.assertEqual((chained.returncode, chained.stdout), (0, ""))

    def test_told_counts_read_each_check_once_and_ignore_a_bad_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_before = os.environ.get("RUMBO_STATE_DIR")
            os.environ["RUMBO_STATE_DIR"] = directory
            try:
                path = record._marker_path("s1", ".told")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("[1, 2]")
                self.assertEqual(record._read_told("s1"), {})
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump({"C1": ["start 09:00", 3], "C2": "end 10:00", "7": ["x"]}, handle)
                # Only lists of labels count, and only their strings.
                self.assertEqual(record._read_told("s1"), {"C1": ["start 09:00"], "7": ["x"]})
            finally:
                if env_before is None:
                    del os.environ["RUMBO_STATE_DIR"]
                else:
                    os.environ["RUMBO_STATE_DIR"] = env_before
        # A check that replaces two checks, one of which replaces the other, counts
        # each earlier check once.
        checks = [{"id": "C1"}, {"id": "C2", "replaces": ["C1"]}, {"id": "C3", "replaces": ["C1", "C2"]}]
        told = {"C1": ["start 09:00", "start 09:00"], "C2": ["start 09:00", "end 10:00"]}
        self.assertEqual(record._told_counts(told, {"checks": checks}, checks[2]), {"start 09:00": 2, "end 10:00": 1})


if __name__ == "__main__":
    unittest.main()
