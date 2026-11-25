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
graders: an llm grader judges the file it focuses on (plan.md), or for
`focus: trace` the assistant's replies, with a judge model and the majority
of three votes; a file_exists grader globs its path in the project. An
incomplete session is not graded. Results are small samples; compare arms over several runs.

--regrade DIR grades the complete sessions of an earlier run again with each
case's current graders, as a run with --grade would, without running any
session, and rewrites DIR/summary.json; use it after adding or changing a
grader. Run it from the directory the run started in, since the summary keeps
case paths as given.

--rerun DIR runs the incomplete sessions of an earlier run again, in place and
with the run's plugin and model, for instance after a usage limit cut a batch
short; add --grade to grade them. Each one starts over in a fresh project, and
DIR/summary.json gets its new row.
"""
import argparse
import concurrent.futures
import glob
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


def run_session(case, plugin, model, out, timeout=900):
    project = os.path.join(out, "project")
    os.makedirs(project, exist_ok=True)
    env = dict(os.environ, RUMBO_STATE_DIR=os.path.join(out, "state"))
    session, costs, failure = None, [], None
    for turn in turns_of(case):
        command = ["claude", "-p", turn, "--model", model, "--plugin-dir", plugin, "--output-format", "json",
                   "--allowedTools", *TOOLS, "--disallowedTools", "WebFetch", "WebSearch", "Agent", "Task"]
        if session:
            command += ["--resume", session]
        number = len(costs) + 1
        try:
            done = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            failure = "turn %d: no result within %d s" % (number, timeout)
            break
        except OSError as error:
            failure = "turn %d: could not run claude: %s" % (number, error)
            break
        try:
            result = json.loads(done.stdout)
        except ValueError:
            failure = "turn %d: claude -p printed no result: %s" % (number, (done.stderr or done.stdout)[-300:])
            break
        session = result.get("session_id") or session
        if result.get("is_error"):
            failure = "turn %d: %s" % (number, str(result.get("result"))[:200])
            break
        costs.append(result.get("total_cost_usd"))
    copy = None
    if session:
        slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(project))
        transcript = os.path.expanduser("~/.claude/projects/%s/%s.jsonl" % (slug, session))
        if os.path.isfile(transcript):
            copy = os.path.join(out, "transcript.jsonl")
            shutil.copy(transcript, copy)
    return {"session": session, "turns": len(costs), "cost": costs[-1] if costs else None,
            "failure": failure, "transcript": copy}


def _is_user_turn(entry):
    """True for a message the person typed, not a tool result, skill text or hook feedback."""
    if entry.get("type") != "user" or entry.get("isMeta") or "toolUseResult" in entry:
        return False
    content = entry.get("message", {}).get("content")
    text = content if isinstance(content, str) else " ".join(
        block.get("text", "") for block in content or [] if isinstance(block, dict) and block.get("type") == "text")
    return bool(text) and not text.startswith(("Base directory", "Stop hook feedback"))


def replies(transcript):
    """What the assistant wrote to the person: every text message, marked with its turn."""
    turn, parts = 0, []
    for line in open(transcript, encoding="utf-8"):
        entry = json.loads(line)
        turn += _is_user_turn(entry)
        if entry.get("type") == "assistant":
            for block in entry.get("message", {}).get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    parts.append("[reply in turn %d]\n%s" % (turn, block["text"].strip()))
    return "\n\n".join(parts)


def read_session(transcript):
    """(blocks, turns whose replies name a record id): blocks are (turn, reason)."""
    turn, blocks, naming = 0, [], set()
    for line in open(transcript, encoding="utf-8"):
        entry = json.loads(line)
        attachment = entry.get("attachment") if isinstance(entry.get("attachment"), dict) else {}
        turn += _is_user_turn(entry)
        if attachment.get("hookEvent") == "Stop" and attachment.get("type") == "hook_blocking_error":
            blocks.append((turn, attachment.get("blockingError", {}).get("blockingError", "")))
        if entry.get("type") == "assistant":
            for block in entry.get("message", {}).get("content") or []:
                if block.get("type") == "text" and RECORD_ID.search(block.get("text", "")):
                    naming.add(turn)
    return blocks, sorted(naming)


def grade(case, project, transcript, judge, only=None):
    """Verdict per grader: PASS, FAIL, ERROR (no judge answer), MISSING (no evidence) or SKIPPED (unsupported).

    An llm grader whose focus is a file judges that file; any other llm grader
    (focus: trace) judges the assistant's replies. A file_exists grader globs
    its path in the project. With only, just the graders it names are graded,
    and their votes join the ones saved earlier.
    """
    verdicts, all_votes = {}, {}
    folder = os.path.join(case, "graders")
    for name in sorted(os.listdir(folder)):
        key = name[:-3]
        if only is not None and key not in only:
            continue
        text = open(os.path.join(folder, name), encoding="utf-8").read()
        meta = FRONT_MATTER.match(text)
        header = meta.group(1) if meta else ""
        kind = (re.search(r"^type:\s*(\S+)", header, re.M) or [None, None])[1]
        if kind == "file_exists":
            pattern = re.search(r'^path:\s*"?([^"\n]+?)"?\s*$', header, re.M)
            wanted = re.search(r"^exists:\s*(true|false)\s*$", header, re.M | re.I)
            if not pattern or not wanted:
                verdicts[key] = "SKIPPED"
                continue
            found = bool(glob.glob(os.path.join(project, pattern.group(1)), recursive=True))
            verdicts[key] = "PASS" if found == (wanted.group(1).lower() == "true") else "FAIL"
            continue
        if kind != "llm":
            verdicts[key] = "SKIPPED"
            continue
        focus = re.search(r"^focus:\s*\{[^}]*source:\s*file[^}]*path:\s*([^\s},]+)", header, re.M)
        if focus:
            target = os.path.join(project, focus.group(1))
            document = open(target, encoding="utf-8").read() if os.path.isfile(target) else ""
        else:
            document = replies(transcript) if transcript else ""
        if not document.strip():
            verdicts[key] = "MISSING"
            continue
        prompt = "%s\n\n<document>\n%s\n</document>\n\n%s" % (FRONT_MATTER.sub("", text).strip(), document, VERDICT_ASK)
        votes = []
        for _ in range(3):
            try:
                # The prompt goes on stdin: a long session's replies would pass
                # the 128 KB limit on one command-line argument.
                done = subprocess.run(["claude", "-p", "--model", judge, "--tools", "", "--output-format", "json"],
                                      input=prompt, capture_output=True, text=True, timeout=300, cwd=project)
                answer = json.loads(done.stdout)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                answer = {"is_error": True}
            # A judge that failed (a usage limit, say) has no verdict; never count it as FAIL.
            votes.append("ERROR" if answer.get("is_error") else vote_of(answer.get("result")))
        verdicts[name[:-3]] = verdict_of(votes)
        all_votes[name[:-3]] = votes
    # Each judge's votes, beside the session, to see how often the judges disagree.
    votes_path = os.path.join(os.path.dirname(os.path.normpath(project)), "judge-votes.json")
    if only is not None:
        try:
            with open(votes_path, encoding="utf-8") as handle:
                earlier = json.load(handle)
            if isinstance(earlier, dict):
                all_votes = dict(earlier, **all_votes)
        except (OSError, ValueError):
            pass
    try:
        with open(votes_path, "w", encoding="utf-8") as handle:
            json.dump(all_votes, handle, indent=1)
    except OSError:
        pass
    return verdicts


# Asked for a bare word, a small judge split its three votes on about a third of
# the gradings of one 24-session run, including replies that plainly met the
# grader. Reasoning first and a verdict line last makes each vote a judgment.
VERDICT_ASK = ("Think it through in two or three sentences, quoting the reply where it matters, then end with a "
               "line that is exactly VERDICT: PASS or VERDICT: FAIL.")
VERDICT_LINE = re.compile(r"VERDICT:\s*\**\s*(PASS|FAIL)\b", re.IGNORECASE)


def vote_of(result):
    """PASS or FAIL from the judge's last verdict line, a bare PASS or FAIL, or ERROR without either."""
    text = str(result or "").strip()
    found = VERDICT_LINE.findall(text)
    if found:
        return found[-1].upper()
    word = (text.split() or ["?"])[0].strip("*.:").upper()
    return word if word in ("PASS", "FAIL") else "ERROR"


