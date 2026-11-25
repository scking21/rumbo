"""Replay the Stop blocks of earlier eval runs against a version of the reply reader.

usage: python3 scripts/replay_stop_blocks.py [--scripts DIR] [--told] RUN_DIR [RUN_DIR ...]

Each RUN_DIR holds the summary.json that scripts/claude_multiturn_eval.py
writes, and its sessions' transcripts. For every saved block whose problems are
all assumed values (UNSOURCED lines), the replay rebuilds each check from the
values the block names and the values the session's final record holds for it
(or stand-ins), sources the values the block does not name, and asks
the reader in DIR/record.py (default: this tree's rumbo/scripts) whether the
reply the gate read before that block states it. With --told, the session's
earlier replies are read first, in order, and what they stated in full counts as
told, as the Stop gate remembers it since 0.3.17; this assumes each check had
the same values at those earlier stops.

A rebuilt check must validate, pass its arithmetic and leave unsourced exactly
the values its block names. A block with a check that cannot be rebuilt that
way, such as a price per unit whose head count no record holds, is counted
apart rather than judged on a different check.

This measures a change to the reader against real replies; it does not rerun
sessions. A block passes when every one of its problems is read as stated.
"""
import argparse
import importlib.util
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The eval runner's own test for a message the person typed, so skill text,
# tool results and hook feedback do not count as prompts here either.
from claude_multiturn_eval import _is_user_turn  # noqa: E402

UNSOURCED = re.compile(r"^(C\d+): UNSOURCED (fits_window|within_budget|before)(?: .*?)?: "
                       r"((?:start|end|segments_min|amounts|total_cap|item_cap|first|second) .*) "
                       r"not in the user's quoted words$")
UNSET_CAP = 987654


