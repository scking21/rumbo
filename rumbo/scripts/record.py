#!/usr/bin/env python3
"""rumbo record tool. Python 3.9+, standard library only.

Subcommands: validate, check, show, init, stop-gate.
Exit codes: 0 clean, 1 content problem, 2 tool or I/O problem.
"""

import argparse
import datetime
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


def load_record(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        raise LoadError("RECORD_NOT_FOUND")
    try:
        return json.loads(raw)
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


def _source_text(record):
    """Return objective quote plus each item's quote, joined by newlines."""
    quotes = [record["objective"]["quote"]]
    for item in (record.get("items") or []):
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
    N = fmt_num(num)
    # Use regex to avoid being part of another number
    # Trailing zeros are the same value: 1.5 is sourced by "$1.50", 600 by "600.00".
    zeros = r"0*" if "." in N else r"(?:\.0+)?"
    pattern = r"(?<![\d.])" + re.escape(N) + zeros + r"(?!\d|\.\d)"
    return re.search(pattern, no_commas) is not None


def _is_time_sourced(time_str, source_text):
    """Return True if time_str (HH:MM) is sourced in source_text.
    Sourced if either HH:MM or H:MM (no leading zero) appears.
    """
    if not isinstance(time_str, str):
        return False
    parts = time_str.split(":")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        return False
    # Match the whole time token so 09:45 is not sourced by 19:45.
    h = int(parts[0])
    mm = parts[1]
    return re.search(rf"(?<!\d)0?{h}:{mm}(?!\d)", source_text) is not None


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
    source = _source_text(record)
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

    return 1 if (failed or unsourced_found) else 0


def _marker_path(session_id, suffix):
    """Per-session marker file for the no-record nudge, or None without a session."""
    if not (isinstance(session_id, str) and session_id):
        return None
    state_dir = os.environ.get("RUMBO_STATE_DIR") or os.path.join(
        tempfile.gettempdir(), "rumbo"
    )
    return os.path.join(state_dir, re.sub(r"[^A-Za-z0-9_-]", "_", session_id) + suffix)


def maybe_nudge(args):
    """Print the no-record nudge when stdin carries planning-looking work.

    Silent unless stdin is non-TTY, parses as a JSON object with a string
    "prompt", and that prompt matches PLANNING_PATTERN.
    If the nudge is printed and there is a session_id, write a marker file.
    """
    try:
        if sys.stdin.isatty():
            return
        raw = sys.stdin.read()
    except Exception:
        return
    try:
        payload = json.loads(raw)
    except ValueError:
        return
    if not isinstance(payload, dict):
        return
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return
    if not PLANNING_PATTERN.search(prompt):
        return
    print(NUDGE_TEMPLATE % (os.path.abspath(__file__), args.record))
    marker_path = _marker_path(payload.get("session_id"), ".nudged")
    if marker_path:
        try:
            os.makedirs(os.path.dirname(marker_path), exist_ok=True)
            with open(marker_path, "w", encoding="utf-8") as handle:
                handle.write(args.record)
        except OSError:
            pass


def cmd_show(args):
    try:
        record = load_record(args.record)
    except LoadError as error:
        if error.code == "RECORD_NOT_FOUND":
            maybe_nudge(args)
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
    print(text)
    return 0


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
        with open(args.record, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
            handle.write("\n")
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


def cmd_stop_gate(args):
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    hook_input = None
    if raw and raw.strip():
        try:
            hook_input = json.loads(raw)
        except ValueError:
            hook_input = None
    if isinstance(hook_input, dict) and hook_input.get("stop_hook_active") is True:
        return 0

    try:
        record = load_record(args.record)
    except LoadError as error:
        if error.code != "RECORD_NOT_FOUND":
            return 0
        # No record yet: enforce the nudge once per session if a marker exists.
        session_id = hook_input.get("session_id") if isinstance(hook_input, dict) else None
        marker_path = _marker_path(session_id, ".nudged")
        enforced_path = _marker_path(session_id, ".enforced")
        if not marker_path:
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

    if validate_record(record):
        return 0

    failures = failing_checks(record)

    # FAIL lines, exactly as `check` prints them (with unsourced suffix).
    parts = []
    for check, _detail in failures:
        line = status_line(check)
        unsourced = unsourced_values(record, check)
        if unsourced:
            line += " (also unsourced: %s)" % ", ".join(unsourced)
        parts.append(line)

    # UNSOURCED lines for checks that pass arithmetic but have unsourced values.
    for check in record.get("checks") or []:
        passed, _detail = evaluate_check(check)
        if not passed:
            continue
        unsourced = unsourced_values(record, check)
        if unsourced:
            label = check.get("label") or ""
            line = "%s: UNSOURCED %s" % (check["id"], check["kind"])
            if label:
                line += " " + label
            line += ": %s not in the user's quoted words" % ", ".join(unsourced)
            parts.append(line)

    if not parts:
        return 0

    reason = "\n".join(parts)
    reason += (
        "\nBefore finishing, resolve each conflict in your answer or state it "
        "plainly to the user; say which values are your assumptions and ask "
        "the user to confirm them; then update the record."
    )
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

    add_record_option(subparsers.add_parser("validate", help="validate the record"))
    add_record_option(subparsers.add_parser("check", help="validate and run checks"))

    show = subparsers.add_parser("show", help="compact summary for hook injection")
    add_record_option(show)
    show.add_argument("--max-chars", type=int, default=1500)

    init = subparsers.add_parser("init", help="create a new record")
    add_record_option(init)
    init.add_argument("--objective", required=True)
    init.add_argument("--quote", required=True)

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
