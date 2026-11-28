"""A budget's money is read as money: not a length of time, an ordinal, a clock time or a date.

In saved live records, 6 of 254 budget checks had an estimate that looked
sourced because a cited quote held the same number as something else: "he can
only do a 60-minute session" for $60 (four checks), "Today is August 20" for
$20 (two checks).
"""
import importlib.util
from pathlib import Path
import time
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
    def test_zero_quantity_and_monetary_unit_need_independent_sources(self):
        quote = "A 25-minute session. No attendees. Budget $600."
        factors = budget([{"unit": 25, "quantity": 0}])
        self.assertEqual(unsourced(factors, quote), ["amounts unit 25", "amounts quantity 0"])
        self.assertEqual(unsourced(factors, quote + " Tickets are $25 per attendee."), [])

    def test_a_length_of_time_does_not_source_an_amount(self):
        said = "Our budget is $600. He can only do a 60-minute session, and the room is ours for 2 hours."
        self.assertEqual(unsourced(budget([60]), said), ["amounts 60"])
        self.assertEqual(unsourced(budget([2]), said), ["amounts 2"])
        for words in ("a 3-day event", "6 weeks away", "for 45 min", "a 2h slot", "over 3 nights"):
            with self.subTest(words=words):
                number = int("".join(ch for ch in words if ch.isdigit()))
                self.assertEqual(unsourced(budget([number]), "Budget $600, " + words + "."), ["amounts %d" % number])
        self.assertEqual(unsourced(budget([60]), said + " The room is $60."), [])
        # A unit follows its number after spaces or one attached hyphen, not a comma
        # or a spaced dash (Codex review on 0.3.26).
        for words in ("Printing costs 20, hours for setup are flexible.",
                      "Printing costs 20 - hours for setup are flexible."):
            with self.subTest(words=words):
                self.assertEqual(unsourced(budget([20]), "Budget 600. " + words), [])
        self.assertEqual(unsourced(budget([20]), "Budget 600. A 20-hour setup."), ["amounts 20"])
        self.assertEqual(unsourced(budget([1000000], total_cap=1200), "Budget $1,200, catering 1,000,000."), [])

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
                              ("Budget £600. Rent is £five hundred pm.", [500]),
                              # A currency code marks money like a sign (Codex review on 0.3.26).
                              ("Budget 600. A USD 20 May fee, and the trainer is EUR 150 hour.", [20, 150]),
                              ("Budget 600. A $1e+3 May fee.", [1000]),
                              # A date is never blanked out of a price (Codex review on 0.3.26).
                              ("Budget $600. A $20.50 May fee, a $ 30 June fee.", [20.5, 30]),
                              ("Budget $600. Due May 20.50 total.", [20.5]),
                              ("Budget 600 dollars, 250 for catering.", [250])):
            with self.subTest(said=said):
                self.assertEqual(unsourced(budget(amounts, total_cap=1500 if "1.5k" in said else 600), said), [])

    def test_a_number_that_cannot_be_a_day_stays_money_beside_a_month(self):
        # Codex review on 0.3.26: monthly figures without a currency sign are money
        # when no calendar day is that large.
        said = "Our budget is 600. Monthly costs: May 50, June 40, July 35."
        self.assertEqual(unsourced(budget([50, 40, 35]), said), [])
        self.assertEqual(stated("Monthly costs: May 50, June 40, July 35 (my estimates).", budget([50, 40, 35]),
                                "Our budget is 600."), {"C1"})
        # A day from 1 to 31 still reads as a date, and so does an ISO date with a real month.
        self.assertEqual(unsourced(budget([31]), "Budget 600, due May 31."), ["amounts 31"])
        self.assertEqual(unsourced(budget([20]), "Budget 600, due 2026-12-20."), ["amounts 20"])
        self.assertEqual(unsourced(budget([30]), "Budget 600, code 2026-13-30."), [])
        # Only a value a clock shows is a time before am or pm.
        self.assertEqual(unsourced(budget([500, 450]), "Budget 600. Rent 500 pm, or five hundred pm, or 450 am."), [])
        self.assertEqual(unsourced(budget([9.3]), "Budget 600. Doors at 9.30pm."), ["amounts 9.3"])
        self.assertEqual(unsourced(budget([9]), "Budget 600. Doors at nine pm."), ["amounts 9"])
        # So does a scale word: "May 2 thousand dollars" is 2000 (Codex review on 0.3.26).
        said = "Budget 6000. Monthly costs: May 2 thousand dollars, June 3 thousand dollars."
        self.assertEqual(unsourced(budget([2000, 3000], total_cap=6000), said), [])
        self.assertEqual(stated("Monthly costs: May 2 thousand dollars (my estimate).", budget([2000], total_cap=6000),
                                "Budget 6000."), {"C1"})
        # A currency word after the day makes it money too.
        self.assertEqual(unsourced(budget([25, 20]), "Budget 600. Rent: June 25 euros, May 20 dollars."), [])

    def test_a_price_is_not_cut_short_by_a_date_after_it(self):
        # "$20.50 May fee" must not read as "$20." with "50 May" taken for a date.
        self.assertEqual(unsourced(budget([20]), "Budget $600. A $20.50 May fee."), ["amounts 20"])
        self.assertEqual(unsourced(budget([0.5]), "Budget $600. Due May 20.50 total."), ["amounts 0.5"])

    def test_a_date_does_not_run_from_one_quote_into_the_next(self):
        # Codex review on 0.3.26: a check's sources are its quotes joined by line
        # breaks, so "launch in May" then "20 for printing" must not read as May 20.
        for said, quote in (("Our budget is 600; launch in May", "20 for printing"),
                            ("Our budget is 600 and printing is 20", "May we add flyers?"),
                            # Nor does a unit of time: "costs 20" then "Hours for setup" is no 20 hours.
                            ("Our budget is 600; printing costs 20", "Hours for setup are flexible."),
                            ("Our budget is 600; printing costs 20", "Am I right that the room is free?")):
            with self.subTest(said=said, quote=quote):
                check = budget([20], refs=["I1"])
                document = {"version": 1, "objective": {"text": "Plan", "quote": said},
                            "items": [{"id": "I1", "text": "t", "quote": quote, "status": "commitment"}],
                            "checks": [check]}
                self.assertEqual(record.unsourced_values(document, check), [])
        self.assertEqual(unsourced(budget([20]), "Budget $600, launch in May 20."), ["amounts 20"])
        # The minutes reader keeps its units on the number's line too.
        window = {"id": "C1", "kind": "fits_window", "start": "09:00", "end": "09:20", "segments_min": [20],
                  "refs": ["I1"]}
        document = {"version": 1, "objective": {"text": "Plan", "quote": "Doors at 9:00, close 9:20, a break of 20"},
                    "items": [{"id": "I1", "text": "t", "quote": "Hours are flexible.", "status": "commitment"}],
                    "checks": [window]}
        self.assertEqual(record.unsourced_values(document, window), [])
        document["objective"]["quote"] = "Doors at 9:00, close 9:20, a break of 20, hours are flexible."
        self.assertEqual(record.unsourced_values(document, window), [])

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
        self.assertEqual(stated("A USD 20 May fee (my estimate).", budget([20]), "Budget 600."), {"C1"})
        self.assertEqual(unsourced(budget([2500000], total_cap=3000000), "Budget EUR 3M, and EUR 2.5M for the hall."), [])
        rent = budget([500])
        self.assertEqual(stated("Rent is £five hundred pm (my estimate).", rent, "Budget £600."), {"C1"})


