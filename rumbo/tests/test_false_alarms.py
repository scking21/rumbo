"""Ordinary wording and calendars must not block a correct record."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'record.py'
SPEC = importlib.util.spec_from_file_location('false_alarm_record', SCRIPT)
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)


def check(quote, **fields):
    document = dict(version=1, objective=dict(text='Synthetic plan', quote=quote), items=[],
                    checks=[dict(id='C1', **fields)])
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'record.json'
        path.write_text(json.dumps(document))
        result = subprocess.run([sys.executable, str(SCRIPT), 'check', '--record', str(path)],
                                capture_output=True, text=True, timeout=10)
    return result.returncode, result.stdout.strip()


class FalseAlarmTests(unittest.TestCase):
    def test_a_clock_time_without_am_or_pm_sources_either_half_of_the_day(self):
        for quote, start, end in (('The talk starts at 11:30, runs 45 minutes, out by 1:00.', '11:30', '13:00'),
                                  ('Doors 6:30, a 90 minute show, done by 8:00', '18:30', '20:00'),
                                  ('From 12:15 for 45 minutes until 1:00', '12:15', '13:00'),
                                  ('From 12:15 for 45 minutes until 1:00', '00:15', '01:00')):
            with self.subTest(quote=quote, start=start):
                self.assertEqual(check(quote, kind='fits_window', start=start, end=end,
                                       segments_min=[45] if '45' in quote else [90]),
                                 (0, 'C1: PASS fits_window'))

    def test_twenty_four_hour_and_meridiem_times_keep_their_one_reading(self):
        for quote, start in (('From 09:30 for 45 minutes until 23:00', '21:30'),
                             ('From 9:30am for 45 minutes until 23:00', '21:30'),
                             ('From 13:30 for 45 minutes until 23:00', '01:30')):
            with self.subTest(quote=quote):
                code, out = check(quote, kind='fits_window', start=start, end='23:00', segments_min=[45])
                self.assertEqual(code, 1)
                self.assertIn('start ' + start, out)

    def test_durations_in_words_source_minutes(self):
        for quote, minutes in (('Doors at 9:00, an hour of setup, done by 17:00.', 60),
                               ('9:00 to 17:00, one hour of talks', 60),
                               ('9:00 to 17:00, a one-hour lunch', 60),
                               ('Start 9:00, half an hour of Q&A, out by 17:00', 30),
                               ('Start 9:00, a half-hour break, out by 17:00', 30),
                               ('Start 9:00, an hour and a half of demos, out by 17:00', 90),
                               ('Start 9:00, two hours of judging, out by 17:00', 120),
                               ('Start 9:00, a three-hour hike, out by 17:00', 180),
                               ('Start 9:00, forty-five minutes of setup, out by 17:00', 45)):
            with self.subTest(quote=quote):
                self.assertEqual(check(quote, kind='fits_window', start='09:00', end='17:00', segments_min=[minutes]),
                                 (0, 'C1: PASS fits_window'))

    def test_amounts_in_words_source_numbers(self):
        for quote, cap in (('We have five hundred dollars for food; catering quoted $450.', 500),
                           ('The cap is two thousand five hundred, catering quoted $450.', 2500),
                           ('A hundred and twenty for food; catering quoted $450 of a $1,000 total.', 120),
                           ('Twelve hundred total; catering quoted $450.', 1200)):
            with self.subTest(quote=quote):
                code, out = check(quote, kind='within_budget', amounts=[450], total_cap=cap)
                self.assertNotIn('UNSOURCED', out)

    def test_number_words_do_not_source_other_values(self):
        for quote, cap in (('We have five hundred dollars; catering quoted $450.', 5),
                           ('We have someone for food; catering quoted $450.', 1),
                           ('We have a budget; catering quoted $450.', 1)):
            with self.subTest(quote=quote, cap=cap):
                code, out = check(quote, kind='within_budget', amounts=[450], total_cap=cap)
                self.assertIn('total_cap %d' % cap, out)

    def test_number_words_keep_separate_numbers_and_signs(self):
        self.assertEqual(list(record._word_numbers('twenty and thirty dollars')), [20, 30])
        self.assertEqual(list(record._word_numbers('one-two hours')), [1, 2])
        self.assertEqual(list(record._word_numbers('two thousand five hundred and six')), [2506])
        self.assertFalse(record._is_number_sourced(500, 'minus five hundred dollars'))
        self.assertTrue(record._is_number_sourced(-500, 'minus five hundred dollars'))
        self.assertFalse(record._is_number_sourced(50, 'twenty and thirty dollars'))

    def test_word_ranges_and_halves_source_no_other_duration(self):
        for words, minutes in (('one-two hours', 180), ('one-two hours', 60), ('one-two hours', 120),
                               ('half-an-hour', 60), ('half an hour', 60), ('half a dozen hours', 60)):
            with self.subTest(words=words, minutes=minutes):
                self.assertFalse(record._is_minutes_sourced(minutes, words))
        self.assertTrue(record._is_minutes_sourced(30, 'half-an-hour'))

    def test_hours_in_words_never_source_money(self):
        code, out = check('Two hours of setup; catering quoted $450.', kind='within_budget', amounts=[450], total_cap=120)
        self.assertIn('total_cap 120', out)

    def test_a_window_that_ends_after_midnight(self):
        self.assertEqual(check('The party starts at 10pm, a 3-hour set, venue closes 2am.',
                               kind='fits_window', start='22:00', end='02:00', segments_min=[180]),
                         (0, 'C1: PASS fits_window'))
        self.assertEqual(check('The party starts at 10pm, a 5-hour set, venue closes 2am.',
                               kind='fits_window', start='22:00', end='02:00', segments_min=[300]),
                         (1, 'C1: FAIL fits_window: 22:00 + 300 min ends 03:00, 60 min after 02:00'))

    def test_dates_without_a_year_take_the_closer_reading(self):
        self.assertEqual(check('RSVPs are due December 20 for the January 5 retreat.',
                               kind='before', first='12-20', second='01-05'),
                         (0, 'C1: PASS before'))
        self.assertEqual(check('The printer needs details by March 20 for the March 12 event.',
                               kind='before', first='03-20', second='03-12'),
                         (1, 'C1: FAIL before: 03-20 is 8 days after 03-12'))
        self.assertEqual(check('Edits are due January 5 for the December 20 show.',
                               kind='before', first='01-05', second='12-20'),
                         (0, 'C1: PASS before'))
        self.assertEqual(check('Venue deposit by March 1 for the October 15 gala.',
                               kind='before', first='03-01', second='10-15'),
                         (0, 'C1: PASS before'))
        self.assertEqual(check('Edits are due September 1 for the March 12 show.',
                               kind='before', first='09-01', second='03-12'),
                         (1, 'C1: FAIL before: 09-01 is 173 days after 03-12'))

    def test_dates_with_years_compare_as_written(self):
        self.assertEqual(check('RSVPs are due December 20, 2026 for the January 5, 2026 retreat.',
                               kind='before', first='2026-12-20', second='2026-01-05'),
                         (1, 'C1: FAIL before: 2026-12-20 is 349 days after 2026-01-05'))

    def test_a_temporal_before_is_not_a_retraction(self):
        item = {'id': 'I4', 'text': 'Budget caps', 'status': 'commitment',
                'quote': 'the $600 total is firm, and no line item can exceed $300'}
        self.assertIsNone(record._retraction_for(item, ['Undo the last formatting change before you send it.']))
        self.assertIsNotNone(record._retraction_for(item, ['Undo the approval from last time.']))

    def test_coding_positions_are_not_planning(self):
        for prompt in ('why does a[1:20] drop the last row', 'error at record.py:12:30',
                       'the log line 10:42:13 shows the retry', 'see line 12:30 of the diff'):
            with self.subTest(prompt=prompt):
                self.assertIsNone(record.PLANNING_PATTERN.search(prompt))
        for prompt in ('meet at 10:30 tomorrow', 'doors (9:45) then talks', 'the 12:30 close'):
            with self.subTest(prompt=prompt):
                self.assertIsNotNone(record.PLANNING_PATTERN.search(prompt))


if __name__ == '__main__':
    unittest.main()
