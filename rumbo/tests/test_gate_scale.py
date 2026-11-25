"""The Stop gate verifies every record quote against every user message of a session.

0.3.12 tried each pair with a regular expression, folded every message again
for each unverified quote, and scanned each match's whole message prefix for a
sign and a clause. A record with 300 items in an 800-message session took about
17 s, past the hook's 10 s timeout, and a Stop hook that times out lets the
turn end unchecked. These tests keep the shortcuts exact and the gate fast.
"""
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import record  # noqa: E402


class QuoteMatchWindowTests(unittest.TestCase):
    """_quote_in looks only at the characters before a match that can change the answer."""

    def test_a_sign_before_a_quoted_number_still_rejects_it(self):
        for message in ("-$900 is the cap", "We said -$900", "a −$900 refund", "cap: -900"):
            quote = "900" if message.endswith("900") else "$900"
            self.assertFalse(record._quote_in(quote, message), message)
        self.assertTrue(record._quote_in("$900", "Budget 30-$900 range"))
        self.assertTrue(record._quote_in("$900", "Budget $900"))

    def test_a_sign_then_a_newline_before_the_quote_reads_as_it_did(self):
        # "$" also matches before a final newline, so the sign test reaches back
        # four characters: a digit there makes the "-" a range dash, not a sign.
        self.assertTrue(record._quote_in("budget", "a00−$\nbudget we"))
        self.assertTrue(record._quote_in("e", "9-$\ne done"))
        self.assertFalse(record._quote_in("budget", "−$\nbudget we"))
        self.assertFalse(record._quote_in("budget", "x-$\nbudget we"))

    def test_negation_is_read_in_the_last_40_characters_of_the_clause(self):
        self.assertFalse(record._quote_in("spend $900", "We do not spend $900 on this."))
        far = "We do not want that. " + "x" * 50 + " spend $900"
        self.assertTrue(record._quote_in("spend $900", far))
        near_break = "not now; we spend $900"
        self.assertTrue(record._quote_in("spend $900", near_break))
        just_within = "not " + "y" * 30 + " spend $900"
        self.assertFalse(record._quote_in("spend $900", just_within))

    def test_a_message_without_the_text_is_rejected_before_any_pattern(self):
        self.assertFalse(record._quote_in("$900", "nothing here"))
        self.assertFalse(record._quote_in("", "anything"))


class GateScaleTests(unittest.TestCase):
    def test_a_large_record_in_a_long_session_stays_well_inside_the_hook_timeout(self):
        words = "venue budget catering speaker schedule session break printer deadline".split()
        messages = ["Message %d: the %s costs $%d and %s." % (i, words[i % len(words)], 100 + i,
                                                                " ".join(words) * 4) for i in range(1200)]
        # Quotes the user never said: every one is checked against every message,
        # and then again for the negation diagnostic, the slowest path.
        items = [{"id": "I%d" % i, "text": "item %d" % i, "status": "draft",
                  "quote": "Quote %d about the %s that nobody wrote down at all" % (i, words[i % len(words)])}
                 for i in range(400)]
        document = {"version": 1, "objective": {"text": "Plan", "quote": messages[0]}, "items": items, "checks": []}
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".rumbo"))
            path = os.path.join(tmp, ".rumbo", "record.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(document, handle)
            transcript = os.path.join(tmp, "t.jsonl")
            with open(transcript, "w", encoding="utf-8") as handle:
                for text in messages:
                    handle.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                             "message": {"role": "user", "content": text}}) + "\n")
            args = record.build_parser().parse_args(["stop-gate", "--record", path])
            previous = os.environ.get("RUMBO_STATE_DIR")
            os.environ["RUMBO_STATE_DIR"] = os.path.join(tmp, "state")
            try:
                import contextlib
                import io
                out = io.StringIO()
                started = time.monotonic()
                with contextlib.redirect_stdout(out):
                    record._stop_gate(args, {"session_id": "scale", "transcript_path": transcript})
                elapsed = time.monotonic() - started
            finally:
                if previous is None:
                    os.environ.pop("RUMBO_STATE_DIR", None)
                else:
                    os.environ["RUMBO_STATE_DIR"] = previous
            reason = json.loads(out.getvalue())["reason"]
            self.assertIn("items[399].quote: UNVERIFIED: quote not found in the user's messages", reason)
            # 0.3.12 took about 16 s here; this change, about 0.25 s.
            self.assertLess(elapsed, 3)


if __name__ == "__main__":
    unittest.main()