class MoneyReadingSpeedTests(unittest.TestCase):
    def test_a_long_quote_of_iso_dates_is_read_in_linear_time(self):
        # Codex review on 0.3.26: checking each number against every ISO date was
        # quadratic, and 12,000 dated lines (384 KB) took 11 to 15 seconds, past the
        # hooks' 10 second timeout.
        quote = "Budget 600. " + "2026-03-20: event; printing 40. " * 12000
        record._SOURCED_NUMBERS.clear()
        started = time.perf_counter()
        self.assertEqual(unsourced(budget([40, 55]), quote), ["amounts 55"])
        self.assertLess(time.perf_counter() - started, 3)
        self.assertEqual(unsourced(budget([20]), "Budget 600. " + "2026-03-20: event. " * 3), ["amounts 20"])

    def test_money_costs_about_as_much_to_read_as_plain_numbers(self):
        # 0.3.26 ran a currency-code search, a month check and an am/pm check on every
        # number, and reading money took twice as long as reading numbers: a 1.2 MB
        # quote of numbers took 6.3 s to check against 2.8 s before. Cheap letter
        # checks now skip those regexes for numbers with no word beside them.
        quote = "Budget 600. " + "1 " * 100000
        timings = []
        for unit in (None, record.MONEY_EXCLUDED_UNIT):
            record._SOURCED_NUMBERS.clear()
            started = time.perf_counter()
            record._sourced_numbers(quote, unit)
            timings.append(time.perf_counter() - started)
        self.assertLess(timings[1], 1.8 * timings[0], timings)


if __name__ == "__main__":
    unittest.main()