def load_reader(scripts):
    spec = importlib.util.spec_from_file_location("replayed_record", os.path.join(scripts, "record.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _number(text):
    return float(text) if "." in text else int(text)


def _phrases(check, reader):
    """(label, words that source it) for every value of check, labelled as the gate's UNSOURCED lines are."""
    fmt = reader.fmt_num
    out = []
    if check["kind"] == "fits_window":
        out += [("start " + check["start"], check["start"]), ("end " + check["end"], check["end"])]
        out += [("segments_min %s" % fmt(seg), "%s minutes" % fmt(seg)) for seg in check["segments_min"]]
    elif check["kind"] == "within_budget":
        for amount in check["amounts"]:
            if isinstance(amount, dict):
                out += [("amounts %s %s" % (key, fmt(amount[key])), fmt(amount[key])) for key in ("unit", "quantity")]
            else:
                out.append(("amounts %s" % fmt(amount), "$" + fmt(amount)))
        for cap in ("total_cap", "item_cap"):
            if check.get(cap) is not None:
                out.append(("%s %s" % (cap, fmt(check[cap])), "$" + fmt(check[cap])))
    else:
        for field in ("first", "second"):
            out.append(("%s month-day %s" % (field, check[field]), check[field][-5:]))
            if len(check[field]) == 10:
                out.append(("%s year %s" % (field, check[field][:4]), check[field][:4]))
    return out


def _stand_in(kind, values):
    """The check a block line describes, with stand-ins for the values it does not name, or None.

    A price per unit or a head count alone cannot be rebuilt: its entry's total
    needs the other factor, and a stand-in would judge a different total.
    """
    named = [value.split() for value in values]
    if kind == "fits_window":
        check = {"start": "00:00", "end": "23:59", "segments_min": []}
        for parts in named:
            if parts[0] in ("start", "end"):
                check[parts[0]] = parts[1]
            else:
                check["segments_min"].append(int(parts[1]))
        check["segments_min"] = check["segments_min"] or [1]
    elif kind == "within_budget":
        if any(parts[1] in ("unit", "quantity") for parts in named if parts[0] == "amounts"):
            return None
        check = {"amounts": [_number(parts[1]) for parts in named if parts[0] == "amounts"] or [0],
                 "total_cap": UNSET_CAP}
        for parts in named:
            if parts[0] in ("total_cap", "item_cap"):
                check[parts[0]] = _number(parts[1])
    else:
        days = {"first": "01-01", "second": "12-31"}
        years = {}
        for parts in named:
            (days if parts[1] == "month-day" else years)[parts[0]] = parts[2]
        if years:
            # A year the block does not name was sourced, so it differs from the named ones.
            years.setdefault("first", str(int(min(years.values())) - 1))
            years.setdefault("second", str(int(max(years.values())) + 1))
            check = {field: "%s-%s" % (years[field], days[field]) for field in ("first", "second")}
        else:
            check = dict(days)
    return check


def rebuild(line, reader, final=None):
    """(check id, one-check record) for a block's UNSOURCED line, or None when it cannot be rebuilt.

    final is the check with the same id in the session's final record, if any:
    it supplies the values the block does not name, such as the head count
    behind a price per unit. Otherwise those values get stand-ins. Either way
    the rebuilt check must validate, pass its arithmetic and leave unsourced
    exactly the values the block names.
    """
    match = UNSOURCED.match(line)
    if not match:
        return None
    check_id, kind, values = match.group(1), match.group(2), [v.strip() for v in match.group(3).split(",")]
    candidates = []
    if isinstance(final, dict) and final.get("kind") == kind:
        candidates.append({key: value for key, value in final.items() if key not in ("label", "replaces", "dropped_by")})
    candidates.append(_stand_in(kind, values))
    for check in candidates:
        if check is None:
            continue
        check = dict(check, id=check_id, kind=kind, refs=[])
        left = list(values)
        words = []
        try:
            for label, phrase in _phrases(check, reader):
                if label in left:
                    left.remove(label)
                else:
                    words.append(phrase)
        except (KeyError, TypeError, ValueError):
            continue
        record = {"version": 1, "objective": {"text": "Replay", "quote": "We plan for %s." % "; ".join(words or ["it"])},
                  "items": [], "checks": [check]}
        if reader.validate_record(record) or not reader.evaluate_check(check)[0]:
            continue
        if sorted(label for label, _reading, _value in reader._unsourced(record, check)) == sorted(values):
            return check_id, record
    return None


def _texts(entry):
    if entry.get("type") != "assistant":
        return []
    content = (entry.get("message") or {}).get("content") or []
    return [block["text"] for block in content if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str) and block["text"].strip()]


def _is_block(entry):
    attachment = entry.get("attachment") if isinstance(entry.get("attachment"), dict) else {}
    return attachment.get("hookEvent") == "Stop" and attachment.get("type") == "hook_blocking_error"


def stops(transcript):
    """[(is a block, reply)] for each stop the gate read: before each prompt and block, and at the end.

    The reply is the last assistant text so far, as the harness reports it; a
    block before any text gets an empty reply, so blocks stay in order.
    """
    out, last = [], None
    with open(transcript, encoding="utf-8") as handle:
        for raw in handle:
            entry = json.loads(raw)
            texts = _texts(entry)
            if texts:
                last = texts[-1]
            if _is_block(entry):
                out.append((True, last or ""))
            elif _is_user_turn(entry) and last is not None:
                out.append((False, last))
    if last is not None:
        out.append((False, last))
    return out


def replay(reader, run_dirs, told=False):
    """(blocks with check problems, assumption-only blocks rebuilt, those read as stated, names of the passing
    ones, assumption-only blocks that could not be rebuilt)."""
    total = assumed = passed = skipped = 0
    names = []
    for run_dir in run_dirs:
        with open(os.path.join(run_dir, "summary.json"), encoding="utf-8") as handle:
            sessions = json.load(handle)["sessions"]
        for row in sessions:
            if not row.get("blocks") or not row.get("transcript") or not os.path.isfile(row["transcript"]):
                continue
            session_stops = stops(row["transcript"])
            final = {}
            record_path = os.path.join(os.path.dirname(row["transcript"]), "project", ".rumbo", "record.json")
            try:
                with open(record_path, encoding="utf-8") as handle:
                    final = {check.get("id"): check for check in json.load(handle).get("checks") or []
                             if isinstance(check, dict)}
            except (OSError, ValueError, AttributeError):
                pass
            block_stops = [n for n, (is_block, _reply) in enumerate(session_stops) if is_block]
            for index, block in enumerate(row["blocks"]):
                problems = [line for line in block["reason"].splitlines() if re.match(r"^C\d+: ", line)]
                if not problems or index >= len(block_stops):
                    continue
                total += 1
                if not all(UNSOURCED.match(line) for line in problems):
                    continue
                rebuilt = [rebuild(line, reader, final.get(line.split(":")[0])) for line in problems]
                if not all(rebuilt):
                    skipped += 1
                    continue
                assumed += 1
                at = block_stops[index]
                reply = session_stops[at][1]
                ok = True
                for check_id, record in rebuilt:
                    memory = {}
                    if told and hasattr(reader, "_stated"):
                        for _is_block_stop, earlier in session_stops[:at]:
                            for told_id, labels in reader._stated(record, earlier, memory)[0].items():
                                have = memory.setdefault(told_id, [])
                                for label in set(labels):
                                    have.extend([label] * (labels.count(label) - have.count(label)))
                    stated = reader.stated_checks(record, reply, memory) if memory else reader.stated_checks(record, reply)
                    ok = ok and check_id in stated
                if ok:
                    passed += 1
                    names.append("%s %s run %d turn %d" % (os.path.basename(os.path.normpath(run_dir)),
                                                           os.path.basename(os.path.normpath(row["case"])),
                                                           row["run"], block["turn"]))
    return total, assumed, passed, names, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("runs", nargs="+", metavar="RUN_DIR")
    parser.add_argument("--scripts", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                                                          "rumbo", "scripts"),
                        help="folder holding the record.py whose reader to replay")
    parser.add_argument("--told", action="store_true", help="count what earlier replies stated in full as told")
    args = parser.parse_args(argv)
    reader = load_reader(args.scripts)
    total, assumed, passed, names, skipped = replay(reader, args.runs, args.told)
    for name in names:
        print("read as stated: " + name)
    print("blocks with check problems: %d; with only assumed values: %d rebuilt, %d not; read as stated: %d"
          % (total, assumed, skipped, passed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