def verdict_of(votes):
    """The majority of the votes that gave a verdict; ERROR without a majority of at least two."""
    passed, failed = votes.count("PASS"), votes.count("FAIL")
    if passed >= 2 and passed > failed:
        return "PASS"
    if failed >= 2 and failed > passed:
        return "FAIL"
    return "ERROR"


def regrade(folder, judge, errors_only=False):
    """Grade an earlier run's complete sessions again with each case's current graders.

    With errors_only, only the graders whose verdict is ERROR are graded again
    (a usage limit, say, cut the judge off) and every other verdict is kept.
    """
    path = os.path.join(folder, "summary.json")
    with open(path, encoding="utf-8") as handle:
        summary = json.load(handle)
    for row in summary["sessions"]:
        # As in a run: an incomplete session is not graded, while a complete one
        # without a transcript still is (its trace graders report MISSING).
        if row.get("failure"):
            continue
        if not os.path.isdir(os.path.join(row["case"], "graders")):
            print("%s run %d: no graders at %s; run --regrade from where the run started" % (
                os.path.basename(os.path.normpath(row["case"])), row["run"], row["case"]), file=sys.stderr)
            continue
        out = os.path.join(folder, "%s-%d" % (os.path.basename(os.path.normpath(row["case"])), row["run"]))
        if not errors_only:
            row["graders"] = grade(row["case"], os.path.join(out, "project"), row.get("transcript"), judge)
            continue
        earlier = row.get("graders") or {}
        only = {name for name, verdict in earlier.items() if verdict == "ERROR"}
        if only:
            row["graders"] = dict(earlier, **grade(row["case"], os.path.join(out, "project"),
                                                   row.get("transcript"), judge, only))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=1)
    report(summary["sessions"])
    return 0


