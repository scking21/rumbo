#!/usr/bin/env python3
"""Run Claude adapter eval cases as multi-turn conversations and summarize them.

Each blank-line-separated paragraph of a case's prompt.md (after its front
matter) is sent as its own turn with `claude -p --resume`, with the plugin
loaded from --plugin-dir, in a fresh project directory under --out. The
bundled cases are single prompts for `claude plugin eval`; sent one paragraph
at a time they exercise what only shows across turns: Stop gate blocks,
records that outlive the decisions behind them, and replies that name record
ids to the user.

This needs a logged-in Claude Code CLI and spends model usage on your account:
each session is a full conversation (a 15-turn sonnet session cost about
$0.6 to $1.1 when this was written), and sessions run at once share one usage
window, so a few in parallel can use it up. A turn that fails, for example on
a usage limit, ends its session, which is then reported as incomplete. The
agent under test runs shell commands without asking, so the script refuses to
run without --allow-shell; run it in a container or VM you can discard.

    python3 scripts/claude_multiturn_eval.py --allow-shell --out /tmp/mt --runs 2 \\
        rumbo/evals/01-workshop-full rumbo/evals/02-launch-full

The summary counts the Stop hook's blocks, the replies that named a record id
such as C5 to the user, and each session's cost. --grade also runs the case's
graders on the file they focus on (plan.md) with a judge model, majority of
three votes. Results are small samples; compare arms over several runs.
"""
import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys

TOOLS = ["Bash", "Read", "Write", "Edit", "Skill", "Glob", "Grep"]
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
RECORD_ID = re.compile(r"\b[CI]\d+\b")


def turns_of(case):
    text = open(os.path.join(case, "prompt.md"), encoding="utf-8").read()
    return [part.strip() for part in FRONT_MATTER.sub("", text).split("\n\n") if part.strip()]


def run_session(case, plugin, model, out):
    project = os.path.join(out, "project")
    os.makedirs(project, exist_ok=True)
    env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(out, "state"))
    session, costs, failure = None, [], None
    for turn in turns_of(case):
        command = ["claude", "-p", turn, "--model", model, "--plugin-dir", plugin, "--output-format", "json",
                   "--allowedTools", *TOOLS, "--disallowedTools", "WebFetch", "WebSearch", "Agent", "Task"]
        if session:
            command += ["--resume", session]
        done = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True, timeout=900)
        try:
            result = json.loads(done.stdout)
        except ValueError:
            raise SystemExit("claude -p failed in %s: %s" % (out, (done.stderr or done.stdout)[-500:]))
        session = result.get("session_id") or session
        if result.get("is_error"):
            failure = "turn %d: %s" % (len(costs) + 1, str(result.get("result"))[:200])
            break
        costs.append(result.get("total_cost_usd"))
    if session is None:
        raise SystemExit("no session was started in %s: %s" % (out, failure))
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(project))
    transcript = os.path.expanduser("~/.claude/projects/%s/%s.jsonl" % (slug, session))
    shutil.copy(transcript, os.path.join(out, "transcript.jsonl"))
    return {"session": session, "turns": len(costs), "cost": costs[-1] if costs else None, "failure": failure}


def read_session(transcript):
    """(blocks, turns whose replies name a record id): blocks are (turn, reason)."""
    turn, blocks, naming = 0, [], set()
    for line in open(transcript, encoding="utf-8"):
        entry = json.loads(line)
        attachment = entry.get("attachment") if isinstance(entry.get("attachment"), dict) else {}
        if entry.get("type") == "user" and not entry.get("isMeta") and "toolUseResult" not in entry:
            content = entry.get("message", {}).get("content")
            text = content if isinstance(content, str) else " ".join(
                block.get("text", "") for block in content or [] if isinstance(block, dict) and block.get("type") == "text")
            if text and not text.startswith(("Base directory", "Stop hook feedback")):
                turn += 1
        if attachment.get("hookEvent") == "Stop" and attachment.get("type") == "hook_blocking_error":
            blocks.append((turn, attachment.get("blockingError", {}).get("blockingError", "")))
        if entry.get("type") == "assistant":
            for block in entry.get("message", {}).get("content") or []:
                if block.get("type") == "text" and RECORD_ID.search(block.get("text", "")):
                    naming.add(turn)
    return blocks, sorted(naming)


