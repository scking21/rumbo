"""Times, dates and money as people say them, and arithmetic the script does for the agent.

Each honest record here was blocked on 0.3.8: a spelled or compound duration,
a window past midnight, Feb 29, the far end of a date range, a scaled amount
or a price per unit. Each invented value must still be reported.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'record.py'
SPEC = importlib.util.spec_from_file_location('math_record', SCRIPT)
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)


def verdict(words, check):
    document = dict(version=1, objective=dict(text='Synthetic plan', quote=words), items=[],
                    checks=[dict(check, id='C1')])
    faults = record.validate_record(document)
    if faults:
        return 'INVALID', '; '.join(faults)
    passed, detail = record.evaluate_check(document['checks'][0])
    unsourced = record.unsourced_values(document, document['checks'][0])
    if not passed:
        return 'FAIL', detail
    if unsourced:
        return 'UNSOURCED', ', '.join(unsourced)
    return 'PASS', ''


def window(start, end, segments, **extra):
    return dict(kind='fits_window', start=start, end=end, segments_min=segments, **extra)


def budget(amounts, cap, item_cap=None):
    check = dict(kind='within_budget', amounts=amounts, total_cap=cap)
    if item_cap is not None:
        check['item_cap'] = item_cap
    return check


class DurationPhrasingTests(unittest.TestCase):
    def test_spelled_and_compound_durations_source_their_minutes(self):
        cases = (
            ('Start at 9:00, a twenty-minute welcome, then a ninety-minute workshop, done by 11:00.', [20, 90], '11:00'),
            ('Start 9:00, two hours of demos, lunch at 11:00.', [120], '11:00'),
            ('Start 9:00, a half-hour reception then the 90-minute screening, out by 11:00.', [30, 90], '11:00'),
            ('From 9:00: half an hour of setup, then a 45-minute talk, until 11:00.', [30, 45], '11:00'),
            ('At 9:00 half an hour of setup, then a 45-minute talk, until 11:00.', [30, 45], '11:00'),
            ('Two sessions from 9:00, each an hour, done by 11:00.', [60, 60], '11:00'),
            ('Two sessions from 9:00, an hour each, done by 11:00; 150 dollars total.', [60, 60], '11:00'),
            ('The DJ is $150 an hour for 2 hours from 9:00 to 11:00.', [120], '11:00'),
            ('Start 9:00, an hour of trail, breakfast at 11:00.', [60], '11:00'),
            ('Rehearsal at 9:00 runs an hour and a half; the hall closes at 11:00.', [90], '11:00'),
            ('Lab from 9:00, 2 and a half hours, vacate by 11:30.', [150], '11:30'),
            ('Starts 9:00 and lasts 1 hour 15 minutes; next group 11:00.', [75], '11:00'),
            ('Begin 9:00, drive 2h30, check-in closes 11:30.', [150], '11:30'),
            ('Begin 9:00, drive 2h30m, check-in closes 11:30.', [150], '11:30'),
            ('9:00 start, a quarter-hour break, sixty minutes of yoga, free until 11:00.', [15, 60], '11:00'),
            ('9:00 start, three quarters of an hour of drills, done 11:00.', [45], '11:00'),
            ('Talk at 9:00, one and a half hours, room booked till 11:00.', [90], '11:00'),
            ('Talk at 9:00, one hour and a half, room booked till 11:00.', [90], '11:00'),
            ('Session 9:00, one hour twenty minutes, ends 11:00.', [80], '11:00'),
            ('Lab from 9:00, 2 hours and a half, vacate by 11:30.', [150], '11:30'),
            ('Start 9:00, a two-and-a-half-hour workshop, finish by 11:30.', [150], '11:30'),
            ('Start 9:00, a one-and-a-half-hour talk, finish by 11:00.', [90], '11:00'),
            ('Start 9:00, an hour and three quarters of rehearsal, finish by 11:00.', [105], '11:00'),
            ('Start 9:00, an hour and a quarter of rehearsal, finish by 11:00.', [75], '11:00'),
            ('Start 9:00, 1 hour plus 15 minutes, finish by 11:00.', [75], '11:00'),
            ('Start 9:00, 2 hours and 3 breaks, finish by 11:00.', [120], '11:00'),
            ('Start 9:00. Rehearsal takes 1 hour. 15 minutes of cleanup follow; finish by 11:00.', [60, 15], '11:00'),
            ('Start 9:00, 1 hr. 15 mins of rehearsal, finish by 11:00.', [75], '11:00'),
            ('Start 9:00, two half-hour sessions, finish by 11:00.', [30, 30], '11:00'),
            ('Start 9:00, two quarter-hour breaks, finish by 11:00.', [15, 15], '11:00'),
            ('Start 9:00, 3 half-hour slots, finish by 11:00.', [30, 30, 30], '11:00'),
            ('Start 9:00. The talk lasts 1 hour, and a half-hour break follows; finish by 11:00.', [60, 30], '11:00'),
            ('Start 9:00, the talk lasts 1 hour and a half-hour break follows, finish by 11:00.', [60, 30], '11:00'),
            ('Start 9:00, 2 hours and a quarter hour of questions, finish by 11:30.', [120, 15], '11:30'),
            ('Start 9:00, a one-and-three-quarter-hour workshop, finish by 11:00.', [105], '11:00'),
            ('Start 9:00, an hour and three-quarters of rehearsal, finish by 11:00.', [105], '11:00'),
            ('Start 9:00, three quarter-hour breaks, finish by 11:00.', [15, 15, 15], '11:00'),
            ('Start 9:00, a three-quarter-hour talk, finish by 11:00.', [45], '11:00'),
            ('Start 9:00, a three-quarter hour talk, finish by 11:00.', [45], '11:00'),
            ('Start 9:00, a 45-minute talk and a half-hour break, finish by 11:00.', [45, 30], '11:00'),
            ('Start 9:00, an hour of setup and half an hour of rehearsal, finish by 11:00.', [60, 30], '11:00'),
            ('Start 9:00, lunch and a quarter-hour walk, finish by 11:00.', [15], '11:00'),
        )
        for words, segments, end in cases:
            with self.subTest(words=words):
                self.assertEqual(verdict(words, window('09:00', end, segments)), ('PASS', ''))

    def test_whole_spelled_counts_source_their_minutes(self):
        for words, minutes in (('twenty-four hours', 1440), ('one hundred hours', 6000), ('one hundred and one hours', 6060)):
            with self.subTest(words=words):
                self.assertEqual(record._is_minutes_sourced(minutes, words), minutes == 1440)

    def test_a_colon_after_a_time_is_punctuation_not_seconds(self):
        self.assertEqual(verdict('Agenda 9:00: welcome, 30 minutes. 9:30: done.', window('09:00', '09:30', [30])), ('PASS', ''))
        self.assertEqual(verdict('Doors 09:00:30, 30 minutes, done 9:30', window('09:00', '09:30', [30])),
                         ('UNSOURCED', 'start 09:00'))

    def test_durations_that_were_not_said_stay_unsourced(self):
        cases = (
            ('a twenty-minute break from 9:00 to 11:00', 15),
            ('9:45:30 is not 9:45, 9:00 to 11:00', 45),
            ('the DJ is $150 an hour, 9:00 to 11:00', 60),
            ('half an hour of setup, 9:00 to 11:00', 60),
            ('an hour and a half, 9:00 to 11:00', 60),
            ('one hour and a half, 9:00 to 11:00', 60),
            ('1 hour and a half, 9:00 to 11:00', 60),
            ('2 hours and a half, 9:00 to 11:00', 120),
            ('2 hours and a quarter, 9:00 to 11:00', 120),
            ('The tutor charges $150 per half hour; available 9:00 to 11:00', 30),
            ('$150 a half hour, 9:00 to 11:00', 30),
            ('$40/quarter hour, 9:00 to 11:00', 15),
            ('a shuttle every half hour, 9:00 to 11:00', 30),
            ('meds every 2 hours, 9:00 to 11:00', 120),
            ('$95 per hour and a half, 9:00 to 11:00', 90),
            ('one hundred and one hours of rehearsals, 9:00 to 11:00', 60),
            ('two thousand and five hours, 9:00 to 11:00', 300),
            ('one hundred and two and a half hours, 9:00 to 11:00', 150),
            ('1 hour one hundred and five minutes, 9:00 to 11:00', 65),
            ('Starts 9:00 and lasts 1 hour 15 minutes, until 11:00', 60),
            ('drive 2h30, 9:00 to 11:00', 120),
            ('an hour and fifteen minutes, 9:00 to 11:00', 60),
            ('Start 9:00, a two-and-a-half-hour workshop, finish by 11:00', 30),
            ('a one-and-a-half-hour talk, 9:00 to 11:00', 30),
            ('a two-and-a-quarter-hour hike, 9:00 to 11:00', 15),
            ('one hundred and a half hours, 9:00 to 11:00', 30),
            ('$95 per two-and-a-half-hour session, 9:00 to 11:00', 30),
            ('$95 per two-and-a-half-hour session, 9:00 to 11:00', 150),
            ('Start 9:00, an hour and three quarters of rehearsal, finish by 11:00', 60),
            ('an hour and a third, 9:00 to 11:00', 60),
            ('1 hour and 20, 9:00 to 11:00', 60),
            ('1 hour plus 15 minutes, 9:00 to 11:00', 60),
            ('2 hours plus a half, 9:00 to 11:00', 120),
            ('The shuttle runs twice an hour; available 9:00 to 11:00', 60),
            ('a bus once an hour, 9:00 to 11:00', 60),
            ('checks three times an hour, 9:00 to 11:00', 60),
            ('alerts 4 times per hour, 9:00 to 11:00', 60),
            ('a bell twice a half hour, 9:00 to 11:00', 30),
            ('Rehearsal takes 1 hour. 15 minutes of cleanup follow, 9:00 to 11:00', 75),
            ('Start 9:00, two hours and a half day of rehearsal, finish by 11:00', 150),
            ('The talk lasts 1 hour, and a half-hour break follows, 9:00 to 11:00', 90),
            ('one hundred and a half hour, 9:00 to 11:00', 30),
            ('Start 9:00, a one-and-three-quarter-hour workshop, finish by 11:00', 75),
            ('Start 9:00, three quarter-hour breaks, finish by 11:00', 45),
            ('three quarter hour, 9:00 to 11:00', 45),
            ('three quarter hour, 9:00 to 11:00', 15),
            ('two quarters of an hour, 9:00 to 11:00', 15),
            ('two hours and a half day of rehearsal, 9:00 to 11:00', 120),
            ('an hour and a quarter minute, 9:00 to 11:00', 75),
            ('$95 half hour, 9:00 to 11:00', 30),
            ('$80 per 2 hours, 9:00 to 11:00', 120),
            ('The tutor charges 150 dollars an hour; available 9:00 to 11:00', 60),
            ('fifty dollars an hour, 9:00 to 11:00', 60),
            ('four hundred fifty dollars an hour, 9:00 to 11:00', 60),
            ('twenty-five bucks a half hour, 9:00 to 11:00', 30),
            ('40 euros a quarter hour, 9:00 to 11:00', 15),
            ('3-5 hours, 9:00 to 11:00', 180),
            ('3-5 hours, 9:00 to 11:00', 300),
            ('two and a half hours, 9:00 to 11:00', 30),
            ('one and a half days, 9:00 to 11:00', 90),
            ('2 hours 15, 9:00 to 11:00', 135),
        )
        for words, minutes in cases:
            with self.subTest(words=words, minutes=minutes):
                self.assertEqual(verdict(words + ', or 17:00', window('09:00', '17:00', [minutes]))[0], 'UNSOURCED')

    def test_hours_still_never_source_money(self):
        self.assertEqual(verdict('an hour of setup, budget $500', budget([60], 500)),
                         ('UNSOURCED', 'amounts 60'))


class AmountPhrasingTests(unittest.TestCase):
    def test_spelled_and_scaled_amounts_are_sourced(self):
        cases = (
            ('Total budget $2.5M; construction is $1.8 million.', [1800000], 2500000),
            ('We have five thousand dollars; the venue is $3,200.', [3200], 5000),
            ('Budget is $800; the photographer charges four hundred fifty dollars.', [450], 800),
            ('Budget $500, plus one hundred and twenty for flowers.', [120], 500),
            ('A thousand dollars in all, twenty-five for stamps.', [25], 1000),
            ('Catering costs fifteen hundred dollars of a $2,000 budget.', [1500], 2000),
            ('Venue is twenty-five hundred dollars, budget $3,000.', [2500], 3000),
            ('Founded nineteen hundred and fifty; budget $2,000.', [1950], 2000),
            ('Tables are twelve hundred, budget $2,000.', [1200], 2000),
            ('Two speakers at $500 and one and a half days of prep, budget $2,000.', [500, 500], 2000),
        )
        for words, amounts, cap in cases:
            with self.subTest(words=words):
                self.assertEqual(verdict(words, budget(amounts, cap)), ('PASS', ''))

    def test_spelled_and_scaled_amounts_do_not_source_other_values(self):
        cases = (
            ('seventeen chairs, budget $1000000000', 7),
            ('someone has the money, budget $1000000000', 1),
            ('five six, budget $1000000000', 56),
            ('construction is $1.8 million, budget $1000000000', 1.8),
            ('a 5m banner, budget $1000000000', 5000000),
            ('Catering costs fifteen hundred dollars; budget $1000000000', 15),
            ('twenty-five hundred dollars, budget $1000000000', 25),
            ('a thousand thousand, budget $1000000000', 1000),
            ('Catering costs one and a half thousand dollars; budget $1000000000', 1),
            ('one point five million, budget $1000000000', 1),
            ('2 and a half thousand, budget $1000000000', 2),
            ('a million and a half, budget $1000000000', 1000000),
            ('two-and-a-half grand, budget $1000000000', 2),
            ('a refund of -twenty, budget $1000000000', 20),
            ('a refund of -€50, budget $1000000000', 50),
        )
        for words, amount in cases:
            with self.subTest(words=words):
                self.assertEqual(verdict(words, budget([amount], 10 ** 9))[0], 'UNSOURCED')


class PricePerUnitTests(unittest.TestCase):
    def test_the_script_multiplies_a_price_per_unit(self):
        self.assertEqual(verdict('Catering is $45 per person for our team of 12, out of a $600 budget.',
                                 budget([{'unit': 45, 'quantity': 12}], 600)), ('PASS', ''))
        self.assertEqual(verdict('Registration is $15 per attendee; the venue holds forty people; $600 total.',
                                 budget([{'unit': 15, 'quantity': 40}], 600)), ('PASS', ''))

    def test_an_over_budget_product_names_its_factors(self):
        self.assertEqual(verdict('The DJ is $150 an hour for 4 hours; entertainment cap $500.',
                                 budget([{'unit': 150, 'quantity': 4}, 0], 500)),
                         ('FAIL', 'total 600 exceeds total_cap 500 by 100 (150 x 4 = 600)'))
        self.assertEqual(verdict('Tables are $120 each and we need 3; no line item over $300; $1,000 total.',
                                 budget([{'unit': 120, 'quantity': 3}], 1000, 300)),
                         ('FAIL', 'amount 120 x 3 = 360 exceeds item_cap 300'))

    def test_products_are_exact_decimals(self):
        self.assertEqual(record.evaluate_check(budget([{'unit': 0.1, 'quantity': 3}], 0.3)), (True, None))
        self.assertEqual(record.evaluate_check(budget([{'unit': 0.1, 'quantity': 3}], 0.29)),
                         (False, 'total 0.3 exceeds total_cap 0.29 by 0.01 (0.1 x 3 = 0.3)'))
        huge = 10 ** 30
        self.assertEqual(record.evaluate_check(budget([{'unit': huge + 1, 'quantity': huge}], huge * huge + huge)),
                         (True, None))

    def test_each_factor_must_be_the_users(self):
        self.assertEqual(verdict('Catering is $45 per person, budget $600.', budget([{'unit': 45, 'quantity': 10}], 600)),
                         ('UNSOURCED', 'amounts quantity 10'))
        # Writing the product yourself is still an assumption.
        self.assertEqual(verdict('Catering is $45 per person for 12, budget $600.', budget([540], 600)),
                         ('UNSOURCED', 'amounts 540'))

    def test_malformed_units_are_validation_faults(self):
        for amount, path in (({'unit': 45, 'qty': 12}, 'amounts[0]'), ({'unit': 45}, 'amounts[0]'),
                             ({'unit': -1, 'quantity': 2}, 'amounts[0].unit'),
                             ({'unit': 1, 'quantity': float('inf')}, 'amounts[0].quantity'),
                             ({'unit': True, 'quantity': 2}, 'amounts[0].unit'), ('45', 'amounts[0]')):
            with self.subTest(amount=amount):
                status, detail = verdict('45 12 600', budget([amount], 600))
                self.assertEqual(status, 'INVALID')
                self.assertIn('checks[0].%s: CHECK_BAD_VALUE' % path, detail)


class MidnightTests(unittest.TestCase):
    def test_a_window_past_midnight_needs_end_next_day(self):
        words = 'The gala runs 9pm to 1am: three 60-minute sets, or three 90-minute sets.'
        self.assertEqual(verdict(words, window('21:00', '01:00', [60, 60, 60], end_next_day=True)), ('PASS', ''))
        self.assertEqual(verdict(words, window('21:00', '01:00', [90, 90, 90], end_next_day=True)),
                         ('FAIL', '21:00 + 270 min ends 01:30 next day, 30 min after 01:00 next day'))
        status, detail = verdict(words, window('21:00', '01:00', [60, 60, 60]))
        self.assertEqual(status, 'INVALID')
        self.assertIn('checks[0].end: CHECK_BAD_VALUE: end 01:00 is before start 21:00; '
                      'if the window runs past midnight, set end_next_day: true', detail)

    def test_end_next_day_cannot_extend_a_same_day_window(self):
        for end in ('10:00', '09:00'):
            with self.subTest(end=end):
                status, detail = verdict('Workshop from 9:00 to 10:00, 90 minutes of activities, or until 09:00',
                                         window('09:00', end, [90], end_next_day=True))
                self.assertEqual(status, 'INVALID')
                self.assertIn('checks[0].end_next_day: CHECK_BAD_VALUE: end %s is not before start 09:00, '
                              'so the window does not cross midnight; remove end_next_day' % end, detail)
        self.assertEqual(verdict('Workshop from 9:00 to 10:00, 90 minutes of activities', window('09:00', '10:00', [90])),
                         ('FAIL', '09:00 + 90 min ends 10:30, 30 min after 10:00'))

    def test_end_next_day_is_a_boolean(self):
        status, detail = verdict('9pm to 1am, 60 minutes', window('21:00', '01:00', [60], end_next_day='yes'))
        self.assertEqual(status, 'INVALID')
        self.assertIn('checks[0].end_next_day: CHECK_BAD_VALUE', detail)

    def test_a_same_day_overrun_reads_as_a_clock_time(self):
        self.assertEqual(record.evaluate_check(window('22:00', '23:30', [120])),
                         (False, '22:00 + 120 min ends 00:00 next day, 30 min after 23:30'))
        self.assertEqual(record.evaluate_check(window('22:00', '06:00', [3000], end_next_day=True)),
                         (False, '22:00 + 3000 min ends 00:00 3 days later, 2520 min after 06:00 next day'))

    def test_eval_messages_are_unchanged(self):
        self.assertEqual(record.evaluate_check(window('09:45', '12:30', [75, 20, 75])),
                         (False, '09:45 + 170 min ends 12:35, 5 min after 12:30'))
        self.assertEqual(record.evaluate_check(window('13:30', '16:15', [20, 50, 15, 50, 15, 50])),
                         (False, '13:30 + 200 min ends 16:50, 35 min after 16:15'))


class DatePhrasingTests(unittest.TestCase):
    def test_february_29_without_a_year(self):
        before = dict(kind='before', first='02-29', second='03-03')
        self.assertEqual(verdict('Abstracts are due Feb 29 and the conference opens March 3.', before), ('PASS', ''))
        self.assertEqual(record.evaluate_check(dict(kind='before', first='03-01', second='02-29')),
                         (False, '03-01 is 1 day after 02-29'))
        # Without Feb 29 the day count stays in a common year.
        self.assertEqual(record.evaluate_check(dict(kind='before', first='03-01', second='02-28')),
                         (False, '03-01 is 1 day after 02-28'))
        self.assertEqual(record.parse_date('02-30'), None)

    def test_both_ends_of_a_range_are_sourced_but_not_the_days_between(self):
        for words, first, second in (('The conference runs June 3-5; headcount by June 5.', '06-05', '06-05'),
                                     ('Festival 12–14 July, vendor forms due the 1st of July.', '07-01', '07-14'),
                                     ('Festival 12–14 July, setup on 1 July.', '07-01', '07-12'),
                                     ('Away Aug 10–17; report due August 9.', '08-09', '08-17'),
                                     ('Away Aug 10 — 17; report due August 9.', '08-09', '08-10')):
            with self.subTest(words=words):
                self.assertEqual(verdict(words, dict(kind='before', first=first, second=second)), ('PASS', ''))
        for words, date in (('The conference runs June 3-5.', '06-04'), ('Festival 12–14 July.', '07-13'),
                            ('June 3-15 people', '06-01')):
            with self.subTest(words=words):
                status, detail = verdict(words, dict(kind='before', first=date, second=date))
                self.assertEqual(status, 'UNSOURCED')

    def test_a_large_gap_names_the_same_year_assumption(self):
        self.assertEqual(record.evaluate_check(dict(kind='before', first='12-20', second='01-10')),
                         (False, '12-20 is 344 days after 01-10 in the same year; if 01-10 is in the '
                                 'following year, ask the user for both years'))
        self.assertEqual(record.evaluate_check(dict(kind='before', first='05-12', second='05-09')),
                         (False, '05-12 is 3 days after 05-09'))
        self.assertEqual(record.evaluate_check(dict(kind='before', first='2026-12-20', second='2026-01-10')),
                         (False, '2026-12-20 is 344 days after 2026-01-10'))


class CostTests(unittest.TestCase):
    def test_long_quotes_are_checked_in_linear_time(self):
        # 0.3.8 took about 47 s on 80 KB of numbers, past the hook's 10 s timeout.
        for text in ('1 ' * 50000, '-1 ' * 40000, 'one ' * 50000, 'an hour and ' * 20000, 'June 3-' * 20000):
            started = time.monotonic()
            record._is_number_sourced(7777777, text)
            record._is_minutes_sourced(77777, text)
            record._is_date_sourced('06-04', text)
            self.assertLess(time.monotonic() - started, 5, text[:12])


class CliTests(unittest.TestCase):
    def test_check_prints_a_unit_price_failure(self):
        document = dict(version=1, objective=dict(text='Synthetic dinner', quote='Dinner is $45 per person for 15 guests; cap $600.'),
                        items=[], checks=[dict(id='food', kind='within_budget', label='catering',
                                               amounts=[dict(unit=45, quantity=15)], total_cap=600)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text(json.dumps(document))
            result = subprocess.run([sys.executable, str(SCRIPT), 'check', '--record', str(path)],
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr),
                         (1, 'food: FAIL within_budget catering: total 675 exceeds total_cap 600 by 75 (45 x 15 = 675)', ''))


if __name__ == '__main__':
    unittest.main()
