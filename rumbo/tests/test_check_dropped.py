"""A check about an option the user dropped names that decision in dropped_by.

`replaces` retires a check when a newer check of the same kind takes over. A
decision that drops an option can leave nothing of that kind to check: in a
live session on 0.3.12 the user went with the maker-space team instead of Dr.
Okafor, and the check on Dr. Okafor's payment deadline had no successor. Its
date now came only from a replaced item, so every hook reported it as the
agent's own assumption. dropped_by retires such a check while the decision
stands, and refuses a decision that would hide a conflict still in force.
"""
import copy
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

OBJECTIVE = "Plan the data workshop. It's the morning of March 12 and we've budgeted $600 total."
OKAFOR = "Dr. Okafor says the foundation must approve his slides by March 20."
PRINTER = "The printer needs the handout files by March 1."
CHOICE = "I think we should go with just the maker-space team for this workshop."
SAID = [OBJECTIVE, OKAFOR, PRINTER, CHOICE]


def item(item_id, quote, status="commitment", **extra):
    return dict({"id": item_id, "text": quote, "quote": quote, "status": status}, **extra)


def document(checks, items=None):
    items = items if items is not None else [
        item("I1", "It's the morning of March 12"),
        item("I2", OKAFOR, "uncertain"),
        item("I3", CHOICE, replaces=["I2"]),
        item("I4", PRINTER),
    ]
    return {"version": 1, "objective": {"text": "Data workshop", "quote": OBJECTIVE}, "items": items,
            "checks": checks}


# Dr. Okafor's slides would be approved after the workshop: a conflict while he
# was an option, moot once the user went without him.
SLIDES = {"id": "C1", "kind": "before", "label": "Dr. Okafor's slide approval before the workshop",
          "first": "03-20", "second": "03-12", "refs": ["I1", "I2"]}
DROPPED = dict(SLIDES, dropped_by="I3")