def grade(case, project, judge):
    verdicts = {}
    folder = os.path.join(case, "graders")
    for name in sorted(os.listdir(folder)):
        text = open(os.path.join(folder, name), encoding="utf-8").read()
        meta = FRONT_MATTER.match(text)
        if not meta or not re.search(r"^type:\s*llm\s*$", meta.group(1), re.M):
            continue
        path = re.search(r"path:\s*([^\s},]+)", meta.group(1))
        target = os.path.join(project, path.group(1) if path else "plan.md")
        if not os.path.isfile(target):
            verdicts[name[:-3]] = "MISSING"
            continue
        prompt = "%s\n\n<document>\n%s\n</document>\n\nAnswer with exactly one word on the first line: PASS or FAIL." % (
            FRONT_MATTER.sub("", text).strip(), open(target, encoding="utf-8").read())
        votes = []
        for _ in range(3):
            done = subprocess.run(["claude", "-p", prompt, "--model", judge, "--tools", "", "--output-format", "json"],
                                  capture_output=True, text=True, timeout=300, cwd=project)
            try:
                answer = json.loads(done.stdout)
            except ValueError:
                answer = {"is_error": True}
            # A judge that failed (a usage limit, say) has no verdict; never count it as FAIL.
            votes.append("ERROR" if answer.get("is_error") else
                         ((str(answer.get("result", "")).strip().split() or ["?"])[0]).strip("*.:").upper())
        verdicts[name[:-3]] = ("ERROR" if "ERROR" in votes else
                               "PASS" if votes.count("PASS") >= 2 else "FAIL")
    return verdicts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cases", nargs="+", help="eval case directories holding prompt.md")
    parser.add_argument("--out", required=True, help="new or empty directory for sessions and summary.json")
    parser.add_argument("--plugin-dir", default=os.path.join(os.path.dirname(__file__), os.pardir, "rumbo"))
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=1, help="sessions to run at once; they share one usage window")
    parser.add_argument("--grade", action="store_true")
    parser.add_argument("--judge-model", default="haiku")
    parser.add_argument("--allow-shell", action="store_true",
                        help="required: the agent under test runs shell commands without asking")
    args = parser.parse_args(argv)
    if not args.allow_shell:
        parser.error("--allow-shell is required; the agent under test runs shell commands without asking")
    if shutil.which("claude") is None:
        parser.error("the claude CLI is not on PATH")
    if os.path.isdir(args.out) and os.listdir(args.out):
        parser.error("--out must be a new or empty directory")
    plugin = os.path.realpath(args.plugin_dir)
    jobs = [(case, n) for case in args.cases for n in range(1, args.runs + 1)]

    def one(job):
        case, n = job
        out = os.path.join(args.out, "%s-%d" % (os.path.basename(os.path.normpath(case)), n))
        row = dict(case=case, run=n, **run_session(case, plugin, args.model, out))
        blocks, naming = read_session(os.path.join(out, "transcript.jsonl"))
        row.update(blocks=[{"turn": turn, "reason": reason} for turn, reason in blocks], naming_ids=naming)
        if args.grade:
            row["graders"] = grade(case, os.path.join(out, "project"), args.judge_model)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        rows = list(pool.map(one, jobs))
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump({"plugin": plugin, "model": args.model, "sessions": rows}, handle, indent=1)
    for row in rows:
        graded = row.get("graders")
        print("%s run %d: %d turns, $%.3f, %d Stop blocks at turns %s, record ids named at turns %s%s%s" % (
            os.path.basename(os.path.normpath(row["case"])), row["run"], row["turns"], row["cost"] or 0,
            len(row["blocks"]), [b["turn"] for b in row["blocks"]], row["naming_ids"],
            "" if graded is None else ", graders %d/%d" % (list(graded.values()).count("PASS"), len(graded)),
            "" if not row["failure"] else ", INCOMPLETE (%s)" % row["failure"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