def report(rows):
    for row in rows:
        graded = row.get("graders")
        print("%s run %d: %d turns, $%.3f, %d Stop blocks at turns %s, record ids named at turns %s%s%s" % (
            os.path.basename(os.path.normpath(row["case"])), row["run"], row["turns"], row["cost"] or 0,
            len(row["blocks"]), [b["turn"] for b in row["blocks"]], row["naming_ids"],
            "" if graded is None else ", graders %d/%d" % (
                list(graded.values()).count("PASS"), len([v for v in graded.values() if v != "SKIPPED"])),
            "" if not row["failure"] else ", INCOMPLETE (%s)" % row["failure"]))


def run_one(case, n, root, plugin, model, turn_timeout, judge=None):
    """Run of case number n under root, as a summary row; with judge, a complete session is graded."""
    out = os.path.join(root, "%s-%d" % (os.path.basename(os.path.normpath(case)), n))
    row = dict(case=case, run=n, session=None, turns=0, cost=None, transcript=None, failure=None,
               blocks=[], naming_ids=[])
    # One broken session, transcript or judge must not lose the others' results.
    try:
        row.update(run_session(case, plugin, model, out, turn_timeout))
        if row["transcript"]:
            blocks, row["naming_ids"] = read_session(row["transcript"])
            row["blocks"] = [{"turn": turn, "reason": reason} for turn, reason in blocks]
        # An incomplete session has no final artifact to judge, and judging a
        # partial one would mix unfinished cases into the comparison.
        if judge and not row["failure"]:
            row["graders"] = grade(case, os.path.join(out, "project"), row["transcript"], judge)
    except Exception as error:
        row["failure"] = row["failure"] or "%s: %s" % (type(error).__name__, error)
    if row["failure"]:
        row["failure"] = " ".join(row["failure"].split())
    return row