class DroppedValidationTests(unittest.TestCase):
    def faults(self, checks, items=None):
        return record.validate_record(document(checks, items))

    def test_a_decision_that_replaced_the_checks_option_drops_it(self):
        self.assertEqual(self.faults([DROPPED]), [])
        self.assertEqual(self.faults([dict(SLIDES, dropped_by=None)]), [])
        rejection = document([])["items"]
        rejection[2] = item("I3", "No, let's not use Dr. Okafor.", "rejected", replaces=["I2"])
        self.assertEqual(self.faults([DROPPED], rejection), [])

    def test_the_decision_must_be_an_item(self):
        for dropped_by in ("I9", "", 3, ["I3"], {"id": "I3"}):
            with self.subTest(dropped_by=dropped_by):
                self.assertEqual(self.faults([dict(SLIDES, dropped_by=dropped_by)]), [
                    "checks[0].dropped_by: RECORD_BAD_REF: name the id of the item that records the user's decision"])

    def test_the_check_must_name_its_items(self):
        for refs in (None, []):
            with self.subTest(refs=refs):
                self.assertEqual(self.faults([dict(DROPPED, refs=refs)]), [
                    "checks[0].dropped_by: RECORD_BAD_REF: list this check's items in refs; the decision must "
                    "replace one of them"])

    def test_the_decision_must_replace_one_of_the_checks_items(self):
        self.assertEqual(self.faults([dict(DROPPED, dropped_by="I4")]), [
            "checks[0].dropped_by: RECORD_BAD_REF: I4 does not replace any of this check's refs; record the "
            "decision as an item that replaces the dropped option's items"])
        # The decision names the check's item itself, not only a newer version
        # of it: following chains of items for every dropped check made a long
        # chain slow to validate, and every hook validates the record.
        items = document([])["items"]
        items[2] = item("I3", CHOICE, replaces=["I5"])
        items.append(item("I5", OKAFOR, "uncertain", replaces=["I2"]))
        self.assertIn("I3 does not replace any of this check's refs", self.faults([DROPPED], items)[0])
        items[2] = item("I3", CHOICE, replaces=["I5", "I2"])
        self.assertEqual(self.faults([DROPPED], items), [])

    def test_many_dropped_checks_stay_quick_to_validate(self):
        import time
        items = [item("I1", "It's the morning of March 12")]
        checks = []
        for i in range(2, 1002, 2):
            items.append(item("I%d" % i, OKAFOR, "uncertain", replaces=["I%d" % (i - 2)] if i > 2 else []))
            items.append(item("I%d" % (i + 1), CHOICE, replaces=["I%d" % i]))
            checks.append(dict(SLIDES, id="C%d" % i, refs=["I1", "I%d" % i], dropped_by="I%d" % (i + 1)))
        started = time.monotonic()
        faults = record.validate_record(document(checks, items))
        self.assertEqual(faults, [])
        self.assertLess(time.monotonic() - started, 3)

    def test_only_a_commitment_or_a_rejection_drops_an_option(self):
        for status in ("draft", "preference", "deferred", "uncertain", "done"):
            with self.subTest(status=status):
                items = document([])["items"]
                items[2] = dict(items[2], status=status)
                self.assertEqual(self.faults([DROPPED], items), [
                    "checks[0].dropped_by: RECORD_BAD_REF: I3 has status %s; only a commitment or a rejection "
                    "drops an option" % status])

    def test_a_decision_the_user_has_since_changed_no_longer_drops_it(self):
        items = document([])["items"] + [item("I6", OKAFOR, replaces=["I3"])]
        self.assertEqual(self.faults([DROPPED], items), [
            "checks[0].dropped_by: RECORD_BAD_REF: I3 is replaced by I6, so it may no longer drop this option; "
            "name the decision in force, or remove dropped_by"])

    def test_a_decision_that_names_a_value_may_update_the_check(self):
        items = document([])["items"]
        items[2] = item("I3", "Dr. Okafor's slides are now due March 5.", replaces=["I2"])
        self.assertEqual(self.faults([DROPPED], items), [
            'checks[0].dropped_by: RECORD_BAD_REF: I3\'s words name a value ("March 5"), so the decision may '
            "update the check rather than drop it: if the user gave a new value, write a check with it that lists "
            "C1 in replaces; if they only dropped the option, change I3's quote to just their words that drop it"])
        # A value the check already has counts too; the words that drop the option do not name it.
        items[2] = item("I3", "Let's go with the maker-space team for the March 12 workshop.", replaces=["I2"])
        self.assertEqual(len(self.faults([DROPPED], items)), 1)
        items[2] = item("I3", "Let's go with the maker-space team", replaces=["I2"])
        self.assertEqual(self.faults([DROPPED], items), [])

    def test_any_value_of_the_checks_kind_counts(self):
        # Review of this change: comparing a decision's values with the check's
        # missed forms the source check reads, such as a year ("March 20, 2027"
        # against 2026-03-20), "03-25", "two hundred fifty dollars" read as
        # fifty, "three-quarter hour" and the end of "March 20-25".
        dated = dict(DROPPED, first="2026-03-20", second="2026-03-12")
        schedule = {"id": "C1", "kind": "fits_window", "start": "10:15", "end": "12:30", "segments_min": [60],
                    "refs": ["I1", "I2"], "dropped_by": "I3"}
        budget = {"id": "C1", "kind": "within_budget", "amounts": [50], "total_cap": 600, "refs": ["I1", "I2"],
                  "dropped_by": "I3"}
        options = {"before": "Dr. Okafor says the foundation must approve his slides by March 20, 2026.",
                   "fits_window": "Dr. Okafor arrives at 10:15 and can do 60 minutes.",
                   "within_budget": "Dr. Okafor charges $50 for travel."}
        cases = [
            (dated, "Dr. Okafor now needs slide approval by March 20, 2027.", "March 20, 2027"),
            (DROPPED, "Dr. Okafor's slides are now due 03-25.", "03-25"),
            (DROPPED, "Dr. Okafor's slides are now due 3/25/2027.", "3/25/2027"),
            (DROPPED, "Dr. Okafor's slide approval window is now March 20\u201325.", "March 20\u201325"),
            (DROPPED, "Dr. Okafor can do it on Friday instead.", "Friday instead"),
            (DROPPED, CHOICE, None),
            (DROPPED, "We may go with the maker-space one instead.", None),
            (DROPPED, "Go with the maker-space team; they're free.", None),
            (schedule, "Dr. Okafor can now do three-quarter hour.", "three-quarter hour"),
            (schedule, "Go with the maker-space team for a 2h30 session.", "2h30 session"),
            (schedule, "Go with the maker-space team; it can stay till noon.", "noon"),
            (schedule, "Go with the maker-space team at 9:45.", "9:45"),
            (schedule, CHOICE, None),
            (budget, "Dr. Okafor now charges two hundred fifty dollars.", "two hundred fifty"),
            (budget, "Go with the maker-space team; they cost $200.", "$200"),
            (budget, "Go with the maker-space team, they're free.", "free"),
            (budget, "Go with the maker-space team, they need 2 tables.", "2 tables"),
            (budget, "Go with the maker-space one.", None),
        ]
        for check, decision, named in cases:
            with self.subTest(kind=check["kind"], decision=decision):
                items = [item("I1", OBJECTIVE), item("I2", options[check["kind"]], "uncertain"),
                         item("I3", decision, replaces=["I2"])]
                faults = self.faults([check], items)
                if named is None:
                    self.assertEqual(faults, [])
                else:
                    self.assertEqual(len(faults), 1, faults)
                    self.assertIn("I3's words name a value (%s)" % json.dumps(named, ensure_ascii=False), faults[0])

    def test_a_check_whose_values_all_stay_in_force_is_still_about_the_plan(self):
        # The printer deadline also names I2, but none of its values came from it.
        printer = {"id": "C2", "kind": "before", "label": "handouts before the workshop", "first": "03-01",
                   "second": "03-12", "refs": ["I1", "I2", "I4"], "dropped_by": "I3"}
        self.assertEqual(self.faults([printer]), [
            "checks[0].dropped_by: RECORD_BAD_REF: no value of this check comes only from the items I3 "
            "replaced, so it is still about the current plan: resolve it or tell the user, and remove dropped_by"])

    def test_values_are_read_only_once_the_rest_of_the_record_is_valid(self):
        items = document([])["items"]
        items[3] = dict(items[3], status="decided")
        faults = self.faults([dict(SLIDES, dropped_by="I3", first="2026-13-40")], items)
        self.assertTrue(faults)
        self.assertFalse([fault for fault in faults if "dropped_by" in fault], faults)


class DroppedCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "project")
        os.makedirs(os.path.join(self.project, ".rumbo"))
        self.record = os.path.join(self.project, ".rumbo", "record.json")
        self.env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(self.tmp.name, "state"))
        self.transcript = os.path.join(self.tmp.name, "t.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            for text in SAID:
                handle.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                         "message": {"role": "user", "content": text}}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, checks, items=None):
        with open(self.record, "w", encoding="utf-8") as handle:
            json.dump(document(checks, items), handle)

    def run_record(self, args, payload=""):
        proc = subprocess.run([sys.executable, SCRIPT] + args + ["--record", self.record], input=payload,
                              text=True, capture_output=True, env=self.env, timeout=10)
        return proc.returncode, proc.stdout, proc.stderr

    def stop(self, session="s1"):
        code, out, err = self.run_record(["stop-gate"], json.dumps(
            {"session_id": session, "transcript_path": self.transcript, "last_assistant_message": "Plan attached."}))
        self.assertEqual((code, err), (0, ""))
        return json.loads(out)["reason"] if out.strip() else None

    def test_check_lists_a_dropped_check_as_history_and_does_not_fail_on_it(self):
        self.write([DROPPED])
        code, out, err = self.run_record(["check"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(),
                         ["C1: DROPPED before Dr. Okafor's slide approval before the workshop by I3"])

    def test_without_dropped_by_the_check_reads_as_an_assumption(self):
        # The live failure: the date came from a replaced item, so it read as unsourced.
        self.write([SLIDES])
        code, out, _err = self.run_record(["check"])
        self.assertEqual(code, 1)
        self.assertIn("(also unsourced: first month-day 03-20)", out)

    def test_show_and_pre_write_leave_out_a_dropped_check(self):
        self.write([DROPPED])
        self.assertNotIn("Open problems", self.run_record(["show"])[1])
        payload = json.dumps({"session_id": "w1", "tool_input": {"file_path": os.path.join(self.project, "plan.md")}})
        self.assertEqual(self.run_record(["pre-write"], payload)[1], "")

    def test_dropping_a_failing_check_ends_its_block_without_a_removal_report(self):
        items = document([])["items"]
        before_choice = [items[0], dict(items[1]), items[3]]
        self.write([SLIDES], before_choice)
        self.assertIn("C1: FAIL before", self.stop())
        self.write([DROPPED])
        self.assertIsNone(self.stop())

    def test_changing_the_decision_brings_the_check_back(self):
        self.write([DROPPED])
        self.assertIsNone(self.stop())
        items = document([])["items"] + [item("I6", OKAFOR, replaces=["I3"])]
        self.write([DROPPED], items)
        reason = self.stop()
        self.assertIn("I3 is replaced by I6, so it may no longer drop this option", reason)

    def test_deleting_a_failing_check_instead_of_dropping_it_is_still_reported(self):
        items = document([])["items"]
        self.write([SLIDES], [items[0], items[1], items[3]])
        self.assertIsNotNone(self.stop())
        # The decision is recorded, but the check is deleted rather than dropped.
        self.write([])
        self.assertIn("C1: check was failing and has been removed from the record", self.stop())

    def session(self, session_id, *texts):
        """Run the Stop gate for a session whose transcript holds texts."""
        transcript = os.path.join(self.tmp.name, "%s.jsonl" % session_id)
        with open(transcript, "w", encoding="utf-8") as handle:
            for text in texts:
                handle.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                         "message": {"role": "user", "content": text}}) + "\n")
        code, out, err = self.run_record(["stop-gate"], json.dumps(
            {"session_id": session_id, "transcript_path": transcript, "last_assistant_message": "Done."}))
        self.assertEqual((code, err), (0, ""))
        return json.loads(out)["reason"] if out.strip() else None

    def test_a_rejection_that_drops_a_check_is_reopened_when_a_later_session_takes_it_back(self):
        # Review of this change: an earlier session's rejection kept the check
        # dropped after the user took it back, because only approvals were
        # checked for a retraction.
        rejection = "No, let's not use Dr. Okafor."
        items = document([])["items"]
        items[2] = item("I3", rejection, "rejected", replaces=["I2"])
        self.write([DROPPED], items)
        self.assertIsNone(self.session("s1", *(SAID[:3] + [rejection])))
        self.assertIsNone(self.session("s2", "Now draft the invitation."))
        reason = self.session("s3", "I've changed my mind: use Dr. Okafor instead.")
        self.assertIn("items[2].quote: EARLIER_APPROVAL: decided in an earlier session, and it drops a check", reason)
        self.assertIn("I've changed my mind: use Dr. Okafor instead.", reason)

    def test_an_earlier_approval_turned_into_a_rejection_cannot_drop_a_check_by_itself(self):
        # The words were recorded for a commitment; dropping a check as a
        # rejection needs words recorded for that, in this session or earlier.
        items = document([])["items"]
        self.write([SLIDES], [items[0], items[1], item("I3", CHOICE), items[3]])
        self.assertIsNotNone(self.session("s1", *SAID))
        items[2] = item("I3", CHOICE, "rejected", replaces=["I2"])
        self.write([DROPPED], items)
        reason = self.session("s2", "Now draft the invitation.")
        self.assertIn("items[2].quote: UNVERIFIED", reason)
        # Said again in this session, the words verify the rejection.
        self.assertIsNone(self.session("s3", CHOICE))

    def test_the_live_session_record_drops_its_payment_deadline(self):
        # The record from the live session, reduced to the dropped deadline.
        items = [item("I1", "It's the morning of March 12."),
                 item("I14", "Dr. Okafor replied: he can't lower his travel costs below $220, and he can only "
                             "do a 60-minute session. He'd need to be paid by April 1.", "uncertain"),
                 item("I16", CHOICE, replaces=["I14"])]
        deadline = {"id": "C8", "kind": "before", "label": "workshop date before Dr. Okafor's payment deadline",
                    "first": "03-12", "second": "04-01", "refs": ["I1", "I14"]}
        self.write([deadline], items)
        self.assertIn("C8: UNSOURCED before", self.run_record(["check"])[1])
        self.write([dict(deadline, dropped_by="I16")], items)
        code, out, _err = self.run_record(["check"])
        self.assertEqual((code, out.strip()),
                         (0, "C8: DROPPED before workshop date before Dr. Okafor's payment deadline by I16"))


