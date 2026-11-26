#!/usr/bin/env python3
"""What agents did after the pre-write hook held a write, in multi-turn eval runs.

usage: python3 scripts/hold_outcomes.py RUN_DIR [RUN_DIR ...]

Each RUN_DIR holds sessions written by scripts/claude_multiturn_eval.py, each
with its transcript.jsonl. A held write is a Write, Edit or MultiEdit whose
tool result is an error starting "PreToolUse:" with the plugin's "rumbo:" text.
For each one this prints its turn, what the hold showed (no record, problems,
undecided items, or both) and what came next in that turn: the same file
written again with changed content, written again unchanged, or not written
again. Then one line per RUN_DIR with the counts.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_multiturn_eval import _is_user_turn  # noqa: E402

WRITES = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def _body(tool):
    """What a write puts in the file, comparable between a held write and the next one."""
    given = tool.get("input") or {}
    if tool.get("name") == "Write":
        return given.get("content")
    return json.dumps({key: value for key, value in given.items() if key != "file_path"}, sort_keys=True)


def _kind(text):
    if "no decision record" in text:
        return "no record"
    problems, undecided = "open problems" in text, "NOT DECIDED" in text
    return "problems and undecided" if problems and undecided else "problems" if problems else "undecided"


def holds(transcript):
    """[(turn, kind, file, outcome)] for each held write in a session's transcript."""
    entries = []
    with open(transcript, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                entries.append(json.loads(line))
    tools, turns, turn = {}, [], 0
    for entry in entries:
        turn += _is_user_turn(entry)
        turns.append(turn)
        if entry.get("type") == "assistant":
            for block in entry.get("message", {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block.get("id")] = block
    found = []
    for index, entry in enumerate(entries):
        content = entry.get("message", {}).get("content") if entry.get("type") == "user" else None
        for block in content if isinstance(content, list) else []:
            if not (isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error")):
                continue
            text = block.get("content")
            if isinstance(text, list):
                text = " ".join(part.get("text", "") for part in text if isinstance(part, dict))
            if not (isinstance(text, str) and text.startswith("PreToolUse:") and "rumbo:" in text):
                continue
            held = tools.get(block.get("tool_use_id")) or {}
            path = (held.get("input") or {}).get("file_path") or (held.get("input") or {}).get("notebook_path")
            outcome = "not written again"
            for later in entries[index + 1:]:
                if _is_user_turn(later):
                    break
                if later.get("type") != "assistant":
                    continue
                again = [b for b in later.get("message", {}).get("content") or [] if isinstance(b, dict)
                         and b.get("type") == "tool_use" and b.get("name") in WRITES
                         and ((b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")) == path]
                if again:
                    outcome = "unchanged" if _body(again[0]) == _body(held) else "changed"
                    break
            found.append((turns[index], _kind(text), os.path.basename(path or "?"), outcome))
    return found


def main(argv=None):
    folders = sys.argv[1:] if argv is None else argv
    if not folders:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    for folder in folders:
        counts = collections.Counter()
        for name in sorted(os.listdir(folder)):
            transcript = os.path.join(folder, name, "transcript.jsonl")
            if not os.path.isfile(transcript):
                continue
            for turn, kind, path, outcome in holds(transcript):
                counts["holds"] += 1
                counts[outcome] += 1
                print("%s %s turn %d: %s held (%s), %s" % (os.path.basename(os.path.normpath(folder)), name, turn,
                                                         path, kind, outcome))
        print("%s: %d held writes, %d changed, %d unchanged, %d not written again" % (
            os.path.basename(os.path.normpath(folder)), counts["holds"], counts["changed"], counts["unchanged"],
            counts["not written again"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