def rerun(folder, judge, jobs, turn_timeout):
    """Run an earlier run's incomplete sessions again, in place, with the run's plugin and model."""
    path = os.path.join(folder, "summary.json")
    with open(path, encoding="utf-8") as handle:
        summary = json.load(handle)
    rows = summary["sessions"]
    todo = []
    for index, row in enumerate(rows):
        if not row.get("failure"):
            continue
        if not os.path.isfile(os.path.join(row["case"], "prompt.md")):
            print("%s run %d: no case at %s; run --rerun from where the run started" % (
                os.path.basename(os.path.normpath(row["case"])), row["run"], row["case"]), file=sys.stderr)
            continue
        todo.append(index)

    def again(index):
        row = rows[index]
        out = os.path.join(folder, "%s-%d" % (os.path.basename(os.path.normpath(row["case"])), row["run"]))
        # The session starts over in a fresh project, as in the first run.
        if os.path.realpath(os.path.dirname(out)) == os.path.realpath(folder) and os.path.isdir(out):
            shutil.rmtree(out)
        return run_one(row["case"], row["run"], folder, summary["plugin"], summary["model"], turn_timeout, judge)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for index, row in zip(todo, pool.map(again, todo)):
            rows[index] = row
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=1)
    report(rows)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cases", nargs="*", help="eval case directories holding prompt.md")
    parser.add_argument("--out", help="new or empty directory for sessions and summary.json")
    parser.add_argument("--regrade", metavar="DIR",
                        help="grade an earlier run's sessions in DIR again instead of running sessions")
    parser.add_argument("--errors-only", action="store_true",
                        help="with --regrade, grade again only the verdicts the judge could not give")
    parser.add_argument("--rerun", metavar="DIR",
                        help="run an earlier run's incomplete sessions in DIR again, with its plugin and model")
    parser.add_argument("--plugin-dir", default=os.path.join(os.path.dirname(__file__), os.pardir, "rumbo"))
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=1, help="sessions to run at once; they share one usage window")
    parser.add_argument("--turn-timeout", type=int, default=900, help="seconds a turn may take")
    parser.add_argument("--grade", action="store_true")
    parser.add_argument("--judge-model", default="haiku")
    parser.add_argument("--allow-shell", action="store_true",
                        help="required: the agent under test runs shell commands without asking")
    args = parser.parse_args(argv)
    if args.regrade:
        if args.cases or args.out:
            parser.error("--regrade takes the run's directory only, no cases or --out")
        if shutil.which("claude") is None:
            parser.error("the claude CLI is not on PATH")
        return regrade(args.regrade, args.judge_model, args.errors_only)
    if args.errors_only:
        parser.error("--errors-only goes with --regrade DIR")
    if args.rerun:
        if args.cases or args.out:
            parser.error("--rerun takes the run's directory only, no cases or --out")
    elif not args.cases or not args.out:
        parser.error("give the case directories and --out, --regrade DIR or --rerun DIR")
    if not args.allow_shell:
        parser.error("--allow-shell is required; the agent under test runs shell commands without asking")
    if shutil.which("claude") is None:
        parser.error("the claude CLI is not on PATH")
    if args.rerun:
        return rerun(args.rerun, args.judge_model if args.grade else None, args.jobs, args.turn_timeout)
    if os.path.isdir(args.out) and os.listdir(args.out):
        parser.error("--out must be a new or empty directory")
    plugin = os.path.realpath(args.plugin_dir)
    jobs = [(case, n) for case in args.cases for n in range(1, args.runs + 1)]

    def one(job):
        return run_one(job[0], job[1], args.out, plugin, args.model, args.turn_timeout,
                       args.judge_model if args.grade else None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        rows = list(pool.map(one, jobs))
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump({"plugin": plugin, "model": args.model, "sessions": rows}, handle, indent=1)
    report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