class DroppedFuzzTests(unittest.TestCase):
    def test_random_decisions_on_valid_records_follow_the_rule(self):
        # The hook fuzz test rarely writes a valid record, so it never reaches
        # the value rule. Seeded, so a failure reproduces.
        import random
        import time
        rng = random.Random(20261124)
        plain = ["I think we should go with just the maker-space team", "No, let's not use Dr. Okafor",
                 "Let's go with the other option instead", "We may go with the maker-space one",
                 "Drop Dr. Okafor from the plan", "Go with the team that one of them leads"]
        every = {"before", "fits_window", "within_budget"}
        # Each phrase with the kinds of check for which it names a value.
        valued = [("by March 25", every), ("at 9:45", every), ("for $200", every), ("on 03-25", every),
                  ("2 tables", every), ("two hundred dollars", every), ("for three-quarter hour", every),
                  ("March 20\u201325", every), ("1e3", every), ("until noon", {"fits_window"}),
                  ("on Friday", {"before"}), ("it's free", {"within_budget"})]
        noise = [", ", " and ", "; ", " \u2014 ", "\u00a0", " (really) ", "\u2019s", "\U0001F600"]
        checks = {
            "before": dict(SLIDES, dropped_by="I3"),
            "fits_window": {"id": "C1", "kind": "fits_window", "start": "10:15", "end": "12:30",
                            "segments_min": [60], "refs": ["I1", "I2"], "dropped_by": "I3"},
            "within_budget": {"id": "C1", "kind": "within_budget", "amounts": [350], "total_cap": 600,
                              "refs": ["I1", "I2"], "dropped_by": "I3"},
        }
        options = {"before": OKAFOR, "fits_window": "Dr. Okafor arrives at 10:15 and can do 60 minutes.",
                   "within_budget": "Dr. Okafor needs $350 for travel."}
        started = time.monotonic()
        for case in range(600):
            kind = rng.choice(sorted(checks))
            parts, names_value = [rng.choice(plain)], False
            for _ in range(rng.randint(0, 3)):
                parts.append(rng.choice(noise))
                phrase, kinds = rng.choice(valued + [(text, set()) for text in plain])
                parts.append(phrase)
                names_value = names_value or kind in kinds
            decision = "".join(parts) + rng.choice([".", "!", "", "..."])
            items = [item("I1", OBJECTIVE), item("I2", options[kind], "uncertain"),
                     item("I3", decision, rng.choice(["commitment", "rejected"]), replaces=["I2"])]
            with self.subTest(case=case, kind=kind, decision=decision):
                faults = record.validate_record(document([dict(checks[kind])], items))
                if names_value:
                    self.assertEqual(len(faults), 1, faults)
                    self.assertIn("words name a value", faults[0])
                else:
                    self.assertEqual(faults, [])
        self.assertLess(time.monotonic() - started, 5)

    def test_validation_never_crashes_on_odd_dropped_by_records(self):
        base = document([DROPPED])
        oddities = [None, 0, "I3", "I2", "I1", "", [], {}, ["I3"], float("nan")]
        for value in oddities:
            for target in ("dropped_by", "refs", "replaces", "status", "quote"):
                doc = copy.deepcopy(base)
                if target in ("dropped_by", "refs"):
                    doc["checks"][0][target] = value
                else:
                    doc["items"][2][target] = value
                with self.subTest(target=target, value=value):
                    self.assertIsInstance(record.validate_record(doc), list)


if __name__ == "__main__":
    unittest.main()
