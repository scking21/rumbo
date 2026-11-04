"""Independent PR19 regressions: never shorten or change signed user values."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'record.py'


class ReviewSourcingBoundaryTests(unittest.TestCase):
    def check_output(self, quote, check):
        record = dict(version=1, objective=dict(text='Synthetic plan', quote=quote),
                      items=[], checks=[dict(check, id='C1')])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'record.json'
            path.write_text(json.dumps(record), encoding='utf-8')
            result = subprocess.run([sys.executable, str(SCRIPT), 'check', '--record', str(path)],
                                    capture_output=True, text=True, timeout=10)
        return result

    def test_currency_sign_does_not_drop_negative_spelled_amount(self):
        for sign in ('-', '\u2212'):
            for currency in ('$', '\u20ac', '\u00a3'):
                with self.subTest(sign=sign, currency=currency):
                    result = self.check_output('Adjustment %s%sfifty; budget 1000.' % (sign, currency),
                        dict(kind='within_budget', amounts=[50], total_cap=1000))
                    self.assertIn('UNSOURCED', result.stdout)

    def test_spaced_currency_sign_is_preserved(self):
        for phrase in ('- € fifty', '−  $  fifty', '-         £ fifty'):
            with self.subTest(phrase=phrase):
                result = self.check_output('Adjustment %s; budget 1000.' % phrase,
                    dict(kind='within_budget', amounts=[50], total_cap=1000))
                self.assertIn('UNSOURCED', result.stdout)

    def test_large_continued_minutes_never_source_whole_hour(self):
        for count in ('one hundred', 'one hundred and five', '100', 'one thousand'):
            with self.subTest(count=count):
                result = self.check_output('Start 9:00; an hour and %s minutes of rehearsal; finish 10:00.' % count,
                    dict(kind='fits_window', start='09:00', end='10:00', segments_min=[60]))
                self.assertIn('UNSOURCED', result.stdout)

    def test_positive_spelled_currency_amount_is_still_sourced(self):
        for currency in ('$', '\u20ac', '\u00a3'):
            result = self.check_output('Fee %sfifty; budget 1000.' % currency,
                dict(kind='within_budget', amounts=[50], total_cap=1000))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS', result.stdout)

    def test_unparsed_fraction_never_sources_whole_hours(self):
        for count in ('four', 'five', '4', '5', 'one hundred and four'):
            result = self.check_output('Start 9:00; an hour and %s quarters of rehearsal; finish 10:00.' % count,
                dict(kind='fits_window', start='09:00', end='10:00', segments_min=[60]))
            self.assertIn('UNSOURCED', result.stdout)

    def test_repeated_number_words_do_not_explode(self):
        result = self.check_output('Start 9:00; an hour and ' + 'twenty one ' * 30 + 'breaks; finish 10:00.',
            dict(kind='fits_window', start='09:00', end='10:00', segments_min=[60]))
        self.assertIn('PASS', result.stdout)

    def test_many_duration_continuations_do_not_rescan_quote(self):
        result = self.check_output('Start 9:00; ' + 'an hour and four breaks; ' * 5000 + 'finish 10:00.',
            dict(kind='fits_window', start='09:00', end='10:00', segments_min=[60]))
        self.assertIn('PASS', result.stdout)

    def test_whitespace_continuation_does_not_backtrack(self):
        result = self.check_output('Start 9:00; an hour' + ' ' * 100000 + 'of rehearsal; finish 10:00.',
            dict(kind='fits_window', start='09:00', end='10:00', segments_min=[60]))
        self.assertIn('PASS', result.stdout)

    def test_fraction_spacing_without_hour_does_not_backtrack(self):
        for fraction in ('half', 'quarter'):
            with self.subTest(fraction=fraction):
                result = self.check_output('Start 9:00; ' + fraction + ' ' * 100000 + 'day; finish 10:00.',
                    dict(kind='fits_window', start='09:00', end='10:00', segments_min=[30]))
                self.assertIn('UNSOURCED', result.stdout)

    def test_fraction_spacing_valid_forms_still_source_duration(self):
        for phrase, minutes in (('half an hour', 30), ('half-hour', 30), ('half hour', 30),
                                ('quarter of an hour', 15), ('quarter-hour', 15),
                                ('quarter hour', 15), ('three quarters of an hour', 45)):
            with self.subTest(phrase=phrase):
                result = self.check_output('Start 9:00; %s; finish 10:00.' % phrase,
                    dict(kind='fits_window', start='09:00', end='10:00', segments_min=[minutes]))
                self.assertIn('PASS', result.stdout)

    def test_many_numeric_tokens_do_not_copy_entire_quote(self):
        result = self.check_output('1 ' * 600000 + 'budget 1000.',
            dict(kind='within_budget', amounts=[50], total_cap=1000))
        self.assertIn('UNSOURCED', result.stdout)

    def test_adjacent_large_minutes_do_not_source_whole_hours(self):
        for count in ('100', 'one hundred', '120', '1000'):
            with self.subTest(count=count):
                result = self.check_output('Start 9:00; 1 hour %s minutes; finish 10:00.' % count,
                    dict(kind='fits_window', start='09:00', end='10:00', segments_min=[60]))
                self.assertIn('UNSOURCED', result.stdout)

    def test_adjacent_non_duration_count_preserves_hours(self):
        result = self.check_output('Start 9:00; 1 hour, 100 guests; finish 10:00.',
            dict(kind='fits_window', start='09:00', end='10:00', segments_min=[60]))
        self.assertIn('PASS', result.stdout)

    def test_numeric_currency_spacing_preserves_negative_sign(self):
        for phrase in ('- € 50', '− £ 50', '- 50', '-$ 50'):
            with self.subTest(phrase=phrase):
                result = self.check_output('Adjustment %s; budget 1000.' % phrase,
                    dict(kind='within_budget', amounts=[50], total_cap=1000))
                self.assertIn('UNSOURCED', result.stdout)

    def test_unsigned_numeric_spacing_and_ranges_remain_sourced(self):
        for phrase in ('$50', '$ 50', '€ 50', '+ £ 50', '30-50', '50'):
            with self.subTest(phrase=phrase):
                result = self.check_output('Fee %s; budget 1000.' % phrase,
                    dict(kind='within_budget', amounts=[50], total_cap=1000))
                self.assertIn('PASS', result.stdout)

    def test_spaced_currency_millions_preserve_complete_value(self):
        for currency in ('$', '€', '£'):
            for amount, expected in ((2.5, 'UNSOURCED'), (2500000, 'PASS')):
                with self.subTest(currency=currency, amount=amount):
                    result = self.check_output('Fee %s 2.5M; budget 10000000.' % currency,
                        dict(kind='within_budget', amounts=[amount], total_cap=10000000))
                    self.assertIn(expected, result.stdout)

    def test_compound_fraction_large_following_minutes_are_unsourced(self):
        for count in ('one hundred', '1000', 'one thousand', '100.5'):
            with self.subTest(count=count):
                result = self.check_output('Start 9:00; one and a half hours and %s minutes of rehearsal; finish 10:30.' % count,
                    dict(kind='fits_window', start='09:00', end='10:30', segments_min=[90]))
                self.assertIn('UNSOURCED', result.stdout)

    def test_negative_standalone_fractions_do_not_source_positive_duration(self):
        for phrase in ('-half an hour', '−half an hour', '- half an hour',
                       '-a half-hour', '-one half hour', '-quarter of an hour',
                       '− three quarters of an hour'):
            with self.subTest(phrase=phrase):
                minutes = 45 if 'three' in phrase else 15 if 'quarter' in phrase else 30
                result = self.check_output('Start 9:00; %s; finish 10:30.' % phrase,
                    dict(kind='fits_window', start='09:00', end='10:30', segments_min=[minutes]))
                self.assertIn('UNSOURCED', result.stdout)

    def test_compound_fraction_non_duration_continuation_stays_sourced(self):
        result = self.check_output('Start 9:00; one and a half hours and one hundred guests; finish 10:30.',
            dict(kind='fits_window', start='09:00', end='10:30', segments_min=[90]))
        self.assertIn('PASS', result.stdout)

    def test_standalone_fraction_large_following_minutes_are_unsourced(self):
        for phrase, minutes in (('half an hour', 30), ('quarter of an hour', 15)):
            for count in ('one hundred', '1000'):
                with self.subTest(phrase=phrase, count=count):
                    result = self.check_output('Start 9:00; %s plus %s minutes; finish 10:30.' % (phrase, count),
                        dict(kind='fits_window', start='09:00', end='10:30', segments_min=[minutes]))
                    self.assertIn('UNSOURCED', result.stdout)

    def test_simple_fraction_amount_does_not_source_numerator(self):
        for phrase in ('one-half', 'one half', 'one third', 'one-quarter', 'two fifths'):
            with self.subTest(phrase=phrase):
                n = 2 if phrase.startswith('two') else 1
                result = self.check_output('Fee is %s dollar; cap $10.' % phrase,
                    dict(kind='within_budget', amounts=[n], total_cap=10))
                self.assertIn('UNSOURCED', result.stdout)

    def test_whitespace_numeric_range_keeps_positive_endpoint(self):
        for phrase in ('30 - 50', '30- 50', '30 -50', '30 − 50', '$30 - € 50'):
            with self.subTest(phrase=phrase):
                result = self.check_output('Fee range is %s dollars; cap $100.' % phrase,
                    dict(kind='within_budget', amounts=[50], total_cap=100))
                self.assertIn('PASS', result.stdout)

    def test_comma_continued_minutes_do_not_source_shorter_fraction(self):
        for joining in (', plus ', ', and ', ', ', ' , plus '):
            with self.subTest(joining=joining):
                result = self.check_output('Start 9:00; one and a half hours%sfifteen minutes of rehearsal; finish 10:30.' % joining,
                    dict(kind='fits_window', start='09:00', end='10:30', segments_min=[90]))
                self.assertIn('UNSOURCED', result.stdout)

    def test_non_duration_continuation_preserves_hours(self):
        result = self.check_output('Start 9:00; an hour and four breaks; finish 10:00.',
            dict(kind='fits_window', start='09:00', end='10:00', segments_min=[60]))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS', result.stdout)


    def test_decimal_word_duration_never_sources_suffix(self):
        for phrase in ('two point one hours', 'two point    one hours', 'two dot      one hours', 'two dot one hours', 'two-point-one hours', 'two point 1 hours', 'two point one and a half hours'):
            for minutes in (60, 90):
                with self.subTest(phrase=phrase, minutes=minutes):
                    result = self.check_output('Start 9:00; ' + phrase + ' of rehearsal; finish 10:30.',
                        dict(kind='fits_window', start='09:00', end='10:30', segments_min=[minutes]))
                    self.assertIn('UNSOURCED', result.stdout)

    def test_fraction_duration_tail_never_sources_prefix(self):
        for phrase in ('one and a half hours plus a quarter', 'one and a half hours, and three quarters', 'half an hour plus a half', 'a quarter of an hour and one third'):
            minutes = 90 if phrase.startswith('one') else (30 if phrase.startswith('half') else 15)
            with self.subTest(phrase=phrase):
                result = self.check_output('Start 9:00; ' + phrase + ' of rehearsal; finish 10:30.',
                    dict(kind='fits_window', start='09:00', end='10:30', segments_min=[minutes]))
                self.assertIn('UNSOURCED', result.stdout)

    def test_fraction_tail_with_explicit_own_hour_stays_separate(self):
        result = self.check_output('Start 9:00; one and a half hours plus a quarter-hour break; finish 10:45.',
            dict(kind='fits_window', start='09:00', end='10:45', segments_min=[90,15]))
        self.assertIn('PASS', result.stdout)

    def test_decimal_word_amount_whitespace_does_not_source_suffix(self):
        for phrase in ('two point    one million', 'two dot      one million'):
            result = self.check_output('Fee ' + phrase + '; cap 2000000.',
                dict(kind='within_budget', amounts=[1000000], total_cap=2000000))
            self.assertIn('UNSOURCED', result.stdout)

    def test_unsupported_fraction_does_not_source_inner_hour(self):
        for phrase in ('four thirds of an hour', 'two fifths of an hour', 'four-thirds of an hour', 'seven eighths of an hour', 'one third of an hour', 'two halves of an hour', 'a twelfth of an hour', 'an eleventh of an hour', 'eleven twelfths of an hour', 'five sixteenths of an hour', 'four hundredths of an hour', '11 twelfths of an hour', '4 thirds of a hour', 'one third of one hour', 'four-thirds-of-an-hour', 'two sixths of an hour', '3 sevenths of an hour', 'two ninths of an hour', 'three tenths of an hour', 'four thirds of' + ' ' * 100000 + 'an hour'):
            with self.subTest(phrase=phrase):
                result = self.check_output('Start 9:00; ' + phrase + '; finish 10:00.',
                    dict(kind='fits_window', start='09:00', end='10:00', segments_min=[60]))
                self.assertIn('UNSOURCED', result.stdout)

    def test_fraction_context_keeps_supported_and_independent_hours(self):
        for phrase, minutes in (('half an hour',30),('three quarters of an hour',45),('a quarter of an hour',15),('growth of an hour',60),('discussion of thirds; an hour',60),('four thirds were discussed, then an hour',60)):
            with self.subTest(phrase=phrase):
                result = self.check_output('Start 9:00; '+phrase+'; finish 10:00.',
                    dict(kind='fits_window',start='09:00',end='10:00',segments_min=[minutes]))
                self.assertIn('PASS',result.stdout)

    def test_spaced_signed_hours_never_source_positive_duration(self):
        for sign in ('-', '−'):
            for gap in (' ', '   ', '\t'):
                for phrase, minutes in (('one and a half hours',90),('1 and a half hours',90),('one hour',60),('1 hour',60),('an hour',60),('a hour',60),('1.5 hours',90),('1 hour 15 minutes',75)):
                    with self.subTest(sign=sign,gap=gap,phrase=phrase):
                        result=self.check_output('Start 9:00; duration '+sign+gap+phrase+'; finish 10:30.',
                            dict(kind='fits_window',start='09:00',end='10:30',segments_min=[minutes]))
                        self.assertIn('UNSOURCED',result.stdout)

    def test_compound_fraction_other_unit_never_sources_hours(self):
        for phrase in ('one hour and a quarter of a day', 'one hour and a quarter of one day', 'one hour and a quarter of 2.5 days', 'one hour and a half of an evening', 'one hour and a quarter of a week', 'one hour and a half day', 'one hour and a quarter of a minute'):
            n=90 if 'half' in phrase else 75
            with self.subTest(phrase=phrase):
                result=self.check_output('Start 9:00; '+phrase+' of rehearsal; finish 10:30.',
                    dict(kind='fits_window',start='09:00',end='10:30',segments_min=[n]))
                self.assertIn('UNSOURCED',result.stdout)

    def test_decimal_word_minute_continuation_never_sources_prefix(self):
        for phrase in ('one hour and two point five minutes','one hour plus two dot five minutes','one hour and two-point-five minutes','one and a half hours and two point five minutes','half an hour plus two point five minutes'):
            n=90 if phrase.startswith('one and') else 30 if phrase.startswith('half') else 60
            with self.subTest(phrase=phrase):
                result=self.check_output('Start 9:00; '+phrase+'; finish 10:30.',
                    dict(kind='fits_window',start='09:00',end='10:30',segments_min=[n]))
                self.assertIn('UNSOURCED',result.stdout)

    def test_complete_fraction_hours_keep_activity_context(self):
        for phrase,n in (('one and a half hours of rehearsal',90),('two and a half hours of work',150)):
            result=self.check_output('Start 9:00; '+phrase+'; finish 12:00.',
                dict(kind='fits_window',start='09:00',end='12:00',segments_min=[n]))
            self.assertIn('PASS',result.stdout)


if __name__ == '__main__':
    unittest.main()
