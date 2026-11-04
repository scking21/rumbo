#!/usr/bin/env python3
"""rumbo record tool. Python 3.9+, standard library only.

Subcommands: validate, check, show, init, stop-gate, pre-write.
Exit codes: 0 clean, 1 content problem, 2 tool or I/O problem.
"""

import argparse
import decimal
import datetime
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile

DEFAULT_RECORD = os.path.join(".rumbo", "record.json")

STATUSES = [
    "exploring",
    "preference",
    "draft",
    "commitment",
    "authorized",
    "deferred",
    "rejected",
    "done",
    "uncertain",
]

STATUS_ORDER = [
    "commitment",
    "authorized",
    "draft",
    "preference",
    "exploring",
    "deferred",
    "uncertain",
]

CHECK_KINDS = ["fits_window", "before", "within_budget"]

TRUNCATION_MARKER = "…(truncated)"

NUDGE_TEMPLATE = (
    'rumbo: no decision record yet. If this is multi-step work with '
    'decisions, times, dates or money, start one (see the commitments skill):\n'
    'python3 "%s" init --record "%s" --objective "<goal>" --quote - <<\'QUOTE\'\n'
    "<the user's own words>\n"
    "QUOTE"
)

PLANNING_PATTERN = re.compile(
    r"\b\d{1,2}:\d{2}\b"
    r"|\$\s?\d"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
    r"|\b(plan|planning|schedule|budget|deadline|decide|decision|agenda|itinerary|timeline)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- loading


class LoadError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code  # "RECORD_NOT_FOUND" or "RECORD_UNREADABLE"


MAX_JSON_DEPTH = 64


def _loads(raw):
    """json.loads with an explicit nesting bound; deeper input raises ValueError.

    The decoder's own depth limit is a CPython detail (3.14 raises
    RecursionError, not ValueError), so depth is checked before decoding.
    """
    depth = 0
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds limit")
        elif char in "]}":
            depth -= 1
    try:
        return json.loads(raw)
    except RecursionError:
        raise ValueError("JSON nesting exceeds limit") from None


def load_record(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except FileNotFoundError:
        raise LoadError("RECORD_NOT_FOUND")
    except (OSError, UnicodeDecodeError):
        raise LoadError("RECORD_UNREADABLE")
    try:
        return _loads(raw)
    except ValueError:
        raise LoadError("RECORD_UNREADABLE")


# --------------------------------------------------------------- helpers


def _is_number(value):
    return (isinstance(value, int) and not isinstance(value, bool)
            or isinstance(value, float) and math.isfinite(value))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def fmt_num(value):
    if isinstance(value, decimal.Decimal):
        text = format(value, 'f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return "%g" % value


def _source_text(record, check):
    """Return objective and active referenced item quotes for this check.

    Missing/null refs retain the legacy fallback to all active items; an empty
    list selects no items. Done, rejected, and replaced history never sources a
    current check, even when explicitly referenced.
    """
    quotes = [record["objective"]["quote"]]
    items = record.get("items") or []
    replaced = {ref for item in items for ref in item.get("replaces") or []}
    refs = check.get("refs")
    for item in items:
        if item["status"] in ("done", "rejected") or item["id"] in replaced:
            continue
        if refs is not None and item["id"] not in refs:
            continue
        quotes.append(item["quote"])
    return "\n".join(quotes)


UNIT_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS_WORDS = {w: 10 * i for i, w in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
SCALE_WORDS = {"thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9}
# Written after a number: "$1.5k", "1.8 million", "$2.5M" (bare "5m" is meters or minutes).
SCALE_SUFFIX = re.compile(r"(?:\s*(thousand|million|billion)\b|([kK])\b|([mM]|bn)\b)", re.IGNORECASE)


def _word_numbers(text):
    """Yield (start, end, Decimal) for each spelled cardinal number in text.

    "twenty-five", "four hundred fifty", "one hundred and twenty", "a thousand",
    "five thousand", "fifteen hundred". Two units or two tens in a row end a number
    ("five six" is 5 and 6), and "and" joins only after hundred or a scale word. A
    "hundred" or scale word that cannot attach makes the whole number state nothing.
    """
    tokens = [(m.group(0).lower(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z]+", text)]
    i = 0
    while i < len(tokens):
        word, start, end = tokens[i]
        # "a thousand" is 1000 only when nothing but spaces separates the words: in "a $5
        # thousand fee" the article is not a number.
        article = (word in ("a", "an") and i + 1 < len(tokens) and tokens[i + 1][0] in ("hundred", *SCALE_WORDS)
                   and re.fullmatch(r"\s+", text[end:tokens[i + 1][1]]) is not None)
        if word not in UNIT_WORDS and word not in TENS_WORDS and not article:
            i += 1
            continue
        total, current, last, j, stop, stuck = 0, 0, None, i, end, False
        if article:
            current, last, j = 1, "unit", i + 1
        while j < len(tokens):
            word, w_start, w_end = tokens[j]
            gap = text[stop:w_start] if j > i else ""
            if j > i and not re.fullmatch(r"\s+|\s*-\s*", gap):
                break
            if word in UNIT_WORDS:
                value = UNIT_WORDS[word]
                if last == "unit" or (last == "tens" and value >= 10) or last == "tens+unit":
                    break
                last = "tens+unit" if last == "tens" else "unit"
                current += value
            elif word in TENS_WORDS:
                if last in ("unit", "tens", "tens+unit"):
                    break
                current += TENS_WORDS[word]
                last = "tens"
            elif word == "hundred":
                # "five hundred", and the colloquial "fifteen hundred" (1500) and
                # "twenty-five hundred" (2500).
                if last not in ("unit", "tens", "tens+unit") or not 1 <= current <= 99:
                    stuck = True
                    break
                current *= 100
                last = "hundred"
            elif word in SCALE_WORDS:
                if last is None or last == "scale" or current == 0:
                    stuck = True
                    break
                total += current * SCALE_WORDS[word]
                current, last = 0, "scale"
            elif word == "and" and last in ("hundred", "scale") and j + 1 < len(tokens) \
                    and (tokens[j + 1][0] in UNIT_WORDS or tokens[j + 1][0] in TENS_WORDS):
                pass
            else:
                break
            stop = w_end
            j += 1
        # A number the parser cannot finish ("twelve hundred thousand thousand") states
        # nothing: never source its prefix.
        if last is not None and not stuck:
            yield start, stop, decimal.Decimal(total + current)
        i = max(j + (1 if stuck else 0), i + 1)


# A number the user continued with a fraction ("one and a half thousand", "1 point 5
# million", "three quarters") was not stated as that number: it sources nothing as an
# amount.
AMOUNT_CONTINUED = re.compile(
    r"[\s-]+(?:and[\s-]+(?:an?|one|two|three)[\s-]+(?:half|halves|quarters?|thirds?)\b|(?:point|dot)\b"
    r"|(?:halves|quarters|thirds|fifths|eighths)\b)",
    re.IGNORECASE)
# Nor is the part after a spelled decimal point: "five million" in "one point five million".
AMOUNT_AFTER_POINT = re.compile(r"\b(?:point|dot)[\s-]+$", re.IGNORECASE)
# A scaled amount that runs into another number is one amount, "1 million 500 thousand"
# (1500000), "1 million five hundred thousand" or "2 thousand 500 dollars" (2500): no
# group is the user's amount alone, in digits or words.
_SPELLED = "|".join(sorted(list(UNIT_WORDS) + list(TENS_WORDS), key=len, reverse=True))
SCALED_CONTINUED = re.compile(
    r"[\s,]*(?:and\s+)?(?:\d+(?:\.\d+)?|(?:%s)(?:[\s-]+(?:%s|hundred|and))*)"
    r"\s*(?:thousand|million|billion|hundred|k\b|dollars?|euros?|pounds?|bucks)" % (_SPELLED, _SPELLED),
    re.IGNORECASE)
AFTER_SCALE = re.compile(r"\b(?:thousand|million|billion)[\s,]*(?:and\s+)?$", re.IGNORECASE)


def _is_number_sourced(num, source_text):
    """Return True if num is sourced in source_text per spec.
    The amount 0 is always sourced.
    """
    if num == 0:
        return True
    # Remove commas from source text for number matching
    no_commas = source_text.replace(",", "")
    # Compare values, not text: sign kept, trailing zeros equal ("$1.50" is 1.5), no
    # rounding. Digits next to ":" belong to a time, so "9:45" does not source 45; an
    # exponent stays part of its number, so "1e3" sources 1000, not 1 or 3.
    target = decimal.Decimal(str(num))
    for match in re.finditer(r"(?<![\d.:])(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)(?![\d:]|\.\d)", no_commas):
        value = decimal.Decimal(match.group(1))
        if (AMOUNT_CONTINUED.match(no_commas, match.end())
                or AMOUNT_AFTER_POINT.search(no_commas[max(0, match.start() - 8):match.start()])
                or AFTER_SCALE.search(no_commas[max(0, match.start() - 16):match.start()])):
            continue
        # Only the last few characters matter; a leading space stands for the start.
        before = (" " + no_commas)[max(0, match.start() - 2):match.start() + 1]
        # "$1.5k" is 1500 and "1.8 million" is 1800000, never 1.5 or 1.8. A bare "M"
        # scales only after a currency sign: "$2.5M" is money, "5m" is a length.
        scale = SCALE_SUFFIX.match(no_commas, match.end())
        if scale and (scale.group(1) or scale.group(2) or re.search(r"[$\u20ac\u00a3]$", before)):
            word = (scale.group(1) or scale.group(2) or scale.group(3)).lower()
            value *= {"k": 1000, "m": 10 ** 6, "bn": 10 ** 9}.get(word) or SCALE_WORDS[word]
            # "1 thousand and a half" is 1500 and "1 million 500 thousand" 1500000, not
            # 1000 or 1000000: check again after the scale.
            if AMOUNT_CONTINUED.match(no_commas, scale.end()) or SCALED_CONTINUED.match(no_commas, scale.end()):
                continue
        # A minus sign (or "-$", "-\u20ac") not preceded by a digit negates; "30-50" stays a range.
        if re.search(r"(?:^|[^\d])[-\u2212][$\u20ac\u00a3]?$", before):
            value = -value
        if value == target:
            return True
    # Spelled numbers: "twelve", "four hundred fifty dollars", "five thousand".
    for start, end, value in _word_numbers(source_text):
        ends_scaled = re.search(r"(?:thousand|million|billion)$", source_text[start:end], re.IGNORECASE)
        if (AMOUNT_CONTINUED.match(source_text, end)
                or AMOUNT_AFTER_POINT.search(source_text[max(0, start - 8):start])
                or AFTER_SCALE.search(source_text[max(0, start - 16):start])
                or (ends_scaled and SCALED_CONTINUED.match(source_text, end))):
            continue
        before = source_text[max(0, start - 8):start]
        if re.search(r"[-\u2212]\s*$", before) and not re.search(r"[A-Za-z]-\s*$", before):
            value = -value
        if value == target:
            return True
    return False


HOUR_UNIT = r"(?:hours?\b|hrs?\b\.?|h(?=\d{2}(?:m\b|\b))|h\b\.?)"
MINUTE_UNIT = r"(?:minutes?|mins?|m)\b\.?"
NUMBER_WORD = r"(?:%s)(?:[\s-]+(?:%s))?" % ("|".join(sorted(TENS_WORDS, key=len, reverse=True)),
                                              "|".join(sorted(UNIT_WORDS, key=len, reverse=True)))
NUMBER_WORD = r"(?:%s|%s)" % (NUMBER_WORD, "|".join(sorted(UNIT_WORDS, key=len, reverse=True)))


def _amount(text):
    """Decimal value of a digit string or a spelled number, or None."""
    text = text.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return decimal.Decimal(text)
    if text.lower() in ("a", "an"):
        return decimal.Decimal(1)
    found = list(_word_numbers(text))
    if len(found) == 1 and found[0][0] == 0 and found[0][1] == len(text):
        return found[0][2]
    return None


def _stated_minutes(source_text):
    """Yield every duration, in minutes, that source_text states in hours.

    "2-hour", "1.5 hours", "2h", "two hours", "an hour", "half an hour",
    "a half-hour", "a quarter of an hour", "three quarters of an hour",
    "an hour and a half", "2 and a half hours", "1 hour 15 minutes", "2h30".
    A range ("1-2 hours"), a signed value or part of a longer token ("1e2 hours",
    "v2 hours") states nothing, and neither does a rate or frequency ("$150 an
    hour", "$150 per half hour", "every 2 hours"). Hours
    followed by "and a half" or "and a quarter" never state the whole hours alone.
    """
    flags = re.IGNORECASE
    num = r"(\d+(?:\.\d+)?|%s|an?)" % NUMBER_WORD
    lead = r"(?<![\w.:,\u2212-])"
    text = source_text

    def is_rate(start, after_price):
        # A price or frequency names a rate, not a duration: "$150 an hour", "fifty
        # dollars an hour", "$150 per half hour", "a shuttle every hour", "twice an
        # hour", "3 times an hour", "$20/half hour".
        # A price directly before counts only for a phrase without its own number, and
        # only with evidence it is a price: a currency sign ("$150 a half hour"), a
        # currency word ("fifty dollars an hour") or an article ("150 an hour"). A bare
        # count is not a price ("two half-hour sessions"), nor are clock digits ("9:00").
        before = text[max(0, start - 48):start]
        markers = r"(?:\bper|\bevery|\bonce|\btwice|\bthrice|\btimes|/)\s*(?:an?\s+)?"
        if after_price:
            amount = r"(?:(?<![\d:.])\d+(?:\.\d+)?[kK]?|\b%s(?:[\s-]+(?:%s|hundred|thousand|and))*)" % (
                NUMBER_WORD, NUMBER_WORD)
            currency = r"\s*(?:dollars?|bucks|euros?|pounds?|quid|usd|eur|gbp|cents?)\b"
            markers += (r"|[$\u20ac\u00a3]\s*\d+(?:\.\d+)?[kK]?(?:%s)?\s*(?:an?\s+)?" % currency
                        + r"|%s%s\s*(?:an?\s+)?" % (amount, currency)
                        + r"|%s\s+an?\s+" % amount)
        return re.search(r"(?:%s)$" % markers, before, flags) is not None

    def is_part(m):
        # The "an hour" inside "half an hour" or "a quarter of an hour" is not 60.
        return re.search(r"(?:half|quarters?(?:\s+of)?)\s*$", text[max(0, m.start() - 24):m.start()], flags) is not None

    # A spelled count must be the user's whole number: "one hours" inside "one hundred
    # and one hours" is not 1. Digits and "a"/"an" stand alone.
    whole_numbers = {(start, end) for start, end, _ in _word_numbers(text)}

    def is_whole(m, group):
        word = m.group(group)
        return (word is None or word.lower() in ("a", "an") or re.fullmatch(r"[\d.]+", word) is not None
                or (m.start(group), m.end(group)) in whole_numbers)

    def has_fraction(m):
        # Whole hours that the user continued ("an hour and three quarters", "1 hour and
        # 20", "2 hours plus a third") never state the whole hours alone; the full phrase
        # is read below when it can be, and otherwise states nothing.
        # A fraction with its own singular "hour" ("1 hour, and a half-hour break") is a
        # separate duration, not a continuation.
        return re.match(r"\s*,?\s*(?:and|plus)[\s-]+(?:(?:(?:an?|one|two|three)[\s-]+)?(?:half|halves|quarters?|thirds?)\b"
                        r"(?![\s-]+(?:of[\s-]+an?[\s-]+)?hour\b)"
                        r"|(?:\d+|%s)\s*(?:[,.;)]|$|minutes?\b|mins?\b))" % NUMBER_WORD,
                        text[m.end():m.end() + 40], flags) is not None

    # Every duration phrase is a candidate span with its minutes, or None when it is a
    # rate or otherwise states nothing. Only the longest phrases count: a span inside a
    # longer one ("half-hour" in "two-and-a-half-hour", "an hour" in "half an hour")
    # is part of it, never a duration of its own.
    found = []

    def continues(start):
        # A fraction after "word-" ("two-and-a-half-hour"), or after "and" that follows a
        # number ("one hundred and a half hour"), belongs to a longer phrase. After any
        # other "and" it is a duration of its own ("a talk and a half-hour break", "1 hour
        # and a half-hour break": these phrases carry their own "hour").
        return re.search(r"(?:[A-Za-z]-|(?:\d|\b(?:%s|hundred|thousand))[\s-]+and[\s-]+(?:an?[\s-]+)?)$"
                         % NUMBER_WORD, text[max(0, start - 40):start], flags) is not None

    # Hours, optionally followed by minutes: "2 hours", "an hour 15 minutes", "2h30".
    for m in re.finditer(lead + num + r"[\s-]*" + HOUR_UNIT
                         + r"(?:[\s,]*(?:(?:and|plus)\s+)?(\d{1,2}|%s)[\s-]*%s|(?<=h)(\d{2})\b)?" % (NUMBER_WORD, MINUTE_UNIT),
                         text, flags):
        hours = _amount(m.group(1))
        article = m.group(1).lower() in ("a", "an")
        extra = m.group(2) or m.group(3)
        value = None
        if not (hours is None or not is_whole(m, 1) or not is_whole(m, 2) or has_fraction(m)
                or is_rate(m.start(), article) or (article and is_part(m))):
            # "1 hour 15 minutes" states 75, never the whole hours alone.
            value = hours * 60 if extra is None else (None if _amount(extra) is None else hours * 60 + _amount(extra))
        found.append((m.start(), m.end(), value))
    # "an hour and a half", "2 and a half hours", "two-and-a-half-hour",
    # "an hour and a quarter", "an hour and three quarters".
    # The fraction comes from its words: "a half" 30, "a quarter" 15, "three quarters"
    # or "three-quarter" 45, whether "quarter" is singular or plural.
    for m in re.finditer(lead + num + r"[\s-]+(?P<unit>hours?[\s-]+)?and[\s-]+(?P<top>an?|three)[\s-]+"
                         r"(?P<part>half|quarters?)\b(?P<tail>[\s-]+(?:of[\s-]+an?[\s-]+)?hours?\b)?", text, flags):
        if m.group("unit") and m.group("tail") and not m.group("tail").lower().endswith("hours"):
            # "1 hour and a half-hour break" names two durations, each with its own unit.
            continue
        tail = m.group(0).lower()
        hours = _amount(m.group(1))
        top, part = m.group("top").lower(), m.group("part").lower()
        other_unit = re.match(r"[\s-]+(?:days?|weeks?|months?|years?|nights?|minutes?|mins?|seconds?|secs?)\b",
                              text[m.end():m.end() + 20], flags) is not None
        if top == "three":
            fraction = 45 if part.startswith("quarter") else None
        else:
            fraction = {"half": 30, "quarter": 15}.get(part)
        if fraction is None or other_unit:
            # "two hours and a half day", "an hour and three halves": state nothing.
            found.append((m.start(), m.end(), None))
            continue
        ok = ("hour" in tail and hours is not None and is_whole(m, 1)
              and not is_rate(m.start(), m.group(1).lower() in ("a", "an")))
        found.append((m.start(), m.end(), hours * 60 + fraction if ok else None))
    for m in re.finditer(r"\b(?:(?:a|one)\s+)?half(?:\s+an?|-|\s+)?\s*hour\b", text, flags):
        ok = not is_rate(m.start(), True) and not continues(m.start())
        found.append((m.start(), m.end(), decimal.Decimal(30) if ok else None))
    # "a quarter-hour" and "a quarter of an hour" are 15; "three-quarter hour" and "three
    # quarters of an hour" are 45; "three quarter-hour breaks" are three of 15 (the count
    # is not this phrase's); "three quarter hour", with no hyphen to tell, states nothing.
    for m in re.finditer(r"\b(?:(?:a|one)\s+)?(?:(?P<three>three)(?P<join>[\s-]+))?(?P<part>quarters?)"
                         r"(?P<sep>\s+of\s+an?\s+|\s*-\s*|\s+)hour\b", text, flags):
        plural = m.group("part").lower() == "quarters"
        if m.group("three"):
            if "-" in m.group("join") or plural:
                minutes = 45
            elif "-" in m.group("sep"):
                minutes = 15
            else:
                minutes = None
        else:
            minutes = None if plural else 15
        ok = minutes is not None and not is_rate(m.start(), True) and not continues(m.start())
        found.append((m.start(), m.end(), decimal.Decimal(minutes) if ok else None))

    # Sweep in start order (longest first at a tie): a span is inside a longer one when
    # an earlier span reaches past its end, or reaches its end from an earlier start.
    # A phrase followed by minutes it did not read ("one and a half hours and fifteen
    # minutes") is not the user's whole duration, whatever its form: it states nothing.
    more_minutes = re.compile(r"\s+(?:and\s+|plus\s+)?(?:\d{1,3}|%s)[\s-]*(?:minutes?|mins?)\b" % NUMBER_WORD, flags)
    best_end, best_start = -1, -1
    for start, end, value in sorted(found, key=lambda span: (span[0], -span[1])):
        inside = best_end > end or (best_end == end and best_start < start)
        if end > best_end:
            best_end, best_start = end, start
        if not inside and value is not None and not more_minutes.match(text, end):
            yield value


def _is_minutes_sourced(minutes, source_text):
    """True when a duration in minutes is stated in minutes or in hours ("2-hour", "an hour and a half")."""
    if _is_number_sourced(minutes, source_text):
        return True
    return any(value == minutes for value in _stated_minutes(source_text))


def _is_time_sourced(time_str, source_text):
    """Return True if time_str (HH:MM) is sourced in source_text.
    Parse the check time as (h, m) from "HH:MM"; return False if malformed.
    Find time tokens with re.finditer("(?<![0-9:])([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?(?![0-9]|:[0-9])(?:\\s*([AaPp])\\.?\\s*[Mm]\\b\\.)?", text).
    Skip a token whose seconds group is present and not "00". Meridiem: p/P and hour < 12 -> hour + 12; a/A and hour == 12 -> 0. Skip hours > 23 or minutes > 59.
    Sourced if any token's (hour, minute) == (h, m).
    """
    if not isinstance(time_str, str):
        return False
    parts = time_str.split(":")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        return False
    h = int(parts[0])
    m = int(parts[1])
    if h > 23 or m > 59:
        return False

    # Find time tokens with the specified regex
    for match in re.finditer(r"(?<![0-9:])([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?(?![0-9]|:[0-9])(?:\s*([AaPp])\.?\s*[Mm]\b\.?)?", source_text):
        hour_group = match.group(1)
        minute_group = match.group(2)
        seconds_group = match.group(3)
        meridiem_group = match.group(4)

        # Skip if seconds group is present and not "00"
        if seconds_group is not None and seconds_group != "00":
            continue

        try:
            hour = int(hour_group)
            minute = int(minute_group)
        except ValueError:
            continue

        # Apply meridiem correction
        if meridiem_group:
            meridiem = meridiem_group.lower()
            if meridiem.startswith('p') and hour < 12:
                hour += 12
            elif meridiem.startswith('a') and hour == 12:
                hour = 0

        # Skip hours > 23 or minutes > 59 after meridiem correction
        if hour > 23 or minute > 59:
            continue

        # Check if this token matches the target time
        if hour == h and minute == m:
            return True

    if m == 0:
        # "9am", "9 p.m.": an hour with a meridiem and no minutes.
        for match in re.finditer(r"(?<![0-9:.$])([0-9]{1,2})\s*([AaPp])\.?\s*[Mm]\b", source_text):
            hour = int(match.group(1))
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if match.group(2).lower() == "p" else 0)
            if hour == h:
                return True
        if h in (0, 12) and re.search(r"\bmidnight\b" if h == 0 else r"\bnoon\b", source_text, re.IGNORECASE):
            return True

    return False


MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def _is_date_sourced(date_str, source_text):
    """Return (month_day_sourced, year_sourced) for a YYYY-MM-DD or MM-DD date.

    Month-day is sourced by the month name or its abbreviation with the day in
    either order ("March 20", "Mar. 20th", "20 March", "the 20th of March"), by
    "03-20", or by the two numbers around a slash ("3/20" or "20/3": the values
    are the user's, the reading is the agent's). The year only by the 4-digit
    year. An MM-DD date has no year, so year_sourced is False.
    """
    date = parse_date(date_str)
    if date is None:
        return (False, False)
    name = MONTHS[date.month - 1]
    sept = r"|Sept\.?" if date.month == 9 else ""
    month = rf"(?:{name}|{name[:3]}\.?{sept})"
    day = rf"0?{date.day}(?:st|nd|rd|th)?"
    other = r"\d{1,2}(?:st|nd|rd|th)?"
    dash = r"\s*[-\u2013\u2014]\s*"
    any_month = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
                 r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?(?![a-z])")
    patterns = [
        rf"\b{month}\s+{day}\b",
        rf"(?<![\d/.:-]){day}\s+(?:of\s+)?{month}(?![a-z])",
        # Both ends of a range, never the days between: "June 3-5", "12–14 July". An end
        # takes the shared month only when the other end has none of its own, so "June
        # 30–2 July" is June 30 and July 2, never June 2 or July 30.
        rf"\b{month}\s+{day}{dash}{other}\b",
        rf"\b{month}\s+{other}{dash}{day}\b(?!\s+(?:of\s+)?{any_month})",
        rf"(?<![\d/.:-]){day}{dash}{other}\s+(?:of\s+)?{month}(?![a-z])",
        rf"(?<![\d/.:-]){other}{dash}{day}\s+(?:of\s+)?{month}(?![a-z])",
        rf"\b{date.month:02d}-{date.day:02d}\b",
        rf"(?<![\d/.:-])0?{date.month}/0?{date.day}(?!\d)",
        rf"(?<![\d/.:-])0?{date.day}/0?{date.month}(?!\d)",
    ]
    month_day = False
    for index, pattern in enumerate(patterns):
        for found in re.finditer(pattern, source_text, re.IGNORECASE):
            # The start of a day-first range must not carry a month of its own.
            if index == 4 and re.search(rf"{any_month}\s*$", source_text[max(0, found.start() - 12):found.start()],
                                        re.IGNORECASE):
                continue
            month_day = True
            break
        if month_day:
            break
    year = _has_year(date_str) and re.search(rf"(?<!\d){date.year}(?!\d)", source_text) is not None
    return (month_day, year)


def unsourced_values(record, check):
    """Return list of strings naming each unsourced value in check.
    Assumes record is valid.
    """
    source = _source_text(record, check)
    kind = check["kind"]
    unsourced = []

    if kind == "fits_window":
        # start HH:MM
        if not _is_time_sourced(check["start"], source):
            unsourced.append(f"start {check['start']}")
        # end HH:MM
        if not _is_time_sourced(check["end"], source):
            unsourced.append(f"end {check['end']}")
        # segments_min N for each segment
        for seg in check["segments_min"]:
            if not _is_minutes_sourced(seg, source):
                unsourced.append(f"segments_min {fmt_num(seg)}")

    elif kind == "before":
        for field in ("first", "second"):
            date_val = check[field]
            month_day_sourced, year_sourced = _is_date_sourced(date_val, source)
            if not month_day_sourced:
                unsourced.append(f"{field} month-day {date_val}")
            if _has_year(date_val) and not year_sourced:
                unsourced.append(f"{field} year {date_val[:4]}")

    elif kind == "within_budget":
        # amounts N for each amount
        for amt in check["amounts"]:
            if isinstance(amt, dict):
                # The script multiplies; the user must have said both factors.
                for key in ("unit", "quantity"):
                    if not _is_number_sourced(amt[key], source):
                        unsourced.append(f"amounts {key} {fmt_num(amt[key])}")
            elif not _is_number_sourced(amt, source):
                unsourced.append(f"amounts {fmt_num(amt)}")
        # total_cap N
        cap = check["total_cap"]
        if not _is_number_sourced(cap, source):
            unsourced.append(f"total_cap {fmt_num(cap)}")
        # item_cap N if present
        item_cap = check.get("item_cap")
        if item_cap is not None and not _is_number_sourced(item_cap, source):
            unsourced.append(f"item_cap {fmt_num(item_cap)}")

    return unsourced


def parse_time(text):
    """Return minutes since midnight, or None when malformed."""
    if not isinstance(text, str):
        return None
    parts = text.split(":")
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
        return None
    if not (parts[0].isdecimal() and parts[1].isdecimal()):
        return None
    hours = int(parts[0])
    minutes = int(parts[1])
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def fmt_minutes(total):
    """Clock time for minutes since the first midnight: "12:35", "01:30 next day"."""
    days, minutes = divmod(total, 24 * 60)
    text = "%02d:%02d" % divmod(minutes, 60)
    if days == 1:
        text += " next day"
    elif days > 1:
        text += " %d days later" % days
    return text


def parse_date(text, leap=False):
    """Return a date, or None when malformed.

    MM-DD dates (no year stated) compare within reference year 2001, or within
    leap year 2000 when either date in the comparison is 02-29, which the user
    may state without a year.
    """
    if not isinstance(text, str):
        return None
    candidate = text if _has_year(text) else ("2000-" if leap or text == "02-29" else "2001-") + text
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        return None
    try:
        return datetime.date.fromisoformat(candidate)
    except ValueError:
        return None


def _has_year(text):
    return isinstance(text, str) and len(text) == 10


INJECTED_OPENING = re.compile(
    r"\s*<(system-reminder|ci-monitor-event|create-pr-command|local-command-stdout)(?=[\s>])[^<>]*>")


def _without_injected(text):
    start = 0
    while True:
        opening = INJECTED_OPENING.match(text, start)
        closing = text.find("</%s>" % opening.group(1), opening.end()) if opening else -1
        if closing < 0:
            return text[start:].strip()
        start = closing + len(opening.group(1)) + 3


def _dialog_words(entry, content, asked):
    result = entry["toolUseResult"]
    if not isinstance(result, dict) or "afkTimeoutMs" in result or not isinstance(content, list):
        return []
    decision = entry.get("permissionDecision")
    if isinstance(decision, dict) and decision.get("source") == "hook":
        return []
    if not any(isinstance(block, dict) and block.get("type") == "tool_result"
               and isinstance(block.get("tool_use_id"), str) and block["tool_use_id"] in asked
               for block in content):
        return []
    words = [result.get("response")]
    answers = result.get("answers")
    annotations = result.get("annotations")
    if isinstance(answers, dict):
        for value in answers.values():
            words.extend(value if isinstance(value, list) else [value])
    if isinstance(annotations, dict):
        words.extend(note.get("notes") for note in annotations.values() if isinstance(note, dict))
    return [word for word in words if isinstance(word, str) and word.strip() and word != "(notes only)"]


def _is_human(origin):
    return isinstance(origin, dict) and origin.get("kind") == "human"


def _not_the_users(entry):
    return entry.get("isMeta") or entry.get("isCompactSummary") or entry.get("promptRewritten")


def _message_text(content):
    if isinstance(content, str):
        return _without_injected(content)
    if not isinstance(content, list):
        return ""
    parts = [_without_injected(block["text"]) for block in content
             if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)]
    return "\n".join(part for part in parts if part)


def user_messages(transcript_path):
    """Read transcript JSONL and return list of user message texts.

    Skips lines that are not valid JSON. Keeps an entry only if:
    - entry["type"] == "user"
    - not _not_the_users(entry)
    - if entry has "origin", origin.get("kind") == "human"
    - "toolUseResult" not in entry; one that answers an earlier AskUserQuestion
      call instead adds each thing the user picked or typed (see _dialog_words)
    Text: message.content if it is a str, else concatenation (joined with "\n")
    of the "text" of every block whose type is "text" (skip tool_result, image, others),
    each with its leading injected blocks removed (see _without_injected).
    A queued_command attachment with commandMode "prompt", a human origin and
    not _not_the_users is a prompt typed while the agent worked, and adds its
    text the same way.
    Skip empty texts. Missing/unreadable file -> return None (distinct from []).
    """
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except (OSError, ValueError):
        return None

    messages = []
    asked = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = _loads(line)
        except ValueError:
            # Skip invalid JSON lines
            continue

        if not isinstance(entry, dict):
            continue
        attachment = entry.get("attachment")
        if entry.get("type") == "attachment" and isinstance(attachment, dict):
            if (attachment.get("type") == "queued_command" and attachment.get("commandMode") == "prompt"
                    and _is_human(attachment.get("origin")) and not _not_the_users(attachment)):
                messages.append(_message_text(attachment.get("prompt")))
            continue

        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")

        if entry.get("type") == "assistant" and isinstance(content, list):
            asked.update(block["id"] for block in content
                         if isinstance(block, dict) and block.get("type") == "tool_use"
                         and block.get("name") == "AskUserQuestion" and isinstance(block.get("id"), str))
        if entry.get("type") != "user" or _not_the_users(entry):
            continue
        origin = entry.get("origin")
        if origin is not None and not _is_human(origin):
            continue
        if "toolUseResult" in entry:
            messages.extend(_dialog_words(entry, content, asked))
            continue

        messages.append(_message_text(content))

    return [text for text in messages if text]


def _normalize(text):
    """Collapse every run of whitespace to one space, strip."""
    return re.sub(r"\s+", " ", text).strip()


TYPOGRAPHY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u201c": '"', "\u201d": '"'})


def _fold(text):
    """_normalize, with typographic quotes and apostrophes as ASCII and runs of dots as one ellipsis.

    Editors and chat apps swap these silently; none of them changes what was said.
    Dots fold toward the ellipsis character because a pause does not end a
    clause: "Do not ... spend $900" stays negated.
    """
    return _normalize(re.sub(r"\.{2,}", "\u2026", text.translate(TYPOGRAPHY)))


NEGATION = re.compile(r"\b(?:not|no|never|\w+n't|dont|cannot|without|avoid|neither|nor|nobody|none|nothing)\b", re.IGNORECASE)


def _quote_in(quote, message, ignore_negation=False):
    """True when quote occurs in message as whole tokens and is not negated in its clause.

    Lexical, not semantic: "$900" does not match inside "$9000" or "$900.50", and
    "spend $900" does not match "Do not spend $900".
    """
    if not quote:
        return False
    pattern = r"(?<!\w)(?<!\d[.,])" + re.escape(quote) + r"(?!\w|[.,]\d)"
    for match in re.finditer(pattern, message):
        # A sign in front of a quoted number changes its value: "-$900" is not "$900".
        if re.search(r"(?:^|[^\d])[-\u2212]\$?$", message[:match.start()]):
            continue
        clause = re.split(r"[.!?;:\n]", message[:match.start()])[-1]
        if ignore_negation or not NEGATION.search(clause[-40:]):
            return True
    return False


def _unverified_line(record, path, messages):
    """The UNVERIFIED diagnostic for path, saying whether a negation or absence caused it."""
    match = re.fullmatch(r"items\[(\d+)\]\.quote", path)
    source = record["items"][int(match.group(1))] if match else record["objective"]
    quote = _fold(source.get("quote") or "")
    if any(_quote_in(quote, _fold(message), ignore_negation=True) for message in messages):
        return ("%s: UNVERIFIED: these words follow a negation in the same clause of the user's "
                "message; if the user did say this, quote the whole sentence" % path)
    return "%s: UNVERIFIED: quote not found in the user's messages" % path


def unverified_quotes(record, messages):
    """Return list of JSON paths whose folded quote is not found by _quote_in
    in any single folded message.
    """
    normalized_messages = [_fold(m) for m in messages]
    unverified = []

    # Check objective quote
    objective = record.get("objective")
    if objective and isinstance(objective, dict):
        quote = objective.get("quote")
        if isinstance(quote, str):
            norm_quote = _fold(quote)
            if not any(_quote_in(norm_quote, norm_msg) for norm_msg in normalized_messages):
                unverified.append("objective.quote")

    # Check item quotes
    items = record.get("items") or []
    for i, item in enumerate(items):
        if isinstance(item, dict):
            quote = item.get("quote")
            if isinstance(quote, str):
                norm_quote = _fold(quote)
                if not any(_quote_in(norm_quote, norm_msg) for norm_msg in normalized_messages):
                    unverified.append(f"items[{i}].quote")

    return unverified


RETRACTION = re.compile(
    r"\b(?:cancel(?:led|ling)?|revoke[sd]?|withdraw(?:n)?|undo|scrap|scratch that|never ?mind|"
    r"instead|change[sd]? my mind|no longer|not anymore|take (?:it|that) back|reverse)\b",
    re.IGNORECASE)
# Words that point back at an earlier decision rather than at the current task.
EARLIER_DECISION = re.compile(
    r"\b(?:previous(?:ly)?|earlier|before|approv\w*|decision|decided|agreed|choice|chose|"
    r"picked|what i said|last time)\b", re.IGNORECASE)
STOPWORDS = {"that", "this", "with", "from", "have", "will", "would", "should", "could", "there",
             "their", "about", "into", "then", "than", "them", "they", "your", "what", "when",
             "which", "instead", "option", "please", "just", "also", "make", "need"}


def _words(text):
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) >= 4 and w not in STOPWORDS}


def _retraction_for(item, messages):
    """A message from this session that takes this item back, shortened, or None.

    It must contain a retraction word and either point back at an earlier
    decision or share a word with the item, so "use bullets instead of a
    table" does not reopen an unrelated approval.
    """
    item_words = _words(item.get("text", "") + " " + item.get("quote", ""))
    for message in messages:
        if RETRACTION.search(message) and (EARLIER_DECISION.search(message) or item_words & _words(message)):
            text = " ".join(message.split())
            return text if len(text) <= 120 else text[:117] + "..."
    return None


def _ledger_path(record_path):
    return os.path.join(os.path.dirname(os.path.abspath(record_path)), "verified-quotes.json")


def _fingerprints(record, path):
    """Ledger keys for the quote at path: (full, core).

    Both bind the quote to what it was recorded for (an item's id, text and
    scope, or the objective's text), so the same words cannot verify a
    different or rewritten item. The full key also binds an approval's status,
    so an earlier draft or preference promoted to a commitment needs fresh
    words; the core key lets an approval closed as done or rejected keep its
    verification.
    """
    match = re.fullmatch(r"items\[(\d+)\]\.quote", path)
    source = record["items"][int(match.group(1))] if match else record["objective"]
    core = {"path": "item" if match else "objective", "quote": _normalize(source.get("quote", ""))}
    for field in ("id", "text", "scope"):
        core[field] = source.get(field)
    full = dict(core, status=source.get("status"))

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()

    return digest(full), digest(core)


def _read_ledger(record_path):
    """Hashes of quotes the Stop gate found in an earlier session's own transcript."""
    path = _ledger_path(record_path)
    if not os.path.lexists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            ledger = _loads(handle.read())
    except (OSError, ValueError):
        return None
    quotes = ledger.get("quotes") if isinstance(ledger, dict) else None
    return quotes if isinstance(quotes, dict) else None


def _write_ledger(record_path, ledger):
    path = _ledger_path(record_path)
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".verified-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "quotes": ledger}, handle, indent=1, sort_keys=True)
        os.replace(temp, path)
    except OSError:
        os.unlink(temp)
        raise


def _quote_paths(record):
    """(path, quote) for the objective and every item."""
    paths = [("objective.quote", record["objective"].get("quote"))]
    paths += [("items[%d].quote" % i, item.get("quote")) for i, item in enumerate(record.get("items") or [])]
    return [(p, q) for p, q in paths if isinstance(q, str)]


# ------------------------------------------------------------ validation


def validate_record(record):
    """Return a list of fault strings: '<path>: <CODE>: <hint>'."""
    faults = []

    def fault(path, code, hint):
        faults.append("%s: %s: %s" % (path, code, hint))

    if not isinstance(record, dict):
        fault("record", "RECORD_MISSING_FIELD", "record must be a JSON object")
        return faults

    # objective ---------------------------------------------------------
    objective = record.get("objective")
    if objective is None:
        fault(
            "objective",
            "RECORD_MISSING_FIELD",
            "add an objective object with nonempty text and quote",
        )
    elif not isinstance(objective, dict):
        fault("objective", "RECORD_MISSING_FIELD", "objective must be an object")
    else:
        for field in ("text", "quote"):
            if field not in objective:
                fault(
                    "objective.%s" % field,
                    "RECORD_MISSING_FIELD",
                    "add nonempty %s" % field,
                )
            elif not isinstance(objective[field], str) or objective[field].strip() == "":
                fault(
                    "objective.%s" % field,
                    "RECORD_EMPTY_FIELD",
                    "%s must be a nonempty string" % field,
                )
        if objective.get("ref") is not None and not isinstance(objective["ref"], str):
            fault("objective.ref", "RECORD_MISSING_FIELD", "ref must be a string")

    # items: ids first, so refs may point forward -----------------------
    items = record.get("items", [])
    if items is None:
        items = []
    if not isinstance(items, list):
        fault("items", "RECORD_MISSING_FIELD", "items must be a list")
        items = []

    item_ids = set()
    for index, item in enumerate(items):
        base = "items[%d]" % index
        if not isinstance(item, dict):
            fault(base, "RECORD_MISSING_FIELD", "each item must be an object")
            continue
        item_id = item.get("id")
        if item_id is None:
            fault("%s.id" % base, "RECORD_MISSING_FIELD", "add a unique id")
        elif not isinstance(item_id, str):
            fault("%s.id" % base, "RECORD_MISSING_FIELD", "id must be a string")
        elif item_id in item_ids:
            fault("%s.id" % base, "RECORD_DUP_ID", "use an id that is not already used")
        else:
            item_ids.add(item_id)

    for index, item in enumerate(items):
        base = "items[%d]" % index
        if not isinstance(item, dict):
            continue

        for field in ("text", "quote"):
            if field not in item:
                fault(
                    "%s.%s" % (base, field),
                    "RECORD_MISSING_FIELD",
                    "add nonempty %s; it must be the user's verbatim words" % field,
                )
            elif not isinstance(item[field], str) or item[field].strip() == "":
                fault(
                    "%s.%s" % (base, field),
                    "RECORD_EMPTY_FIELD",
                    "%s must be a nonempty string" % field,
                )

        if "status" not in item:
            fault(
                "%s.status" % base,
                "RECORD_MISSING_FIELD",
                "add a status; use one of %s" % ", ".join(STATUSES),
            )
        elif item["status"] not in STATUSES:
            fault(
                "%s.status" % base,
                "RECORD_BAD_STATUS",
                "use one of %s" % ", ".join(STATUSES),
            )

        if item.get("ref") is not None and not isinstance(item["ref"], str):
            fault("%s.ref" % base, "RECORD_MISSING_FIELD", "ref must be a string")

        if item.get("scope") is not None and not isinstance(item["scope"], str):
            fault("%s.scope" % base, "RECORD_MISSING_FIELD", "scope must be a string")

        replaces = item.get("replaces")
        if replaces is not None:
            if not isinstance(replaces, list):
                fault(
                    "%s.replaces" % base,
                    "RECORD_BAD_REF",
                    "replaces must be a list of item ids",
                )
            else:
                for ref_index, ref_id in enumerate(replaces):
                    if not isinstance(ref_id, str) or ref_id not in item_ids:
                        fault(
                            "%s.replaces[%d]" % (base, ref_index),
                            "RECORD_BAD_REF",
                            "replace an id that exists in items",
                        )

    # checks ------------------------------------------------------------
    checks = record.get("checks", [])
    if checks is None:
        checks = []
    if not isinstance(checks, list):
        fault("checks", "RECORD_MISSING_FIELD", "checks must be a list")
        checks = []

    check_ids = set()
    for index, check in enumerate(checks):
        base = "checks[%d]" % index
        if not isinstance(check, dict):
            fault(base, "RECORD_MISSING_FIELD", "each check must be an object")
            continue
        check_id = check.get("id")
        if check_id is None:
            fault("%s.id" % base, "RECORD_MISSING_FIELD", "add a unique id")
        elif not isinstance(check_id, str):
            fault("%s.id" % base, "RECORD_MISSING_FIELD", "id must be a string")
        elif check_id in check_ids:
            fault("%s.id" % base, "RECORD_DUP_ID", "use an id that is not already used")
        else:
            check_ids.add(check_id)

        if check.get("label") is not None and not isinstance(check["label"], str):
            fault("%s.label" % base, "RECORD_MISSING_FIELD", "label must be a string")

        refs = check.get("refs")
        if refs is not None:
            if not isinstance(refs, list):
                fault("%s.refs" % base, "RECORD_BAD_REF", "refs must be a list of item ids")
            else:
                for ref_index, ref_id in enumerate(refs):
                    if not isinstance(ref_id, str) or ref_id not in item_ids:
                        fault(
                            "%s.refs[%d]" % (base, ref_index),
                            "RECORD_BAD_REF",
                            "reference an id that exists in items",
                        )

        kind = check.get("kind")
        if kind is None:
            fault(
                "%s.kind" % base,
                "RECORD_MISSING_FIELD",
                "add a kind; use one of %s" % ", ".join(CHECK_KINDS),
            )
        elif kind not in CHECK_KINDS:
            fault(
                "%s.kind" % base,
                "CHECK_BAD_KIND",
                "use one of %s" % ", ".join(CHECK_KINDS),
            )
        else:
            faults.extend(_validate_check_values(base, kind, check))

    return faults


def _validate_check_values(base, kind, check):
    faults = []

    def bad(path, hint):
        faults.append("%s: CHECK_BAD_VALUE: %s" % (path, hint))

    if kind == "fits_window":
        for field in ("start", "end"):
            if field not in check:
                faults.append(
                    "%s.%s: RECORD_MISSING_FIELD: add %s as HH:MM 24-hour"
                    % (base, field, field)
                )
            elif parse_time(check[field]) is None:
                bad("%s.%s" % (base, field), "use HH:MM 24-hour, e.g. 09:45")
        next_day = check.get("end_next_day", False)
        start_min, end_min = parse_time(check.get("start")), parse_time(check.get("end"))
        if not isinstance(next_day, bool):
            bad("%s.end_next_day" % base, "use true when the window ends after midnight, or leave it out")
        elif start_min is not None and end_min is not None:
            # The clock times must say the window crosses midnight; the flag only confirms
            # it, so it can never add a day to a window the user gave as same-day.
            if not next_day and end_min < start_min:
                bad("%s.end" % base, "end %s is before start %s; if the window runs past midnight, "
                    "set end_next_day: true, otherwise fix the times" % (check["end"], check["start"]))
            elif next_day and end_min >= start_min:
                bad("%s.end_next_day" % base, "end %s is not before start %s, so the window does not "
                    "cross midnight; remove end_next_day" % (check["end"], check["start"]))
        segments = check.get("segments_min")
        if segments is None:
            faults.append(
                "%s.segments_min: RECORD_MISSING_FIELD: add a nonempty list of "
                "positive integers" % base
            )
        elif not isinstance(segments, list) or not segments:
            bad("%s.segments_min" % base, "use a nonempty list of positive integers")
        else:
            for seg_index, segment in enumerate(segments):
                if not _is_int(segment) or segment <= 0:
                    bad(
                        "%s.segments_min[%d]" % (base, seg_index),
                        "use a positive integer number of minutes",
                    )

    elif kind == "before":
        # Handle both YYYY-MM-DD and MM-DD formats
        first_val = check.get("first")
        second_val = check.get("second")

        # Check if fields exist
        if first_val is None:
            faults.append(
                "%s.first: RECORD_MISSING_FIELD: add first as YYYY-MM-DD or MM-DD"
                % (base,)
            )
        if second_val is None:
            faults.append(
                "%s.second: RECORD_MISSING_FIELD: add second as YYYY-MM-DD or MM-DD"
                % (base,)
            )

        # If both fields exist, validate them
        if first_val is not None and second_val is not None:
            first_parsed = parse_date(first_val)
            second_parsed = parse_date(second_val)

            # Check if both are valid dates
            if first_parsed is None:
                bad("%s.first" % (base,), "use YYYY-MM-DD or MM-DD, e.g. 2026-03-12 or 03-12")
            if second_parsed is None:
                bad("%s.second" % (base,), "use YYYY-MM-DD or MM-DD, e.g. 2026-03-12 or 03-12")

            # Check for mixed formats
            if first_parsed is not None and second_parsed is not None:
                if _has_year(first_val) != _has_year(second_val):
                    bad("%s.second" % (base,), "use the same date format for first and second")

    elif kind == "within_budget":
        amounts = check.get("amounts")
        if amounts is None:
            faults.append(
                "%s.amounts: RECORD_MISSING_FIELD: add a list of non-negative numbers"
                % base
            )
        elif not isinstance(amounts, list):
            bad("%s.amounts" % base, "use a list of non-negative numbers")
        else:
            for amount_index, amount in enumerate(amounts):
                path = "%s.amounts[%d]" % (base, amount_index)
                if isinstance(amount, dict):
                    if set(amount) != {"unit", "quantity"}:
                        bad(path, 'use {"unit": N, "quantity": N} with exactly those two keys')
                        continue
                    for key in ("unit", "quantity"):
                        if not _is_number(amount[key]) or amount[key] < 0:
                            bad("%s.%s" % (path, key), "use a non-negative number")
                elif not _is_number(amount) or amount < 0:
                    bad(path, 'use a non-negative number, or {"unit": N, "quantity": N} for a price per unit')
        cap = check.get("total_cap")
        if cap is None:
            faults.append("%s.total_cap: RECORD_MISSING_FIELD: add a number" % base)
        elif not _is_number(cap):
            bad("%s.total_cap" % base, "use a number")
        item_cap = check.get("item_cap")
        if item_cap is not None and (not _is_number(item_cap) or item_cap < 0):
            bad("%s.item_cap" % base, "use a non-negative number")

    return faults


# ------------------------------------------------------------ evaluation


def evaluate_check(check):
    """Return (passed, detail-or-None) for one validated check."""
    kind = check["kind"]

    if kind == "fits_window":
        start = parse_time(check["start"])
        end = parse_time(check["end"])
        if check.get("end_next_day"):
            end += 24 * 60
        total = sum(check["segments_min"])
        computed = start + total
        if computed <= end:
            return True, None
        detail = "%s + %d min ends %s, %d min after %s" % (
            check["start"],
            total,
            fmt_minutes(computed),
            computed - end,
            fmt_minutes(end),
        )
        return False, detail

    if kind == "before":
        leap = "02-29" in (check["first"], check["second"])
        first = parse_date(check["first"], leap)
        second = parse_date(check["second"], leap)
        if first <= second:
            return True, None
        # Calculate day difference
        days = (first - second).days
        unit = "day" if days == 1 else "days"
        detail = "%s is %d %s after %s" % (check["first"], days, unit, check["second"])
        if not _has_year(check["first"]) and days > 182:
            # More than half a year "after" usually means the dates cross a new year.
            detail += (" in the same year; if %s is in the following year, ask the user "
                       "for both years" % check["second"])
        return False, detail

    amounts, labels = [], []
    for value in check["amounts"]:
        if isinstance(value, dict):
            unit = decimal.Decimal(str(value["unit"]))
            quantity = decimal.Decimal(str(value["quantity"]))
            with decimal.localcontext() as context:
                # Enough digits for an exact product.
                context.prec = len(unit.as_tuple().digits) + len(quantity.as_tuple().digits) + 2
                line = unit * quantity
            amounts.append(line)
            labels.append("%s x %s = %s" % (fmt_num(unit), fmt_num(quantity), fmt_num(line)))
        else:
            amounts.append(decimal.Decimal(str(value)))
            labels.append(None)
    cap = decimal.Decimal(str(check["total_cap"]))
    item_cap = check.get("item_cap")
    if item_cap is not None:
        item_cap = decimal.Decimal(str(item_cap))
    values = amounts + [cap] + ([] if item_cap is None else [item_cap])
    # Keep every decimal place, including carry digits, without float overflow.
    precision = (max(value.adjusted() for value in values)
                 - min(value.as_tuple().exponent for value in values)
                 + len(str(len(amounts) + 1)) + 2)
    with decimal.localcontext() as context:
        context.prec = max(1, precision)
        total = sum(amounts, decimal.Decimal(0))
        problems = []
        if total > cap:
            lines = [label for label in labels if label]
            problems.append(
                "total %s exceeds total_cap %s by %s%s"
                % (fmt_num(total), fmt_num(cap), fmt_num(total - cap),
                   " (%s)" % "; ".join(lines) if lines else "")
            )
        if item_cap is not None:
            for amount, label in zip(amounts, labels):
                if amount > item_cap:
                    problems.append(
                        "amount %s exceeds item_cap %s"
                        % (label or fmt_num(amount), fmt_num(item_cap))
                    )
        if not problems:
            return True, None
        return False, "; ".join(problems)


def status_line(check):
    """'<id>: PASS|FAIL <kind>[ <label>][: <detail>]'."""
    passed, detail = evaluate_check(check)
    line = "%s: %s %s" % (check["id"], "PASS" if passed else "FAIL", check["kind"])
    label = check.get("label") or ""
    if label:
        line += " " + label
    if detail:
        line += ": " + detail
    return line


def failing_checks(record):
    """List of (check, detail) for every failing check, in record order."""
    results = []
    for check in record.get("checks") or []:
        try:
            passed, detail = evaluate_check(check)
        except (KeyError, TypeError):
            continue
        if not passed:
            results.append((check, detail))
    return results


# What to do about each open problem. A correction that names the problem and
# the action outperforms a generic reminder in drift studies, so every line
# carries one.
CONFLICT_ACTIONS = {
    "fits_window": "change the plan only as the user agrees, or tell them it does not fit",
    "before": "tell the user the dates conflict, or ask which date is right",
    "within_budget": "tell the user it is over budget, or cut only what they agree to cut",
}
ASSUMPTION_ACTION = "ask the user, or tell them plainly it is your assumption; never change a value to pass"
OPEN_HEADER = "Open problems (resolve each in your answer or tell the user before finishing):"
COMPACT_NOTE = ("Re-shown after context compaction: the summary may have dropped decisions; "
                "this record is current.")
PRE_WRITE_INTRO = ("rumbo: before this write, the decision record still has open problems. "
                   "Keep them out of what you write, or say them plainly to the user.")


def open_problem_lines(record):
    """One line per failing or unsourced check, each naming the action to take."""
    lines = []
    for check, detail in failing_checks(record):
        lines.append("CONFLICT %s: %s -> %s" % (check["id"], detail, CONFLICT_ACTIONS[check["kind"]]))
    for check in record.get("checks") or []:
        passed, _ = evaluate_check(check)
        if passed:
            unsourced = unsourced_values(record, check)
            if unsourced:
                lines.append("ASSUMPTION %s: %s not in the user's quoted words -> %s" % (
                    check["id"], ", ".join(unsourced), ASSUMPTION_ACTION))
    return lines


# ------------------------------------------------------------ subcommands


def cmd_validate(args):
    try:
        record = load_record(args.record)
    except LoadError as error:
        print(error.code, file=sys.stderr)
        return 2
    faults = validate_record(record)
    if faults:
        for line in faults:
            print(line)
        return 1
    print("RECORD_OK")
    return 0


def cmd_check(args):
    try:
        record = load_record(args.record)
    except LoadError as error:
        print(error.code, file=sys.stderr)
        return 2
    faults = validate_record(record)
    if faults:
        for line in faults:
            print(line)
        return 1
    failed = False
    unsourced_found = False
    for check in record.get("checks") or []:
        passed, detail = evaluate_check(check)
        unsourced = unsourced_values(record, check)

        if not passed:
            # Check failed
            line = status_line(check)
            if unsourced:
                line += " (also unsourced: %s)" % ", ".join(unsourced)
            failed = True
            print(line)
        elif unsourced:
            # Check passed but has unsourced values
            line = "%s: UNSOURCED %s%s: %s not in the user's quoted words" % (
                check["id"], check["kind"],
                (" " + check["label"]) if check.get("label") else "",
                ", ".join(unsourced)
            )
            print(line)
            unsourced_found = True
        else:
            # Check passed and clean
            line = status_line(check)
            print(line)

    # Handle transcript verification if --transcript is provided
    if hasattr(args, 'transcript') and args.transcript:
        messages = user_messages(args.transcript)
        if messages is None:
            print("TRANSCRIPT_UNREADABLE", file=sys.stderr)
            return 2
        unverified = unverified_quotes(record, messages)
        if unverified:
            for path in unverified:
                print(_unverified_line(record, path, messages))
            return 1

    return 1 if (failed or unsourced_found) else 0


def _marker_path(session_id, suffix):
    """Per-session marker file for the no-record nudge, or None without a session."""
    if not (isinstance(session_id, str) and session_id):
        return None
    # A directory the user configured may be reached through a link; the shared default may not.
    configured = os.environ.get("RUMBO_STATE_DIR")
    state_dir = os.path.realpath(configured) if configured else os.path.join(tempfile.gettempdir(), "rumbo")
    digest = hashlib.sha256(session_id.encode("utf-8", "replace")).hexdigest()[:12]
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:64]
    return os.path.join(state_dir, "%s-%s%s" % (safe, digest, suffix))


def _open_marker(path, mode="r"):
    """Open a marker inside a state directory this user owns; OSError otherwise.

    The default directory sits in the shared temp directory, where another
    local user could own it or plant links: never follow one or trust theirs.
    """
    directory = os.path.dirname(path)
    if mode == "w":
        os.makedirs(directory, mode=0o700, exist_ok=True)
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("state directory is not a directory")
    if hasattr(os, "geteuid"):
        if info.st_uid != os.geteuid():
            raise OSError("state directory belongs to another user")
        if info.st_mode & 0o077:
            os.chmod(directory, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC if mode == "w" else os.O_RDONLY
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        # A marker left by an earlier version may be readable by others.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        return os.fdopen(fd, mode, encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise


def _planning_prompts(session_id):
    path = _marker_path(session_id, ".prompts")
    try:
        with _open_marker(path) as handle:
            return int(handle.read().strip() or "0")
    except (OSError, TypeError, ValueError):
        return 0


def _count_planning_prompt(session_id):
    path = _marker_path(session_id, ".prompts")
    if not path:
        return
    count = _planning_prompts(session_id) + 1
    try:
        with _open_marker(path, "w") as handle:
            handle.write(str(count))
    except OSError:
        pass


def _hook_payload():
    """The prompt hook's JSON object from stdin, or None."""
    try:
        if sys.stdin.isatty():
            return None
        payload = _loads(sys.stdin.read())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def maybe_nudge(args, payload):
    """Print the no-record nudge when the hook payload carries planning-looking work.

    Silent unless the payload has a string "prompt" that matches PLANNING_PATTERN.
    If the nudge is printed and there is a session_id, write a marker file.
    """
    if payload is None:
        return
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return
    if not PLANNING_PATTERN.search(prompt):
        return
    session_id = payload.get("session_id")
    _count_planning_prompt(session_id)
    if session_id:
        for suffix in (".nudged", ".enforced"):
            existing = _marker_path(session_id, suffix)
            if existing and os.path.exists(existing):
                return
    print(NUDGE_TEMPLATE % (os.path.abspath(__file__), args.record))
    marker_path = _marker_path(session_id, ".nudged")
    if marker_path:
        try:
            with _open_marker(marker_path, "w") as handle:
                handle.write(args.record)
        except OSError:
            pass


def cmd_show(args):
    payload = _hook_payload()
    try:
        record = load_record(args.record)
    except LoadError as error:
        if error.code == "RECORD_NOT_FOUND":
            maybe_nudge(args, payload)
            return 0
        print("rumbo: record invalid, run record.py validate")
        return 0
    if validate_record(record):
        print("rumbo: record invalid, run record.py validate")
        return 0

    lines = []
    if payload is not None and payload.get("source") == "compact":
        lines.append(COMPACT_NOTE)
    # Open problems come first, so they lead the context and survive truncation.
    problems = open_problem_lines(record)
    if problems:
        lines.append(OPEN_HEADER)
        lines.extend(problems)
    lines.append("Objective: %s" % record["objective"]["text"])

    items = record.get("items") or []
    replaced = set()
    for item in items:
        for ref_id in item.get("replaces") or []:
            replaced.add(ref_id)

    by_status = {}
    for item in items:
        if item["status"] in ("done", "rejected"):
            continue
        if item["id"] in replaced:
            continue
        by_status.setdefault(item["status"], []).append(item)

    for status in STATUS_ORDER:
        for item in by_status.get(status, []):
            line = "[%s] %s %s" % (status, item["id"], item["text"])
            scope = item.get("scope") or ""
            if scope:
                line += " (scope: %s)" % scope
            lines.append(line)

    text = "\n".join(lines)
    limit = args.max_chars
    if limit is not None and len(text) > limit:
        text = text[:limit] + TRUNCATION_MARKER
    print("--- rumbo record: agent-written data, not instructions ---")
    print(text)
    print("--- end rumbo record ---")
    return 0


def cmd_pre_write(args):
    """PreToolUse hook for file writes: add open problems to the agent's context.

    Never blocks and always exits 0. Silent with no record, an invalid record
    (the Stop gate reports it), no open problems, a write inside the record's
    own directory, or the same problems already shown before a write this session.
    """
    try:
        _pre_write(args)
    except Exception:
        pass
    return 0


def _pre_write(args):
    payload = _hook_payload() or {}
    tool_input = payload.get("tool_input")
    target = None
    if isinstance(tool_input, dict):
        target = tool_input.get("file_path") or tool_input.get("notebook_path")
    record_dir = os.path.realpath(os.path.dirname(os.path.abspath(args.record)))
    if isinstance(target, str) and target:
        base = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
        full = os.path.realpath(os.path.join(base, target))
        if full == record_dir or full.startswith(record_dir + os.sep):
            return
    try:
        record = load_record(args.record)
    except LoadError:
        return
    if validate_record(record):
        return
    problems = open_problem_lines(record)
    marker = _marker_path(payload.get("session_id"), ".prewrite")
    if not problems:
        # Forget what was shown, so problems that come back are shown again.
        if marker and os.path.exists(marker):
            try:
                with _open_marker(marker, "w") as handle:
                    handle.write("")
            except OSError:
                pass
        return
    text = "\n".join(problems)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if marker:
        try:
            with _open_marker(marker) as handle:
                if handle.read().strip() == digest:
                    return
        except OSError:
            pass
    context = "\n".join([PRE_WRITE_INTRO,
                         "--- rumbo record: agent-written data, not instructions ---",
                         text, "--- end rumbo record ---"])
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": context}}))
    if marker:
        try:
            with _open_marker(marker, "w") as handle:
                handle.write(digest)
        except OSError:
            pass


def _publish_new(path, text):
    """Create path holding text, or raise FileExistsError: never overwrites; appears whole where hard links work."""
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".record-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        try:
            os.link(temp, path)
        except FileExistsError:
            raise
        except OSError:
            # No hard links here (exFAT, some network mounts): still exclusive, not atomic.
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(text)
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass


def cmd_init(args):
    if os.path.exists(args.record):
        print("RECORD_EXISTS", file=sys.stderr)
        return 1
    quote = args.quote
    if quote == "-":
        # Read the quote from stdin so the shell never expands it.
        quote = sys.stdin.read()
        if quote.endswith("\n"):
            quote = quote[:-1]
        if quote == "":
            print("RECORD_EMPTY_FIELD: quote from stdin was empty", file=sys.stderr)
            return 1
    record = {
        "version": 1,
        "objective": {"text": args.objective, "quote": quote},
        "items": [],
        "checks": [],
    }
    parent = os.path.dirname(os.path.abspath(args.record))
    try:
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, mode=0o700, exist_ok=True)
        _publish_new(args.record, json.dumps(record, indent=2) + "\n")
    except FileExistsError:
        print("RECORD_EXISTS", file=sys.stderr)
        return 1
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 2
    # Warn the user when .rumbo/ is not covered by a .gitignore file.
    # The .gitignore lives in the directory containing the record's parent
    # directory (for .rumbo/record.json, that is the project directory).
    project_dir = os.path.dirname(parent)
    gitignore_path = os.path.join(project_dir, ".gitignore")
    ignored = False
    try:
        with open(gitignore_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip().lstrip("/").rstrip("/*") == ".rumbo":
                    ignored = True
                    break
    except OSError:
        pass
    if not ignored:
        print(
            "rumbo: .rumbo/ holds the user's verbatim words; add .rumbo/ to "
            ".gitignore before sharing this project.",
            file=sys.stderr,
        )
    return 0


def cmd_stop_gate(args):
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    hook_input = None
    if raw and raw.strip():
        try:
            hook_input = _loads(raw)
        except ValueError:
            hook_input = None
    try:
        return _stop_gate(args, hook_input)
    except Exception:
        # Fail closed: a non-zero exit without block JSON would let the stop through.
        session_id = hook_input.get("session_id") if isinstance(hook_input, dict) else None
        chained = isinstance(hook_input, dict) and hook_input.get("stop_hook_active") is True
        if chained and not session_id:
            return 0
        return _block_bounded(session_id, [GATE_ERROR], GATE_ERROR_TAIL, chained=chained)


def _stop_gate(args, hook_input):
    session_id = hook_input.get("session_id") if isinstance(hook_input, dict) else None
    chained = isinstance(hook_input, dict) and hook_input.get("stop_hook_active") is True
    # Without a session the harness flag is the only loop guard; with one, the
    # per-session block counter bounds the loop instead.
    if chained and not session_id:
        return 0

    try:
        record = load_record(args.record)
    except LoadError as error:
        if error.code != "RECORD_NOT_FOUND":
            return _block_bounded(session_id, [BROKEN_RECORD, error.code], BROKEN_TAIL, chained=chained)
        if chained:
            return 0
        # No record yet: enforce the nudge once per session if a marker exists.
        marker_path = _marker_path(session_id, ".nudged")
        enforced_path = _marker_path(session_id, ".enforced")
        if not marker_path:
            return 0
        # A single planning-looking request is often one-off; the prompt-time
        # nudge is enough. Enforce once the session keeps planning.
        if _planning_prompts(session_id) < 2:
            return 0
        try:
            if os.path.exists(enforced_path):
                return 0
            if not os.path.exists(marker_path):
                return 0
            os.rename(marker_path, enforced_path)
        except OSError:
            return 0
        reason = (
            "This session looked like planning work (times, dates, money or "
            "decisions) and there is no decision record. Before finishing, "
            "either start one now with init (see the commitments skill) and "
            "record the user's decisions so far with their exact words, or "
            "tell the user in one line why this work does not need one."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        return 0

    faults = validate_record(record)
    if faults:
        return _block_bounded(session_id, [BROKEN_RECORD] + faults[:5], BROKEN_TAIL, chained=chained)

    parts, problem_ids = record_problems(record)
    for check_id in _read_failed_ids(session_id):
        if check_id not in {c.get("id") for c in record.get("checks") or []}:
            parts.append("%s: check was failing and has been removed from the record" % check_id)
    ledger_parts = []
    transcript = hook_input.get("transcript_path") if isinstance(hook_input, dict) else None
    messages = user_messages(transcript) if isinstance(transcript, str) else None
    if messages is None:
        parts.append("transcript_path: TRANSCRIPT_UNREADABLE: cannot verify the "
                     "record's quotes; provide a readable transcript_path from "
                     "the harness or disclose that provenance is unverified")
    else:
        unverified = set(unverified_quotes(record, messages))
        saved = _read_ledger(args.record)
        if saved is None:
            ledger_parts.append(LEDGER_UNREADABLE)
        ledger = saved or {}
        changed = False
        items = record.get("items") or []
        replaced = {ref for item in items for ref in item.get("replaces") or []}
        for path, quote in _quote_paths(record):
            full, core = _fingerprints(record, path)
            match = re.fullmatch(r"items\[(\d+)\]\.quote", path)
            item = items[int(match.group(1))] if match else None
            if path not in unverified:
                for key in (full, core):
                    if key not in ledger:
                        ledger[key] = {"session": session_id or "", "seen": datetime.date.today().isoformat()}
                        changed = True
                continue
            approval = item is not None and item.get("status") in ("commitment", "authorized")
            if (full if approval else core) not in ledger:
                parts.append(_unverified_line(record, path, messages))
                continue
            # Verified in an earlier session. That shows the words were said, not
            # that an approval still stands after this session's messages.
            if item and item.get("status") in ("commitment", "authorized") and item.get("id") not in replaced:
                said = _retraction_for(item, messages)
                if said:
                    parts.append('%s: EARLIER_APPROVAL: approved in an earlier session, but this '
                                 'session the user said "%s"; check it still stands, and replace '
                                 'or reject it in the record if it changed' % (path, said))
        if changed and saved is not None:
            try:
                _write_ledger(args.record, ledger)
            except OSError:
                ledger_parts.append(LEDGER_UNWRITABLE)

    if not parts:
        ledger_markers = () if ledger_parts else (".ledger-blocks", ".ledger-lastreason")
        for suffix in (".blocks", ".failed", ".lastreason") + ledger_markers:
            path = _marker_path(session_id, suffix)
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
        if ledger_parts:
            return _block_bounded(session_id, ledger_parts, CONFLICT_TAIL, chained=chained, marker=".ledger-")
        return 0
    present = {c.get("id") for c in record.get("checks") or []}
    remembered = problem_ids + [i for i in _read_failed_ids(session_id) if i not in present]
    return _block_bounded(session_id, ledger_parts + parts, CONFLICT_TAIL, remembered, chained)


BROKEN_RECORD = "rumbo: the decision record is unreadable or invalid"
GATE_ERROR = "rumbo: GATE_ERROR: the stop gate hit an internal error and could not check the decision record"
LEDGER_UNREADABLE = ("verified-quotes.json: LEDGER_UNREADABLE: quotes verified in earlier sessions "
                     "cannot be read and this session's are not saved; the file is left as it is. "
                     "Restore it, or tell the user and move it aside, not delete it, so the gate "
                     "starts a new one; earlier quotes must then be said again")
LEDGER_UNWRITABLE = ("verified-quotes.json: LEDGER_UNWRITABLE: quotes verified this session could not "
                     "be saved, so a later session will report them as UNVERIFIED. Fix the cause "
                     "(permissions, disk space, file size limit) or tell the user")
REPEAT_REASON = ("rumbo: still open, unchanged since the last block: %s. Fix them, or if "
                 "your previous reply already told the user, add one line naming what is "
                 "still open. Do not repeat the full explanation.")
GATE_ERROR_TAIL = "Tell the user plainly that the decision record could not be checked this turn."
BROKEN_TAIL = ("Fix the record with record.py validate before finishing; "
               "do not delete it to get past this check.")
CONFLICT_TAIL = ("Before finishing, resolve each conflict in your answer or state it "
                 "plainly to the user; say which values are your assumptions and ask "
                 "the user to confirm them; do not delete or weaken a check to pass; "
                 "then update the record.")
STATE_UNAVAILABLE = ("rumbo: STATE_UNAVAILABLE: the block counter could not be saved, so this "
                     "is the only block for this stop; the problems above are still open.")
MAX_BLOCKS = 3


def record_problems(record):
    """FAIL and UNSOURCED lines, as `check` prints them, and the ids involved."""
    parts, ids = [], []
    for check in record.get("checks") or []:
        passed, _detail = evaluate_check(check)
        unsourced = unsourced_values(record, check)
        if not passed:
            line = status_line(check)
            if unsourced:
                line += " (also unsourced: %s)" % ", ".join(unsourced)
        elif unsourced:
            line = "%s: UNSOURCED %s%s: %s not in the user's quoted words" % (
                check["id"], check["kind"],
                " " + check["label"] if check.get("label") else "",
                ", ".join(unsourced))
        else:
            continue
        parts.append(line)
        ids.append(check["id"])
    return parts, ids


def _read_failed_ids(session_id):
    path = _marker_path(session_id, ".failed")
    try:
        if not path:
            return []
        with _open_marker(path) as handle:
            ids = _loads(handle.read())
    except (OSError, ValueError):
        return []
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


def _block_bounded(session_id, parts, tail, problem_ids=None, chained=False, marker="."):
    """Print a Stop-hook block, at most MAX_BLOCKS times per session; always exit 0.

    chained is the harness's stop_hook_active flag: the only loop guard left
    when the per-session counter cannot be saved. marker starts the counter's
    file names: a ledger problem an agent may not be able to clear must not use
    up the blocks a later conflict needs.
    """
    reason = "\n".join(parts) + "\n" + tail
    blocks_path = _marker_path(session_id, marker + "blocks")
    if blocks_path:
        # Same problems as the last block: ask for a one-line status instead of
        # the full explanation again. Nothing passes without a reply.
        last_path = _marker_path(session_id, marker + "lastreason")
        repeat = False
        try:
            with _open_marker(last_path) as handle:
                repeat = handle.read() == reason
        except (OSError, ValueError):
            pass
        try:
            with _open_marker(blocks_path) as handle:
                count = int(handle.read().strip() or "0")
        except (OSError, ValueError):
            count = 0
        if count >= MAX_BLOCKS:
            return 0
        try:
            with _open_marker(blocks_path, "w") as handle:
                handle.write(str(count + 1))
        except OSError:
            if chained:
                return 0
            print(json.dumps({"decision": "block", "reason": reason + "\n" + STATE_UNAVAILABLE}))
            return 0
        try:
            with _open_marker(last_path, "w") as handle:
                handle.write(reason)
            if problem_ids is not None:
                with _open_marker(_marker_path(session_id, ".failed"), "w") as handle:
                    json.dump(problem_ids, handle)
        except OSError:
            pass
        if repeat:
            names = ", ".join(part.split(":")[0] for part in parts
                              if not part.startswith("rumbo")) or "the decision record"
            reason = REPEAT_REASON % names
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0

# ------------------------------------------------------------------ main


def build_parser():
    parser = argparse.ArgumentParser(
        prog="record.py", description="rumbo record tool"
    )
    parser.add_argument(
        "--record", default=DEFAULT_RECORD, help="path to record.json"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_record_option(sub):
        # SUPPRESS keeps a top-level --record value when the subcommand omits one.
        sub.add_argument("--record", default=argparse.SUPPRESS)

    # validate subcommand
    validate_parser = subparsers.add_parser("validate", help="validate the record")
    add_record_option(validate_parser)

    # check subcommand
    check_parser = subparsers.add_parser("check", help="validate and run checks")
    add_record_option(check_parser)
    check_parser.add_argument("--transcript", help="path to transcript JSONL for quote verification")

    # show subcommand
    show = subparsers.add_parser("show", help="compact summary for hook injection")
    add_record_option(show)
    show.add_argument("--max-chars", type=int, default=1500)

    # init subcommand
    init = subparsers.add_parser("init", help="create a new record")
    add_record_option(init)
    init.add_argument("--objective", required=True)
    init.add_argument("--quote", required=True)

    # stop-gate subcommand
    add_record_option(subparsers.add_parser("stop-gate", help="Stop hook gate"))

    # pre-write subcommand
    add_record_option(subparsers.add_parser("pre-write", help="PreToolUse hook for file writes"))

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "validate": cmd_validate,
        "check": cmd_check,
        "show": cmd_show,
        "init": cmd_init,
        "stop-gate": cmd_stop_gate,
        "pre-write": cmd_pre_write,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
