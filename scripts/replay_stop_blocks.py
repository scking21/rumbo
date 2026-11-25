"""Replay the Stop blocks of earlier eval runs against a version of the reply reader.

usage: python3 scripts/replay_stop_blocks.py [--scripts DIR] [--told] RUN_DIR [RUN_DIR ...]

Each RUN_DIR holds the summary.json that scripts/claude_multiturn_eval.py
writes, and its sessions' transcripts. For every saved block whose problems are
all assumed values (UNSOURCED lines), the replay rebuilds each check from the
values the block names, sources the values the block does not name, and asks
the reader in DIR/record.py (default: this tree's rumbo/scripts) whether the
reply the gate read before that block states it. With --told, the session's
earlier replies are read first, in order, and what they stated in full counts as
told, as the Stop gate remembers it since 0.3.17; this assumes each check had
the same values at those earlier stops.

This measures a change to the reader against real replies; it does not rerun
sessions. A block passes when every one of its problems is read as stated.
"""
import argparse
import importlib.util
import json
import os
import re
import sys

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


def rebuild(line):
    """(check id, one-check record) for a block's UNSOURCED line, or None when it cannot be rebuilt."""
    match = UNSOURCED.match(line)
    if not match:
        return None
    check_id, kind, values = match.group(1), match.group(2), [v.strip() for v in match.group(3).split(",")]
    said = []
    if kind == "fits_window":
        check = {"start": None, "end": None, "segments_min": []}
        for value in values:
            name, _, text = value.partition(" ")
            if name in ("start", "end"):
                check[name] = text
            elif name == "segments_min":
                check["segments_min"].append(int(text))
        # Values the block does not name were sourced: give them a sourced stand-in.
        for name, stand_in in (("start", "00:00"), ("end", "23:59")):
            if check[name] is None:
                check[name] = stand_in
                said.append(stand_in)
        if not check["segments_min"]:
            check["segments_min"] = [1]
            said.append("1 minute")
    elif kind == "within_budget":
        check = {"amounts": [], "total_cap": UNSET_CAP}
        for value in values:
            parts = value.split()
            if parts[0] == "amounts" and parts[1] in ("unit", "quantity"):
                entry = {"unit": 1, "quantity": 1, parts[1]: _number(parts[2])}
                check["amounts"].append(entry)
                said.append("1 each")
            elif parts[0] == "amounts":
                check["amounts"].append(_number(parts[1]))
            elif parts[0] in ("total_cap", "item_cap"):
                check[parts[0]] = _number(parts[1])
        if "total_cap" not in [value.split()[0] for value in values]:
            said.append("a cap of %d" % UNSET_CAP)
        if not check["amounts"]:
            check["amounts"] = [0]
    else:
        check = {"first": None, "second": None}
        for value in values:
            parts = value.split()
            if parts[1] == "month-day":
                check[parts[0]] = parts[2]
        for name, stand_in, words in (("first", "01-01", "January 1"), ("second", "12-31", "December 31")):
            if check[name] is None:
                check[name] = stand_in
                said.append(words)
    check.update(id=check_id, kind=kind, refs=[])
    quote = "We plan for " + " and ".join(said) + "." if said else "We plan."
    return check_id, {"version": 1, "objective": {"text": "Replay", "quote": quote}, "items": [], "checks": [check]}


def _texts(entry):
    if entry.get("type") != "assistant":
        return []
    content = (entry.get("message") or {}).get("content") or []
    return [block["text"] for block in content if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str) and block["text"].strip()]


def _is_block(entry):
    attachment = entry.get("attachment") if isinstance(entry.get("attachment"), dict) else {}
    return attachment.get("hookEvent") == "Stop" and attachment.get("type") == "hook_blocking_error"


def _is_prompt(entry):
    if entry.get("type") != "user":
        return False
    content = (entry.get("message") or {}).get("content")
    return isinstance(content, str) or any(isinstance(block, dict) and block.get("type") == "text"
                                           for block in content or [])


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
            elif _is_prompt(entry) and last is not None:
                out.append((False, last))
    if last is not None:
        out.append((False, last))
    return out


def replay(reader, run_dirs, told=False):
    """(blocks with check problems, assumption-only blocks, those read as stated, names of the passing ones)."""
    total = assumed = passed = 0
    names = []
    for run_dir in run_dirs:
        with open(os.path.join(run_dir, "summary.json"), encoding="utf-8") as handle:
            sessions = json.load(handle)["sessions"]
        for row in sessions:
            if not row.get("blocks") or not row.get("transcript") or not os.path.isfile(row["transcript"]):
                continue
            session_stops = stops(row["transcript"])
            block_stops = [n for n, (is_block, _reply) in enumerate(session_stops) if is_block]
            for index, block in enumerate(row["blocks"]):
                problems = [line for line in block["reason"].splitlines() if re.match(r"^C\d+: ", line)]
                if not problems or index >= len(block_stops):
                    continue
                total += 1
                rebuilt = [rebuild(line) for line in problems]
                if not all(rebuilt):
                    continue
                assumed += 1
                at = block_stops[index]
                reply = session_stops[at][1]
                ok = True
                for check_id, record in rebuilt:
                    if reader.validate_record(record):
                        ok = False
                        break
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
    return total, assumed, passed, names


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("runs", nargs="+", metavar="RUN_DIR")
    parser.add_argument("--scripts", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                                                          "rumbo", "scripts"),
                        help="folder holding the record.py whose reader to replay")
    parser.add_argument("--told", action="store_true", help="count what earlier replies stated in full as told")
    args = parser.parse_args(argv)
    reader = load_reader(args.scripts)
    total, assumed, passed, names = replay(reader, args.runs, args.told)
    for name in names:
        print("read as stated: " + name)
    print("blocks with check problems: %d; with only assumed values: %d; read as stated: %d" % (total, assumed, passed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
