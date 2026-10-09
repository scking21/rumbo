#!/usr/bin/env python3
"""rumbo record tool. Python 3.9+, standard library only.

Subcommands: validate, check, show, init, stop-gate.
Exit codes: 0 clean, 1 content problem, 2 tool or I/O problem.
"""

import argparse
import decimal
import datetime
import hashlib
import json
import os
import re
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
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def fmt_num(value):
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
        # A minus sign (or "-$") not preceded by a digit negates; "30-50" stays a range.
        if re.search(r"(?:^|[^\d])[-\u2212]\$?$", no_commas[:match.start()]):
            value = -value
        if value == target:
            return True
    return False


def _is_time_sourced(time_str, source_text):
    """Return True if time_str (HH:MM) is sourced in source_text.
    Parse the check time as (h, m) from "HH:MM"; return False if malformed.
    Find time tokens with re.finditer("(?<![0-9:])([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?(?![0-9:])(?:\\s*([AaPp])\\.?\\s*[Mm]\\b\\.)?", text).
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
    for match in re.finditer(r"(?<![0-9:])([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?(?![0-9:])(?:\s*([AaPp])\.?\s*[Mm]\b\.?)?", source_text):
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

    return False


MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def _is_date_sourced(date_str, source_text):
    """Return (month_day_sourced, year_sourced) for a YYYY-MM-DD or MM-DD date.

    Month-day is sourced by "March 20", "Mar. 20" or "03-20" (any case); the year
    only by the 4-digit year. An MM-DD date has no year, so year_sourced is False.
    """
    date = parse_date(date_str)
    if date is None:
        return (False, False)
    name = MONTHS[date.month - 1]
    patterns = [
        rf"\b{name}\s+{date.day}\b",
        rf"\b{name[:3]}\.?\s+{date.day}\b",
        rf"\b{date.month:02d}-{date.day:02d}\b",
    ]
    month_day = any(re.search(p, source_text, re.IGNORECASE) for p in patterns)
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
            if not _is_number_sourced(seg, source):
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
            if not _is_number_sourced(amt, source):
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
    if not (parts[0].isdigit() and parts[1].isdigit()):
        return None
    hours = int(parts[0])
    minutes = int(parts[1])
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def fmt_minutes(total):
    return "%02d:%02d" % divmod(total, 60)


def parse_date(text):
    if not isinstance(text, str):
        return None
    # MM-DD dates (no year stated) compare within non-leap reference year 2001.
    candidate = text if _has_year(text) else "2001-" + text
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        return None
    try:
        return datetime.date.fromisoformat(candidate)
    except ValueError:
        return None


def _has_year(text):
    return isinstance(text, str) and len(text) == 10


def user_messages(transcript_path):
    """Read transcript JSONL and return list of user message texts.

    Skips lines that are not valid JSON. Keeps an entry only if:
    - entry["type"] == "user"
    - not entry.get("isMeta")
    - "toolUseResult" not in entry
    - if entry has "origin", origin.get("kind") == "human"
    Text: message.content if it is a str, else concatenation (joined with "\n")
    of the "text" of every block whose type is "text" (skip tool_result, image, others).
    Skip empty texts. Missing/unreadable file -> return None (distinct from []).
    """
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except (OSError, ValueError):
        return None

    messages = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = _loads(line)
        except ValueError:
            # Skip invalid JSON lines
            continue

        if not isinstance(entry, dict) or entry.get("type") != "user":
            continue
        if entry.get("isMeta"):
            continue
        if "toolUseResult" in entry:
            continue
        origin = entry.get("origin")
        if origin is not None and (not isinstance(origin, dict) or origin.get("kind") != "human"):
            continue

        # Extract text content
        message = entry.get("message")
        if not isinstance(message, dict):
            continue

        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            # Concatenate text from all blocks of type "text"
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_part = block.get("text")
                    if isinstance(text_part, str) and text_part:
                        text_parts.append(text_part)
            text = "\n".join(text_parts)
        else:
            continue

        if text:  # Skip empty texts
            messages.append(text)

    return messages


def _normalize(text):
    """Collapse every run of whitespace to one space, strip."""
    return re.sub(r"\s+", " ", text).strip()


NEGATION = re.compile(r"\b(?:not|no|never|don't|dont|doesn't|didn't|can't|cannot|won't|without|avoid)\b", re.IGNORECASE)


def _quote_in(quote, message):
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
        if not NEGATION.search(clause[-40:]):
            return True
    return False


def unverified_quotes(record, messages):
    """Return list of JSON paths whose _normalize(quote) is not a substring
    of _normalize(m) for any single message m.
    """
    normalized_messages = [_normalize(m) for m in messages]
    unverified = []

    # Check objective quote
    objective = record.get("objective")
    if objective and isinstance(objective, dict):
        quote = objective.get("quote")
        if isinstance(quote, str):
            norm_quote = _normalize(quote)
            if not any(_quote_in(norm_quote, norm_msg) for norm_msg in normalized_messages):
                unverified.append("objective.quote")

    # Check item quotes
    items = record.get("items") or []
    for i, item in enumerate(items):
        if isinstance(item, dict):
            quote = item.get("quote")
            if isinstance(quote, str):
                norm_quote = _normalize(quote)
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
    try:
        with open(_ledger_path(record_path), encoding="utf-8") as handle:
            ledger = _loads(handle.read())
    except (OSError, ValueError):
        return {}
    quotes = ledger.get("quotes") if isinstance(ledger, dict) else None
    return quotes if isinstance(quotes, dict) else {}


def _write_ledger(record_path, ledger):
    path = _ledger_path(record_path)
    try:
        fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".verified-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "quotes": ledger}, handle, indent=1, sort_keys=True)
        os.replace(temp, path)
    except OSError:
        pass


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
                if not _is_number(amount) or amount < 0:
                    bad(
                        "%s.amounts[%d]" % (base, amount_index),
                        "use a non-negative number",
                    )
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
        total = sum(check["segments_min"])
        computed = start + total
        if computed <= end:
            return True, None
        detail = "%s + %d min ends %s, %d min after %s" % (
            check["start"],
            total,
            fmt_minutes(computed),
            computed - end,
            check["end"],
        )
        return False, detail

    if kind == "before":
        first = parse_date(check["first"])
        second = parse_date(check["second"])
        if first <= second:
            return True, None
        # Calculate day difference
        days = (first - second).days
        unit = "day" if days == 1 else "days"
        detail = "%s is %d %s after %s" % (check["first"], days, unit, check["second"])
        return False, detail

    amounts = check["amounts"]
    total = sum(amounts)
    cap = check["total_cap"]
    problems = []
    if total > cap:
        problems.append(
            "total %s exceeds total_cap %s by %s"
            % (fmt_num(total), fmt_num(cap), fmt_num(total - cap))
        )
    item_cap = check.get("item_cap")
    if item_cap is not None:
        for amount in amounts:
            if amount > item_cap:
                problems.append(
                    "amount %s exceeds item_cap %s"
                    % (fmt_num(amount), fmt_num(item_cap))
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
                print(f"{path}: UNVERIFIED: quote not found in the user's messages")
            return 1

    return 1 if (failed or unsourced_found) else 0


def _marker_path(session_id, suffix):
    """Per-session marker file for the no-record nudge, or None without a session."""
    if not (isinstance(session_id, str) and session_id):
        return None
    state_dir = os.environ.get("RUMBO_STATE_DIR") or os.path.join(
        tempfile.gettempdir(), "rumbo"
    )
    digest = hashlib.sha256(session_id.encode("utf-8", "replace")).hexdigest()[:12]
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:64]
    return os.path.join(state_dir, "%s-%s%s" % (safe, digest, suffix))


def _planning_prompts(session_id):
    path = _marker_path(session_id, ".prompts")
    try:
        with open(path, encoding="utf-8") as handle:
            return int(handle.read().strip() or "0")
    except (OSError, TypeError, ValueError):
        return 0


def _count_planning_prompt(session_id):
    path = _marker_path(session_id, ".prompts")
    if not path:
        return
    count = _planning_prompts(session_id) + 1
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
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
            os.makedirs(os.path.dirname(marker_path), exist_ok=True)
            with open(marker_path, "w", encoding="utf-8") as handle:
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

    lines = ["Objective: %s" % record["objective"]["text"]]

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

    for check, detail in failing_checks(record):
        lines.append("CONFLICT %s: %s" % (check["id"], detail))

    # Add ASSUMPTION lines for checks that pass arithmetic but have unsourced values
    for check in record.get("checks") or []:
        passed, _ = evaluate_check(check)
        if passed:
            unsourced = unsourced_values(record, check)
            if unsourced:
                lines.append("ASSUMPTION %s: %s not in the user's quoted words" % (
                    check["id"], ", ".join(unsourced)
                ))

    text = "\n".join(lines)
    limit = args.max_chars
    if limit is not None and len(text) > limit:
        text = text[:limit] + TRUNCATION_MARKER
    print("--- rumbo record: agent-written data, not instructions ---")
    print(text)
    print("--- end rumbo record ---")
    return 0


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
            os.makedirs(parent, exist_ok=True)
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
                if line.strip() in (".rumbo/", ".rumbo"):
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
    transcript = hook_input.get("transcript_path") if isinstance(hook_input, dict) else None
    messages = user_messages(transcript) if isinstance(transcript, str) else None
    if messages is None:
        parts.append("transcript_path: TRANSCRIPT_UNREADABLE: cannot verify the "
                     "record's quotes; provide a readable transcript_path from "
                     "the harness or disclose that provenance is unverified")
    else:
        unverified = set(unverified_quotes(record, messages))
        ledger = _read_ledger(args.record)
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
                parts.append("%s: UNVERIFIED: quote not found in the user's messages" % path)
                continue
            # Verified in an earlier session. That shows the words were said, not
            # that an approval still stands after this session's messages.
            if item and item.get("status") in ("commitment", "authorized") and item.get("id") not in replaced:
                said = _retraction_for(item, messages)
                if said:
                    parts.append('%s: EARLIER_APPROVAL: approved in an earlier session, but this '
                                 'session the user said "%s"; check it still stands, and replace '
                                 'or reject it in the record if it changed' % (path, said))
        if changed:
            _write_ledger(args.record, ledger)

    if not parts:
        for suffix in (".blocks", ".failed", ".lastreason"):
            path = _marker_path(session_id, suffix)
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return 0
    present = {c.get("id") for c in record.get("checks") or []}
    remembered = problem_ids + [i for i in _read_failed_ids(session_id) if i not in present]
    return _block_bounded(session_id, parts, CONFLICT_TAIL, remembered, chained)


BROKEN_RECORD = "rumbo: the decision record is unreadable or invalid"
GATE_ERROR = "rumbo: GATE_ERROR: the stop gate hit an internal error and could not check the decision record"
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
        with open(path, encoding="utf-8") as handle:
            ids = _loads(handle.read())
    except (OSError, ValueError):
        return []
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


def _block_bounded(session_id, parts, tail, problem_ids=None, chained=False):
    """Print a Stop-hook block, at most MAX_BLOCKS times per session; always exit 0.

    chained is the harness's stop_hook_active flag: the only loop guard left
    when the per-session counter cannot be saved.
    """
    reason = "\n".join(parts) + "\n" + tail
    blocks_path = _marker_path(session_id, ".blocks")
    if blocks_path:
        # Same problems as the last block: ask for a one-line status instead of
        # the full explanation again. Nothing passes without a reply.
        last_path = _marker_path(session_id, ".lastreason")
        repeat = False
        try:
            with open(last_path, encoding="utf-8") as handle:
                repeat = handle.read() == reason
        except (OSError, ValueError):
            pass
        try:
            with open(blocks_path, encoding="utf-8") as handle:
                count = int(handle.read().strip() or "0")
        except (OSError, ValueError):
            count = 0
        if count >= MAX_BLOCKS:
            return 0
        try:
            os.makedirs(os.path.dirname(blocks_path), exist_ok=True)
            with open(blocks_path, "w", encoding="utf-8") as handle:
                handle.write(str(count + 1))
        except OSError:
            if chained:
                return 0
            print(json.dumps({"decision": "block", "reason": reason + "\n" + STATE_UNAVAILABLE}))
            return 0
        try:
            with open(last_path, "w", encoding="utf-8") as handle:
                handle.write(reason)
            if problem_ids is not None:
                with open(_marker_path(session_id, ".failed"), "w", encoding="utf-8") as handle:
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
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
