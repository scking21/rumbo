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

    def test_a_time_that_names_its_half_of_the_day_keeps_one_reading(self):
        for words in ('1:00a', '1:00 a.', '1:00 in the morning', '1:00 pm0', '1:00:00', '1:00 am', '1:00 a.m.', '1:00 a', '1:00 A', '1:00 a, b', '1:00 a?', '1:00 a)', '1:00 a-b'):
            with self.subTest(words=words):
                self.assertFalse(record._is_time_sourced('13:00', words))
        for words in ('1:00 in the afternoon', '1:00 at night', '1:00 tonight'):
            with self.subTest(words=words):
                self.assertTrue(record._is_time_sourced('13:00', words))
        self.assertTrue(record._is_time_sourced('13:00', 'out by 1:00, then dinner'))
        self.assertTrue(record._is_time_sourced('13:00', 'Meet at 1:00 America/Chicago time'))
        for words in ('1:00 a quick lunch', '1:00 a 30-minute talk', '1:00 a $20 lunch', '1:00 a €20 lunch'):
            with self.subTest(words=words):
                self.assertTrue(record._is_time_sourced('13:00', words))

    def test_twenty_four_hour_and_meridiem_times_keep_their_one_reading(self):
        for quote, start in (('From 09:30 for 45 minutes until 23:00', '21:30'),
                             ('From 9:30am for 45 minutes until 23:00', '21:30'),
                             ('From 13:30 for 45 minutes until 23:00', '01:30')):
            with self.subTest(quote=quote):
                code, out = check(quote, kind='fits_window', start=start, end='23:00', segments_min=[45])
                self.assertEqual(code, 1)
                self.assertIn('start ' + start, out)

    def test_a_spaced_minus_after_a_number_is_a_range_for_words_as_for_digits(self):
        for words, value in (('Step 1 - 10 people', 10), ('Step 1 - ten people', 10), ('Room 4 - twenty seats', 20)):
            with self.subTest(words=words):
                self.assertTrue(record._is_number_sourced(value, words))
                self.assertFalse(record._is_number_sourced(-value, words))
        self.assertTrue(record._is_number_sourced(-10, 'a change of - ten dollars'))

    def test_a_second_scale_word_does_not_merge_two_numbers(self):
        for value in (3000, 1002, 2002000):
            with self.subTest(value=value):
                self.assertFalse(record._is_number_sourced(value, 'one thousand and two thousand dollars'))
        self.assertTrue(record._is_number_sourced(2500000, 'two million five hundred thousand dollars'))
        for words in ('one thousand and two thousand five hours', 'one thousand and two thousand five elevenths of an hour'):
            for minutes in (300, 120, 60):
                with self.subTest(words=words, minutes=minutes):
                    self.assertFalse(record._is_minutes_sourced(minutes, words))
        self.assertFalse(record._is_number_sourced(5, 'twelve hundred thousand thousand five dollars'))
        self.assertTrue(record._is_number_sourced(7, 'one thousand and two thousand, then seven guests'))

    def test_a_hyphenated_half_an_hour_is_thirty_minutes(self):
        for words in ('half-an-hour', 'a half-an-hour break'):
            with self.subTest(words=words):
                self.assertTrue(record._is_minutes_sourced(30, words))
                self.assertFalse(record._is_minutes_sourced(60, words))

    def test_a_temporal_before_is_not_a_retraction(self):
        item = {'id': 'I4', 'text': 'Budget caps', 'status': 'commitment',
                'quote': 'the $600 total is firm, and no line item can exceed $300'}
        self.assertIsNone(record._retraction_for(item, ['Undo the last formatting change before you send it.']))
        self.assertIsNotNone(record._retraction_for(item, ['Undo the approval from last time.']))

    def test_coding_positions_are_not_planning(self):
        for prompt in ('why does a[1:20] drop the last row', 'error at record.py:12:30', 'inspect rows[0][1:20]',
                       'the log line 10:42:13 shows the retry', 'see line 12:30 of the diff',
                       'see settings.json:12:30', 'view.swift:12:30 crashes'):
            with self.subTest(prompt=prompt):
                self.assertIsNone(record.PLANNING_PATTERN.search(prompt))
        for prompt in ('meet at 10:30 tomorrow', 'doors (9:45) then talks', 'the 12:30 close', '[9:30 am] standup',
                       'Dinner: 7:30', 'pipeline 8:15 run', 'headline 10:30',
                       '[Standup 9:30]', '[9:30] standup'):
            with self.subTest(prompt=prompt):
                self.assertIsNotNone(record.PLANNING_PATTERN.search(prompt))


    def test_long_messages_stay_fast(self):
        import time
        for text in ('one ' * 12500, 'five and ' * 6000, 'five hundred and ' * 3000, 'two hours ' * 5000):
            with self.subTest(text=text[:20]):
                began = time.monotonic()
                record._is_minutes_sourced(7, text)
                record._is_number_sourced(7, text)
                self.assertLess(time.monotonic() - began, 2)


if __name__ == '__main__':
    unittest.main()
