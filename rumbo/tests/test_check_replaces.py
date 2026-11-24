"""A newer check can replace an obsolete one, as a newer item replaces an older item.

In live sessions on 0.3.11 the user's decisions made checks obsolete: an
option was dropped, or the user's own figures replaced an assumed budget.
Deleting such a check is reported by the Stop gate, so agents kept it and
reported it in every reply, or deleted it, were blocked, and restored it as
"(moot)". A replaced check stays in the record as history; the check that
replaces it is checked as usual.
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

SAID = "The budget is $600 total. Dr. Okafor's travel is $250, catering is $400, and the maker-space team is free."


def budget(check_id, amounts, **extra):
    return dict({"id": check_id, "kind": "within_budget", "amounts": amounts, "total_cap": 600, "refs": []}, **extra)


def document(*checks):
    return {"version": 1, "objective": {"text": "Workshop", "quote": SAID}, "items": [], "checks": list(checks)}


OKAFOR = budget("C1", [250, 400], label="budget with Dr. Okafor")
MAKER = budget("C2", [0, 400], label="budget with the maker-space team", replaces=["C1"])


class ReplacesValidationTests(unittest.TestCase):
    def faults(self, *checks):
        return record.validate_record(document(*checks))

    def test_a_check_replaces_other_checks_of_its_kind(self):
        self.assertEqual(self.faults(OKAFOR, MAKER), [])
        chain = budget("C3", [0, 300], replaces=["C2"])
        self.assertEqual(self.faults(OKAFOR, MAKER, chain), [])
        self.assertEqual(self.faults(dict(OKAFOR, replaces=[])), [])

    def test_unknown_own_and_non_string_ids_are_refused(self):
        for replaces in (["C9"], ["C2"], [1], [None]):
            with self.subTest(replaces=replaces):
                self.assertEqual(self.faults(OKAFOR, dict(MAKER, replaces=replaces)),
                                 ["checks[1].replaces[0]: RECORD_BAD_REF: replace the id of another check in checks"])
        self.assertEqual(self.faults(OKAFOR, dict(MAKER, replaces="C1")),
                         ["checks[1].replaces: RECORD_BAD_REF: replaces must be a list of check ids"])

    def test_a_check_of_another_kind_cannot_be_replaced(self):
        dates = {"id": "C3", "kind": "before", "first": "03-01", "second": "03-12", "refs": []}
        self.assertEqual(self.faults(OKAFOR, dates, dict(MAKER, replaces=["C3"])),
                         ["checks[2].replaces[0]: RECORD_BAD_REF: replace only a check of the same kind (within_budget)"])

    def test_a_cycle_is_refused(self):
        # Each check in a cycle would be replaced, so none would be checked.
        faults = self.faults(dict(OKAFOR, replaces=["C2"]), MAKER)
        self.assertEqual(faults, ["checks[0].replaces: RECORD_BAD_REF: replaces must not form a cycle",
                                  "checks[1].replaces: RECORD_BAD_REF: replaces must not form a cycle"])
        loop = [budget("A", [1], replaces=["B"]), budget("B", [1], replaces=["C"]), budget("C", [1], replaces=["A"])]
        self.assertEqual(len(self.faults(*loop)), 3)
        # A check that replaces a cycle member is not itself on the cycle.
        self.assertEqual(len(self.faults(*loop, budget("D", [1], replaces=["A"]))), 3)

    def test_an_id_that_is_not_a_string_is_reported_not_a_crash(self):
        # Review of this change: an unhashable id raised TypeError while the
        # kinds were collected, instead of the fault validate already reports.
        for bad_id in (["C1"], {"id": "C1"}, 7, None):
            with self.subTest(bad_id=bad_id):
                faults = self.faults(dict(OKAFOR, id=bad_id), MAKER)
                self.assertIn("checks[1].replaces[0]: RECORD_BAD_REF: replace the id of another check in checks", faults)
                self.assertTrue(any(fault.startswith("checks[0].id: RECORD_MISSING_FIELD") for fault in faults), faults)
        self.assertEqual(self.faults(dict(OKAFOR, id=["C1"]), dict(MAKER, replaces=[["C1"]]))[-1],
                         "checks[1].replaces[0]: RECORD_BAD_REF: replace the id of another check in checks")

    def test_a_long_chain_is_checked_in_linear_time(self):
        # Every hook validates the record. A search from each check took
        # seconds for a few thousand chained checks, against a 10 s timeout.
        import time
        chain = [budget("C%d" % i, [1], **({"replaces": ["C%d" % (i - 1)]} if i else {})) for i in range(20000)]
        started = time.monotonic()
        self.assertEqual(self.faults(*chain), [])
        chain[0]["replaces"] = ["C19999"]
        self.assertEqual(len(self.faults(*chain)), 20000)
        self.assertLess(time.monotonic() - started, 3)


class ReplacedCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "project")
        os.makedirs(os.path.join(self.project, ".rumbo"))
        self.record = os.path.join(self.project, ".rumbo", "record.json")
        self.env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(self.tmp.name, "state"))
        self.transcript = os.path.join(self.tmp.name, "t.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                     "message": {"role": "user", "content": SAID}}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *checks):
        with open(self.record, "w", encoding="utf-8") as handle:
            json.dump(document(*checks), handle)

    def run_record(self, args, payload=""):
        proc = subprocess.run([sys.executable, SCRIPT] + args + ["--record", self.record], input=payload,
                              text=True, capture_output=True, env=self.env, timeout=10)
        return proc.returncode, proc.stdout, proc.stderr

    def stop(self, session="s1"):
        code, out, err = self.run_record(["stop-gate"], json.dumps(
            {"session_id": session, "transcript_path": self.transcript, "last_assistant_message": "Plan attached."}))
        self.assertEqual((code, err), (0, ""))
        return json.loads(out)["reason"] if out.strip() else None

    def test_check_lists_a_replaced_check_as_history_and_does_not_fail_on_it(self):
        self.write(OKAFOR, MAKER)
        code, out, err = self.run_record(["check"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), ["C1: REPLACED within_budget budget with Dr. Okafor by C2",
                                            "C2: PASS within_budget budget with the maker-space team"])

    def test_the_replacing_check_is_still_checked(self):
        self.write(OKAFOR, budget("C2", [250, 400, 0], replaces=["C1"]))
        code, out, _err = self.run_record(["check"])
        self.assertEqual(code, 1)
        self.assertIn("C2: FAIL within_budget: total 650 exceeds total_cap 600 by 50", out)
        self.assertIn("C1: REPLACED within_budget budget with Dr. Okafor by C2", out)

    def test_only_the_newest_check_of_a_chain_is_in_force(self):
        self.write(OKAFOR, budget("C2", [250, 400], replaces=["C1"]), budget("C3", [0, 400], replaces=["C2"]))
        code, out, _err = self.run_record(["check"])
        self.assertEqual(code, 0, out)
        self.assertEqual([line.split(":")[1].split()[0] for line in out.splitlines()], ["REPLACED", "REPLACED", "PASS"])

    def test_show_and_pre_write_leave_out_a_replaced_check(self):
        self.write(OKAFOR, MAKER)
        code, out, _err = self.run_record(["show"])
        self.assertEqual(code, 0)
        self.assertNotIn("Open problems", out)
        payload = json.dumps({"session_id": "w1", "tool_input": {"file_path": os.path.join(self.project, "plan.md")}})
        self.assertEqual(self.run_record(["pre-write"], payload)[1], "")
        self.write(OKAFOR)
        self.assertIn("CONFLICT C1", self.run_record(["show"])[1])

    def test_replacing_a_failing_check_ends_its_block_without_a_removal_report(self):
        self.write(OKAFOR)
        self.assertIn("C1: FAIL within_budget", self.stop())
        self.write(OKAFOR, MAKER)
        self.assertIsNone(self.stop())

    def test_deleting_a_replaced_check_that_was_failing_is_still_reported(self):
        self.write(OKAFOR)
        self.assertIsNotNone(self.stop())
        self.write(dict(MAKER, replaces=[]))
        self.assertIn("C1: check was failing and has been removed from the record", self.stop())


if __name__ == "__main__":
    unittest.main()
