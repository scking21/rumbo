"""Tabulate multi-turn eval runs: grader pass counts, Stop blocks, record ids named and cost per arm.

usage: python3 scripts/eval_summary.py LABEL=DIR [LABEL=DIR ...]

Each DIR holds the summary.json that scripts/claude_multiturn_eval.py writes.
Give the same LABEL to several DIRs to pool them into one column, such as a
run and a later run of the cases it did not have. Prints two markdown tables
and each arm's cost; an incomplete session counts in "complete sessions" only.
"""
import collections
import json
import os
import sys


def load(folder):
    with open(os.path.join(folder, "summary.json"), encoding="utf-8") as handle:
        return json.load(handle)


def tabulate(arms):
    """(labels, table, costs, failures) for [(label, folder), ...]; table[case][label] holds the counts."""
    table = collections.OrderedDict()
    costs = collections.OrderedDict()
    failures = []
    for label, folder in arms:
        costs.setdefault(label, 0.0)
        for row in load(folder)["sessions"]:
            case = os.path.basename(os.path.normpath(row["case"]))
            entry = table.setdefault(case, {}).setdefault(label, {
                "runs": 0, "complete": 0, "passed": collections.Counter(), "graded": collections.Counter(),
                "blocks": 0, "naming": 0})
            entry["runs"] += 1
            costs[label] += row.get("cost") or 0
            if row.get("failure"):
                failures.append((label, case, row["run"], row["failure"]))
                continue
            entry["complete"] += 1
            entry["blocks"] += len(row.get("blocks") or [])
            entry["naming"] += bool(row.get("naming_ids"))
            for name, verdict in (row.get("graders") or {}).items():
                # ERROR, MISSING and SKIPPED are not verdicts on the session.
                if verdict in ("PASS", "FAIL"):
                    entry["graded"][name] += 1
                    entry["passed"][name] += verdict == "PASS"
    return list(costs), table, costs, failures


def render(arms):
    labels, table, costs, failures = tabulate(arms)
    out = ["| Case | Grader | " + " | ".join(labels) + " |", "| --- | --- | " + " | ".join("---" for _ in labels) + " |"]
    for case, by_arm in table.items():
        for name in sorted({name for entry in by_arm.values() for name in entry["graded"]}):
            cells = []
            for label in labels:
                entry = by_arm.get(label)
                cells.append("%d/%d" % (entry["passed"][name], entry["graded"][name])
                             if entry and entry["graded"][name] else "-")
            out.append("| %s | %s | %s |" % (case, name, " | ".join(cells)))
    out += ["", "| Case | Measure | " + " | ".join(labels) + " |", "| --- | --- | " + " | ".join("---" for _ in labels) + " |"]
    for case, by_arm in table.items():
        for measure, title in (("complete", "complete sessions"), ("blocks", "Stop blocks"),
                               ("naming", "sessions naming a record id")):
            cells = []
            for label in labels:
                entry = by_arm.get(label)
                if not entry:
                    cells.append("-")
                elif measure == "complete":
                    cells.append("%d/%d" % (entry["complete"], entry["runs"]))
                else:
                    cells.append(str(entry[measure]))
            out.append("| %s | %s | %s |" % (case, title, " | ".join(cells)))
    out.append("")
    out += ["%s total cost: $%.2f" % (label, costs[label]) for label in labels]
    out += ["INCOMPLETE %s %s run %d: %s" % failure for failure in failures]
    return "\n".join(out)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    arms = [arg.split("=", 1) for arg in args]
    if not arms or any(len(arm) != 2 or not arm[0] or not arm[1] for arm in arms):
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    print(render(arms))
    return 0


if __name__ == "__main__":
    sys.exit(main())
