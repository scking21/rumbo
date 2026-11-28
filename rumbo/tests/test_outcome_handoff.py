"""Outcome handoff and Claude Stop compatibility on disposable project files."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "record.py")


class OutcomeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rumbo outcomes ")
        self.addCleanup(self.temp.cleanup)
        self.project = os.path.join(self.temp.name, "project")
        os.makedirs(os.path.join(self.project, ".rumbo"))
        self.record_path = os.path.join(self.project, ".rumbo", "record.json")
        self.report_path = os.path.join(self.project, "report.txt")
        with open(self.report_path, "w", encoding="utf-8") as handle:
            handle.write("verified report\n")
        self.report_sha = self.sha(self.report_path)
        self.transcript = os.path.join(self.temp.name, "transcript.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": "Build the report and index."}}) + "\n")
        self.env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(self.temp.name, "state"))

    @staticmethod
    def sha(path):
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    def base(self, outcomes):
        return {
            "version": 1,
            "objective": {"text": "Build the report and index", "quote": "Build the report and index."},
            "target": "the disposable report packet in this project",
            "items": [],
            "checks": [],
            "outcomes": outcomes,
        }

    def verified(self, outcome_id="O1"):
        return {
            "id": outcome_id,
            "text": "Report saved and read back",
            "owner": "worker",
            "acceptance": "report.txt has the reviewed bytes",
            "status": "verified",
            "evidence": "read report.txt after writing it",
            "artifacts": [{"path": "report.txt", "sha256": self.report_sha}],
        }

    @staticmethod
    def runnable(outcome_id="O2"):
        return {
            "id": outcome_id,
            "text": "Index saved and read back",
            "owner": "worker",
            "acceptance": "index.txt names report.txt",
            "status": "runnable",
            "next_action": "write and read back index.txt",
        }

    @staticmethod
    def blocked(outcome_id="O3"):
        return {
            "id": outcome_id,
            "text": "Owner accepts the packet",
            "owner": "project owner",
            "acceptance": "owner decision recorded",
            "status": "blocked",
            "blocker": "owner decision is unavailable to this worker",
            "restart_trigger": "owner records the decision",
        }

    def write(self, document):
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2)

    def run_cli(self, *args, payload=None, env=None):
        return subprocess.run(
            [sys.executable, SCRIPT, *args], input=payload, text=True,
            capture_output=True, env=env or self.env, timeout=10,
        )

    def handoff(self):
        return self.run_cli("handoff", "--record", self.record_path, "--root", self.project)

    def stop(self, session):
        payload = json.dumps({"session_id": session, "transcript_path": self.transcript})
        return self.run_cli("stop-gate", "--record", self.record_path, payload=payload)

    def test_runnable_row_continues_and_blocks_stop(self):
        self.write(self.base([self.verified(), self.runnable()]))
        handoff = self.handoff()
        report = json.loads(handoff.stdout)
        self.assertEqual((handoff.returncode, report["status"]), (1, "CONTINUE"))
        self.assertEqual(report["outcomes"][1]["next_action"], "write and read back index.txt")
        stop = self.stop("runnable")
        self.assertEqual(stop.returncode, 0, stop.stderr)
        block = json.loads(stop.stdout)
        self.assertEqual(block["decision"], "block")
        self.assertIn("OUTCOME O2: RUNNABLE", block["reason"])

    def test_a_pinned_handoff_refuses_a_record_that_changed_after_review(self):
        # The OpenAI adapter's CLI had this flag; the Claude CLI read it but did not offer it.
        self.write(self.base([self.verified()]))
        pin = self.sha(self.record_path)
        args = ("handoff", "--record", self.record_path, "--root", self.project)
        self.assertEqual(self.run_cli(*args, "--reviewed-record-sha256", pin).returncode, 0)
        changed = self.base([self.verified()])
        changed["outcomes"][0]["owner"] = "another worker"
        self.write(changed)
        refused = self.run_cli(*args, "--reviewed-record-sha256", pin)
        self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.assertIn("HANDOFF_RECORD_CHANGED", refused.stderr)
        self.assertIn("INVALID_REVIEW_DIGEST", self.run_cli(*args, "--reviewed-record-sha256", "bad").stderr)
        self.assertEqual(json.loads(self.run_cli(*args).stdout)["outcomes"][0]["owner"], "another worker")

    def test_a_repeat_names_a_runnable_outcome_by_its_text(self):
        self.write(self.base([self.runnable()]))
        self.assertIn("OUTCOME O2: RUNNABLE", json.loads(self.stop("repeat").stdout)["reason"])
        repeat = json.loads(self.stop("repeat").stdout)["reason"]
        self.assertIn("OUTCOME O2 (Index saved and read back)", repeat)

    def test_real_blocker_does_not_hide_unrelated_runnable_work(self):
        self.write(self.base([self.blocked(), self.runnable()]))
        report = json.loads(self.handoff().stdout)
        self.assertEqual(report["status"], "CONTINUE")
        self.assertEqual(self.stop("mixed").stdout.startswith('{"decision": "block"'), True)

    def test_blocked_only_is_bounded_and_does_not_block_stop(self):
        self.write(self.base([self.verified(), self.blocked()]))
        handoff = self.handoff()
        report = json.loads(handoff.stdout)
        self.assertEqual((handoff.returncode, report["status"]), (1, "BOUNDED"))
        self.assertEqual(report["outcomes"][1]["restart_trigger"], "owner records the decision")
        self.assertEqual(self.stop("bounded").stdout, "")

    def test_all_current_evidence_is_complete_and_does_not_block_stop(self):
        self.write(self.base([self.verified()]))
        handoff = self.handoff()
        report = json.loads(handoff.stdout)
        self.assertEqual((handoff.returncode, report["status"]), (0, "COMPLETE"))
        self.assertEqual(report["outcomes"][0]["artifacts"][0]["state"], "current")
        self.assertEqual(self.stop("complete").stdout, "")

    def test_handoff_refuses_a_sibling_root_even_if_its_bytes_match(self):
        self.write(self.base([self.verified()]))
        sibling = os.path.join(self.temp.name, "sibling")
        os.makedirs(sibling)
        os.rename(self.report_path, os.path.join(sibling, "report.txt"))
        case_variant = os.path.join(self.project, ".RUMBO", "RECORD.JSON")
        paths = [self.record_path]
        if os.path.exists(case_variant):
            paths.append(case_variant)
        for path in paths:
            with self.subTest(record=path):
                crossed = self.run_cli("handoff", "--record", path, "--root", sibling)
                self.assertEqual((crossed.returncode, crossed.stdout), (2, ""))
                self.assertIn("HANDOFF_PROJECT_MISMATCH", crossed.stderr)
        report = json.loads(self.handoff().stdout)
        self.assertEqual((report["status"], report["outcomes"][0]["artifacts"][0]["state"]),
                         ("CONTINUE", "missing"))

    def test_handoff_accepts_project_directory_alias_and_detached_record(self):
        self.write(self.base([self.verified()]))
        alias = os.path.join(self.temp.name, "project-link")
        os.symlink(self.project, alias, target_is_directory=True)
        detached = os.path.join(self.temp.name, "prior-record.json")
        with open(self.record_path, "rb") as source, open(detached, "wb") as copy:
            copy.write(source.read())
        for path, root in [(self.record_path, alias), (detached, self.project)]:
            with self.subTest(path=path, root=root):
                reply = self.run_cli("handoff", "--record", path, "--root", root)
                self.assertEqual(reply.returncode, 0, reply.stderr)
                self.assertEqual(json.loads(reply.stdout)["status"], "COMPLETE")

    def test_changed_bytes_reopen_only_the_stale_outcome(self):
        self.write(self.base([self.verified(), self.blocked()]))
        with open(self.report_path, "w", encoding="utf-8") as handle:
            handle.write("changed after review\n")
        handoff = self.handoff()
        report = json.loads(handoff.stdout)
        self.assertEqual((handoff.returncode, report["status"]), (1, "CONTINUE"))
        row = report["outcomes"][0]
        self.assertEqual((row["recorded_status"], row["effective_status"]), ("verified", "runnable"))
        self.assertEqual(row["artifacts"][0]["state"], "stale")
        block = json.loads(self.stop("stale").stdout)
        self.assertIn("OUTCOME O1: STALE_EVIDENCE", block["reason"])

    def test_required_checks_reopen_only_the_verified_row_that_needs_their_success(self):
        closed = self.verified("O2")
        closed["text"] = "Report the budget conflict"
        bound = dict(self.verified(), required_checks=["Budget"])
        document = self.base([bound, closed, self.blocked()])
        document["objective"]["quote"] = "The option costs $135 against a $90 budget."
        document["checks"] = [dict(id="Budget", kind="within_budget", amounts=[135], total_cap=90, refs=[])]
        self.write(document)
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": document["objective"]["quote"]}}) + "\n")
        report = json.loads(self.handoff().stdout)
        self.assertEqual(report["status"], "CONTINUE")
        self.assertEqual([r["effective_status"] for r in report["outcomes"]], ["runnable", "verified", "blocked"])
        check = report["outcomes"][0]["required_checks"][0]
        self.assertEqual((check["id"], check["state"]), ("Budget", "failed"))
        self.assertIn("Budget: FAIL", check["detail"])
        payload = json.dumps(dict(session_id="disclosed", transcript_path=self.transcript,
                                  last_assistant_message="The option costs $135 against the $90 budget."))
        result = self.run_cli("stop-gate", "--record", self.record_path, payload=payload)
        self.assertIn("Budget (failed)", json.loads(result.stdout)["reason"])

    def test_missing_required_check_keeps_every_row_visible_and_recovers(self):
        document = self.base([dict(self.verified(), required_checks=["Cost", "Slot"]), self.blocked()])
        document["objective"]["quote"] = "The cost is $45 within $90. The slot is 9:00 to 10:00 for 60 minutes."
        document["checks"] = [dict(id="Cost", kind="within_budget", amounts=[45], total_cap=90, refs=[])]
        self.write(document)
        report = json.loads(self.handoff().stdout)
        affected, blocked = report["outcomes"]
        self.assertEqual(report["status"], "CONTINUE")
        self.assertEqual([c["state"] for c in affected["required_checks"]], ["passed", "missing"])
        self.assertIn("Slot (missing)", affected["next_action"])
        self.assertEqual((blocked["owner"], blocked["restart_trigger"]), ("project owner", "owner records the decision"))
        document["checks"].append(dict(id="Slot", kind="fits_window", start="09:00", end="10:00",
                                       segments_min=[60], refs=[]))
        self.write(document)
        report = json.loads(self.handoff().stdout)
        self.assertEqual(report["status"], "BOUNDED")
        self.assertEqual([c["state"] for c in report["outcomes"][0]["required_checks"]], ["passed", "passed"])

    def test_unsourced_or_retired_check_does_not_supply_current_evidence(self):
        document = self.base([dict(self.verified(), required_checks=["Old", "Current"])])
        document["objective"]["quote"] = "Respect the $90 cap."
        document["checks"] = [dict(id="Old", kind="within_budget", amounts=[0], total_cap=90, refs=[]),
                              dict(id="Current", kind="within_budget", amounts=[35], total_cap=90,
                                   refs=[], replaces=["Old"])]
        self.write(document)
        report = json.loads(self.handoff().stdout)
        self.assertEqual(report["status"], "CONTINUE")
        self.assertEqual([c["state"] for c in report["outcomes"][0]["required_checks"]], ["retired", "unsourced"])
        document["outcomes"][0]["required_checks"] = ["Current"]
        document["objective"]["quote"] += " The accepted quote is $35."
        self.write(document)
        self.assertEqual(json.loads(self.handoff().stdout)["status"], "COMPLETE")

    def test_invalid_required_check_list_gets_a_structural_diagnostic(self):
        for bad in (None, [], "Cost", ["Cost", "Cost"], [False], [" "]):
            with self.subTest(bad=bad):
                self.write(self.base([dict(self.verified(), required_checks=bad)]))
                result = self.handoff()
                self.assertEqual(result.returncode, 1)
                self.assertIn("RECORD_BAD_REF", result.stdout)

    def test_show_orients_without_claiming_hash_freshness(self):
        self.write(self.base([self.runnable()]))
        result = self.run_cli("show", "--record", self.record_path)
        self.assertIn("Handoff (recorded status; run handoff to verify artifact hashes): CONTINUE", result.stdout)
        self.assertIn("OUTCOME O2 [runnable] owner worker", result.stdout)

    def test_invalid_rows_and_escaping_artifacts_are_rejected(self):
        cases = [
            self.base([{"id": "O1", "status": "runnable"}]),
            self.base([{**self.verified(), "artifacts": [{"path": "../outside", "sha256": "0" * 64}]}]),
        ]
        for index, document in enumerate(cases):
            with self.subTest(index=index):
                self.write(document)
                result = self.run_cli("validate", "--record", self.record_path)
                self.assertEqual(result.returncode, 1)
        self.assertIn("RECORD_BAD_PATH", result.stdout)

    def test_legacy_record_has_identical_clean_check_and_stop_behavior(self):
        legacy = {"version": 1, "objective": {"text": "One task", "quote": "One task."},
                  "items": [], "checks": []}
        self.write(legacy)
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": "One task."}}) + "\n")
        check = self.run_cli("check", "--record", self.record_path)
        self.assertEqual((check.returncode, check.stdout, check.stderr), (0, "", ""))
        self.assertEqual(self.stop("legacy").stdout, "")

    def test_actual_claude_wrapper_blocks_runnable_outcome(self):
        self.write(self.base([self.runnable()]))
        env = dict(self.env, CLAUDE_PLUGIN_ROOT=ROOT, CLAUDE_PROJECT_DIR=self.project)
        payload = json.dumps({"session_id": "wrapper", "transcript_path": self.transcript})
        result = subprocess.run(
            [os.path.join(ROOT, "scripts", "stop-gate.sh")], input=payload, text=True,
            capture_output=True, env=env, cwd=self.project, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OUTCOME O2: RUNNABLE", json.loads(result.stdout)["reason"])


if __name__ == "__main__":
    unittest.main()
