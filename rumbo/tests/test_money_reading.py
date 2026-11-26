"""A budget's money is read as money: not a length of time, an ordinal, a clock time or a date.

In saved live records, 6 of 254 budget checks had an estimate that looked
sourced because a cited quote held the same number as something else: "he can
only do a 60-minute session" for $60 (four checks), "Today is August 20" for
$20 (two checks).
"""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record.py"
SPEC = importlib.util.spec_from_file_location("money_record", SCRIPT)
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)


def budget(amounts, total_cap=600, **fields):
    return dict({"id": "C1", "kind": "within_budget", "amounts": amounts, "total_cap": total_cap, "refs": []}, **fields)


def unsourced(check, said):
    document = {"version": 1, "objective": {"text": "Plan", "quote": said}, "items": [], "checks": [check]}
    return record.unsourced_values(document, check)


def stated(reply, check, said):
    document = {"version": 1, "objective": {"text": "Plan", "quote": said}, "items": [], "checks": [check]}
    return record.stated_checks(document, reply)


class MoneyReadingTests(unittest.TestCase):
    def test_a_length_of_time_does_not_source_an_amount(self):
        said = "Our budget is $600. He can only do a 60-minute session, and the room is ours for 2 hours."
        self.assertEqual(unsourced(budget([60]), said), ["amounts 60"])
        self.assertEqual(unsourced(budget([2]), said), ["amounts 2"])
        for words in ("a 3-day event", "6 weeks away", "for 45 min", "a 2h slot", "over 3 nights"):
            with self.subTest(words=words):
                number = int("".join(ch for ch in words if ch.isdigit()))
                self.assertEqual(unsourced(budget([number]), "Budget $600, " + words + "."), ["amounts %d" % number])
        self.assertEqual(unsourced(budget([60]), said + " The room is $60."), [])

    def test_a_date_an_ordinal_or_a_clock_time_does_not_source_an_amount(self):
        for words, amount in (("Today is August 20", 20), ("by the 20th", 20), ("on 2026-03-20", 20),
                              ("the 20th of March", 20), ("20 May", 20), ("Mar. 20", 20), ("a 9am start", 9),
                              ("doors at 9 a.m.", 9), ("the 3rd session", 3)):
            with self.subTest(words=words):
                self.assertEqual(unsourced(budget([amount]), "Budget $600. " + words + "."), ["amounts %d" % amount])

    def test_money_beside_those_words_still_sources_its_amount(self):
        for said, amounts in (("Our budget is $600, with marketing 50, decorations 40 and 20 for printing.", [50, 40, 20]),
                              ("Budget $600. A $20 May fee and £30 June dues.", [20, 30]),
                              ("Budget $600. Sept 12: $300 ads, due March 1.", [300]),
                              ("Budget $600. The room is $45/hour, or $150 a day.", [45, 150]),
                              ("Budget $1.5k.", [1500]),
                              # A currency sign makes it money, whatever follows.
                              ("Budget $600. The trainer is $150 hour, or $60 hr for the assistant.", [150, 60]),
                              ("Budget £600. Rent is £500 pm and the van €20 day.", [500, 20]),
                              # A date is never blanked out of a price (Codex review on 0.3.26).
                              ("Budget $600. A $20.50 May fee, a $ 30 June fee.", [20.5, 30]),
                              ("Budget $600. Due May 20.50 total.", [20.5]),
                              ("Budget 600 dollars, 250 for catering.", [250])):
            with self.subTest(said=said):
                self.assertEqual(unsourced(budget(amounts, total_cap=1500 if "1.5k" in said else 600), said), [])

    def test_a_price_is_not_cut_short_by_a_date_after_it(self):
        # "$20.50 May fee" must not read as "$20." with "50 May" taken for a date.
        self.assertEqual(unsourced(budget([20]), "Budget $600. A $20.50 May fee."), ["amounts 20"])
        self.assertEqual(unsourced(budget([0.5]), "Budget $600. Due May 20.50 total."), ["amounts 0.5"])

    def test_a_cap_and_a_price_per_unit_are_money_but_a_quantity_can_be_hours(self):
        said = "The room is $150 an hour for 4 hours, and the whole budget is 600."
        self.assertEqual(unsourced(budget([{"unit": 150, "quantity": 4}]), said), [])
        # 4 hours is not $4 a unit; 150 is a number, so it can count 150 of something.
        self.assertEqual(unsourced(budget([{"unit": 4, "quantity": 150}]), said), ["amounts unit 4"])
        self.assertEqual(unsourced(budget([150], total_cap=4), said), ["total_cap 4"])
        self.assertEqual(unsourced(budget([150], item_cap=4), said), ["item_cap 4"])

    def test_the_reply_reader_reads_money_the_same_way(self):
        said = "Our budget is $600. He can only do a 60-minute session."
        assumed = budget([60])
        self.assertEqual(stated("Catering is $60 (my estimate).", assumed, said), {"C1"})
        self.assertEqual(stated("The 60-minute session stays (my estimate).", assumed, said), set())
        over = budget([350, 300], refs=None)
        said = "Our budget is $600, with $350 for catering and $300 for the speaker."
        self.assertEqual(stated("That is $650, over the $600 budget.", over, said), {"C1"})
        self.assertEqual(stated("That is $50 over the budget.", over, said), {"C1"})
        self.assertEqual(stated("The talk runs 50 minutes over the budget slot.", over, said), set())


if __name__ == "__main__":
    unittest.main()
