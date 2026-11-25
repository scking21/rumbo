"""The Stop gate reads the reply the user is about to see.

A failing or unsourced check that the reply already states plainly needs no
block: the agent has just told the user. In live sessions on 0.3.10 the gate
blocked such replies anyway, and the agent repeated the same conflicts in a
second message. Statement is word matching on the harness's copy of the reply
(`last_assistant_message`), read with the same readers as the source check.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "record.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import record  # noqa: E402

OBJECTIVE = "I'm organizing a half-day workshop on March 12."
SCHEDULE = "Please draft the schedule: two 75-minute sessions with a 20-minute break, 12:30 close."
START = "The maker-space team just confirmed for the 9:45 session."
PRINTER = "The printer needs final details by March 20."
BUDGET = "Our budget is $600 total, and no line item can exceed $300. Catering is $350."

CONFLICTS = {"version": 1, "objective": {"text": "Workshop March 12", "quote": OBJECTIVE},
             "items": [{"id": "I1", "text": "Schedule", "quote": SCHEDULE, "status": "draft"},
                       {"id": "I2", "text": "Start 9:45", "quote": START, "status": "commitment"},
                       {"id": "I3", "text": "Printer deadline", "quote": PRINTER, "status": "commitment"},
                       {"id": "I4", "text": "Budget", "quote": BUDGET, "status": "commitment"}],
             "checks": [{"id": "C1", "kind": "fits_window", "start": "09:45", "segments_min": [75, 20, 75],
                         "end": "12:30", "refs": ["I1", "I2"]},
                        {"id": "C2", "kind": "before", "first": "03-20", "second": "03-12", "refs": ["I3"]},
                        {"id": "C3", "kind": "within_budget", "amounts": [350], "total_cap": 600,
                         "item_cap": 300, "refs": ["I4"]}]}

SAYS_C1 = "The sessions end at 12:35, after the 12:30 close."
SAYS_C2 = "The printer needs details by March 20, but the workshop is March 12."
SAYS_C3 = "Catering at $350 is over the $300 line-item cap."
SAYS_ALL = "\n".join(["Three conflicts to settle:", "- " + SAYS_C1, "- " + SAYS_C2, "- " + SAYS_C3])


def check(**fields):
    return dict({"id": "C1", "refs": []}, **fields)


def stated(reply, one_check, said, told=None):
    """Ids stated by reply, for a record whose objective quote is the user's words said."""
    document = {"version": 1, "objective": {"text": "Plan", "quote": said}, "items": [], "checks": [one_check]}
    return record.stated_checks(document, reply, told)


AGENDA_SAID = "Please draft a morning agenda for the workshop."
AGENDA = {"version": 1, "objective": {"text": "Workshop", "quote": OBJECTIVE},
          "items": [{"id": "I1", "text": "Agenda", "quote": AGENDA_SAID, "status": "draft"}],
          "checks": [{"id": "C1", "kind": "fits_window", "label": "draft agenda", "start": "09:00",
                      "segments_min": [75, 20, 75], "end": "12:30", "refs": ["I1"]}]}
AGENDA_TOLD = ["start 09:00", "end 12:30", "segments_min 75", "segments_min 20", "segments_min 75"]
# A first reply that lays the agenda out, and a later one that only says it is still open.
AGENDA_IN_FULL = ("Every time here is my assumption, not your decision.\n| 9:00\u201310:15 | Session 1 |\n"
                  "| 10:15\u201310:35 | Break |\n| 10:35\u201311:50 | Session 2 |\nWe close at 12:30.")
AGENDA_STATUS = "Here are the two speakers side by side.\n\nStill open: the 9:00 to 12:30 times are my assumption."


class StatementReadingTests(unittest.TestCase):
    """stated_checks: which problems the reply names."""

    def test_overrun_needs_the_reached_end_and_the_window_end_on_one_line(self):
        late = check(kind="fits_window", start="09:00", segments_min=[60, 5], end="10:00")
        said = "Doors 9:00, a 60-minute talk and 5 minutes of questions, close 10:00."
        self.assertEqual(stated("Sessions run until 10:05, past the 10:00 close.", late, said), {"C1"})
        self.assertEqual(stated("The day ends at 10:05am; we close at 10 a.m.", late, said), {"C1"})
        self.assertEqual(stated("Sessions run until 10:05.\nWe close at 10:00.", late, said), set())

    def test_overrun_can_be_stated_as_the_minutes_over(self):
        late = check(kind="fits_window", start="09:00", segments_min=[60, 5], end="10:00")
        said = "Doors 9:00, a 60-minute talk and 5 minutes of questions, close 10:00."
        for reply in ("Sessions run five minutes past the close.", "The schedule is 5 min too long.",
                      "A 9:05 start conflicts with your schedule by five minutes."):
            self.assertEqual(stated(reply, late, said), {"C1"}, reply)
        # A bare 5, or minutes with nothing that says they run over, is not the overrun.
        for reply in ("Step 5 is over.", "Allow 5 minutes for questions.", "It runs 15 minutes over."):
            self.assertEqual(stated(reply, late, said), set(), reply)

    def test_overnight_overrun_is_read_as_a_clock_time(self):
        late = check(kind="fits_window", start="21:00", segments_min=[270], end="01:00", end_next_day=True)
        said = "9pm to 1am, 270 minutes"
        self.assertEqual(stated("The night runs to 1:30 am, after the 1:00 am end.", late, said), {"C1"})
        self.assertEqual(stated("The night runs to 1:30 pm, after the 1:00 am end.", late, said), set())

    def test_dates_need_an_ordering_word_on_their_line(self):
        late = check(kind="before", first="03-20", second="03-03")
        said = "The event is March 3 and the printer deadline is March 20."
        self.assertEqual(stated("The March 20 deadline falls after the March 3 event.", late, said), {"C1"})
        self.assertEqual(stated("3/20 is 17 days after 3/3.", late, said), {"C1"})
        self.assertEqual(stated("Event: March 3. Printer deadline: March 20.", late, said), set())
        # "before March 20" names the deadline; it does not say the dates conflict.
        self.assertEqual(stated("By March 3, finish what must happen before March 20.", late, said), set())

    def test_dates_in_different_years_need_their_years(self):
        # Review of 0.3.11: a reply that moves the deadline into the other year
        # and says the schedule works must not count as stating the conflict.
        late = check(kind="before", first="2027-03-01", second="2026-03-03")
        said = "The deadline is March 1, 2027 and the launch is March 3, 2026."
        self.assertEqual(stated("March 1, 2026 is earlier than March 3, 2026, so the schedule works.", late, said),
                         set())
        self.assertEqual(stated("The March 1 deadline is after the March 3 launch.", late, said), set())
        self.assertEqual(stated("March 1, 2027 is after March 3, 2026, a year late.", late, said), {"C1"})
        # In one year the month and day decide it, as they do without a year.
        same = check(kind="before", first="2026-03-20", second="2026-03-12")
        said = "The workshop is March 12, 2026 and the printer needs details by March 20, 2026."
        self.assertEqual(stated("The March 20 deadline is after the March 12 workshop.", same, said), {"C1"})

    def test_budget_needs_the_total_and_the_cap(self):
        over = check(kind="within_budget", amounts=[300, 250], total_cap=500)
        said = "Ads are $300 and the newsletter $250; the budget is $500."
        self.assertEqual(stated("Both together cost $550, over the $500 budget.", over, said), {"C1"})
        self.assertEqual(stated("Both together cost $550.", over, said), set())
        self.assertEqual(stated("Both together cost $1,550, over the $500 budget.", over, said), set())

    def test_budget_overrun_can_be_stated_as_its_excess(self):
        # A live reply: "No, 100 flyers at about $1 each don't fit. They're $30 over the budget."
        over = check(kind="within_budget", amounts=[300, 250], total_cap=500)
        said = "Ads are $300 and the newsletter $250; the budget is $500."
        self.assertEqual(stated("They're $50 over the budget.", over, said), {"C1"})
        table = "| **Total** | **$550** |\n| Budget cap | $500 |\n| **Over by** | **$50** |"
        self.assertEqual(stated(table, over, said), {"C1"})
        self.assertEqual(stated("That leaves $50 for flyers.", over, said), set())

    def test_a_cap_of_zero_must_be_said(self):
        # Review of 0.3.11: the source check counts 0 as always sourced, so a
        # zero cap read as stated whatever the reply said.
        over = check(kind="within_budget", amounts=[350], total_cap=0)
        said = "Catering costs $350, and there is no budget: 0."
        self.assertEqual(stated("Catering costs $350. All set!", over, said), set())
        self.assertEqual(stated("Catering costs $350 against a budget of $0.", over, said), {"C1"})
        self.assertEqual(stated("Catering costs $350, but the budget is zero.", over, said), {"C1"})
        # Zeros inside other numbers and times are not a zero.
        for reply in ("Catering costs $350 by 10:00.", "Catering costs $350 of $1,000.", "Catering costs $350, 0.5 of it now."):
            self.assertEqual(stated(reply, over, said), set(), reply)

    def test_item_cap_needs_each_amount_over_it_and_the_cap(self):
        over = check(kind="within_budget", amounts=[350, 320], total_cap=1000, item_cap=300)
        said = "Catering is $350 and the room $320; $1,000 total, at most $300 per item."
        self.assertEqual(stated("$350 and $320 each exceed the $300 item limit.", over, said), {"C1"})
        self.assertEqual(stated("Catering ($350) is over the $300 item limit.", over, said), set())
        self.assertEqual(stated("Catering at $350 is $50 over the limit.\nThe room, $320, is $20 over.", over, said),
                         {"C1"})

    def test_unit_price_overrun_needs_the_product(self):
        over = check(kind="within_budget", amounts=[{"unit": 45, "quantity": 15}], total_cap=600)
        said = "$45 per person for 15, $600 budget"
        self.assertEqual(stated("15 people at $45 is $675, more than the $600 budget.", over, said), {"C1"})
        self.assertEqual(stated("15 people at $45 is over the $600 budget.", over, said), set())

    def test_an_assumed_value_must_be_called_an_assumption_or_asked_about(self):
        assumed = check(kind="fits_window", start="09:00", segments_min=[45], end="10:00")
        said = "Doors 9:00, close 10:00."
        self.assertEqual(stated("I assumed a 45-minute session.", assumed, said), {"C1"})
        self.assertEqual(stated("Is a 45-minute session right?", assumed, said), {"C1"})
        self.assertEqual(stated("The session is 45 minutes (my estimate).", assumed, said), {"C1"})
        self.assertEqual(stated("The session is 45 minutes.", assumed, said), set())
        self.assertEqual(stated("The session is 45 minutes.\nShall I book the room?", assumed, said), set())

    def test_a_section_or_preamble_that_calls_values_estimates_covers_them(self):
        # Live replies put estimates in a table under a heading such as
        # "## Draft budget (my estimates, against the $600 cap)".
        assumed = check(kind="within_budget", amounts=[{"unit": 6, "quantity": 40}, 200], total_cap=600)
        said = "40 people, $600 total."
        table = "| Coffee, 40 x $6 | $240 |\n| Honorarium | $200 |"
        self.assertEqual(stated("## Draft budget (my estimates)\n\n" + table, assumed, said), {"C1"})
        self.assertEqual(stated("Every dollar figure is my own assumption.\n\n## Budget\n" + table, assumed, said),
                         {"C1"})
        self.assertEqual(stated("## Budget\n" + table + "\nThe check flags these as unsourced: they're my est.",
                                assumed, said), {"C1"})
        self.assertEqual(stated("## Budget (my proposal)\n" + table, assumed, said), {"C1"})
        self.assertEqual(stated("## Budget\n" + table + "\nThese amounts are my suggestions.", assumed, said), {"C1"})
        # Three or more words after "you" no longer give the cue to the user.
        self.assertEqual(stated("## Budget\nAs you can see from my estimates:\n" + table, assumed, said), {"C1"})
        # Words that give the value to the user are the claim an unsourced value contradicts.
        for heading in ("## Budget (the figures you suggested)", "## Budget (your estimate)",
                        "## Budget (as you proposed)", "## Budget (your earlier estimate)",
                        "## Budget (as you originally suggested)", "## Budget (you've already estimated it)"):
            self.assertEqual(stated(heading + "\n" + table, assumed, said), set(), heading)
        # A cue in another section does not cover a table it does not head.
        self.assertEqual(stated("## Venue\nI assumed the room is free.\n## Budget\n" + table, assumed, said), set())
        self.assertEqual(stated("## Budget\n" + table, assumed, said), set())

    def test_a_schedule_written_as_time_ranges_states_its_block_lengths(self):
        # A 0.3.15 live session: the reply called its whole draft schedule an
        # assumption and laid it out as ranges ("9:20-10:35"), so it named no
        # block in minutes, and the gate blocked it three turns running.
        draft = check(kind="fits_window", start="09:00", segments_min=[20, 75, 15, 75, 25], end="12:30")
        said = "It's the morning of March 12. Can you help me plan it?"
        reply = ("Here's a first draft. The start time, end time and every dollar figure in it are my assumptions.\n"
                 "## Draft plan\n"
                 "**Schedule (assumed 9:00 to 12:30):**\n"
                 "| Time | Block |\n|---|---|\n"
                 "| 9:00\u20139:20 | Welcome and a warm-up |\n"
                 "| 9:20\u201310:35 | Session 1 |\n"
                 "| 10:35\u201310:50 | Break |\n"
                 "| 10:50\u201312:05 | Session 2 |\n"
                 "| 12:05\u201312:30 | Show-and-tell |")
        self.assertEqual(stated(reply, draft, said), {"C1"})
        # A single time, or a range of another length, states no block length.
        for line in ("| 9:20 | Session 1 |", "| 9:00\u20139:30 | Welcome |"):
            with self.subTest(line=line):
                one = check(kind="fits_window", start="09:00", segments_min=[20], end="12:30")
                self.assertEqual(stated("These times are my assumptions.\n" + line + "\nStart 9:00, end 12:30.", one,
                                        said), set())

    def test_a_range_on_a_known_clock_rolls_over_a_whole_day(self):
        # Review of this change: every range rolled over 12 hours, so "6pm-9am"
        # read as 180 minutes and could clear an assumed three-hour block. A
        # second review found the same for a 24-hour end beside a meridiem.
        said = "We plan an overnight build."
        for line, minutes, expected in (("6pm\u20139am", 180, set()), ("6pm\u20139am", 900, {"C1"}),
                                        ("18:00\u201309:00", 180, set()), ("18:00\u201309:00", 900, {"C1"}),
                                        ("18:00\u20139am", 180, set()), ("18:00\u20139am", 900, {"C1"}),
                                        ("10pm\u201306:30", 510, {"C1"}),
                                        ("9:00 \u2013 10:15pm", 75, {"C1"}), ("12:50\u20131:05", 15, {"C1"})):
            with self.subTest(line=line, minutes=minutes):
                block = check(kind="fits_window", start="00:00", segments_min=[minutes], end="23:59", end_next_day=False)
                reply = "These times are my assumptions.\n| " + line + " | Build |\nStart 00:00, end 23:59."
                self.assertEqual(stated(reply, block, said), expected)

    def test_a_status_line_states_assumed_values_told_in_full_earlier(self):
        # Live sessions on 0.3.15: in 8 of 10 blocks left after the time-range
        # fix, an earlier reply had stated every assumed value, and the blocked
        # later reply still said "9:00-12:30 is my assumption" without
        # repeating each block length.
        agenda = AGENDA["checks"][0]
        self.assertEqual(stated(AGENDA_IN_FULL, agenda, OBJECTIVE), {"C1"})
        self.assertEqual(stated(AGENDA_STATUS, agenda, OBJECTIVE), set())
        self.assertEqual(stated(AGENDA_STATUS, agenda, OBJECTIVE, {"C1": AGENDA_TOLD}), {"C1"})
        # Only for the values told, for that check, with a line that calls them
        # assumptions or asks about them.
        self.assertEqual(stated(AGENDA_STATUS, agenda, OBJECTIVE, {"C1": AGENDA_TOLD[:-1]}), set())
        self.assertEqual(stated(AGENDA_STATUS, agenda, OBJECTIVE, {"C2": AGENDA_TOLD}), set())
        self.assertEqual(stated("We still start at 9:00.", agenda, OBJECTIVE, {"C1": AGENDA_TOLD}), set())
        self.assertEqual(stated("Still starting at 9:00?", agenda, OBJECTIVE, {"C1": AGENDA_TOLD}), {"C1"})
        for told in (None, [], {"C1": "start 09:00"}, {"C1": [None, 3]}):
            self.assertEqual(stated(AGENDA_STATUS, agenda, OBJECTIVE, told), set(), told)

    def test_a_told_check_is_stated_by_a_line_that_calls_its_kind_an_assumption(self):
        # Live, on 0.3.17's first version: "My catering, handout and contingency
        # figures from the budget are still my estimates" named no amount.
        agenda = AGENDA["checks"][0]
        told = {"C1": AGENDA_TOLD}
        for reply, expected in (("The schedule is still my assumption.", {"C1"}),
                                ("Do the agenda times still work for you?", {"C1"}),
                                ("The schedule stays as drafted.", set()),
                                # The cue must be on that line: a section's is not enough
                                # without a value.
                                ("## My assumptions\nThe schedule stays as drafted.", set()),
                                ("The budget is still my estimate.", set())):
            with self.subTest(reply=reply):
                self.assertEqual(stated(reply, agenda, OBJECTIVE, told), expected)
                self.assertEqual(stated(reply, agenda, OBJECTIVE), set())

    def test_values_told_for_a_check_carry_to_the_check_that_replaces_it(self):
        # Live: the agent replaced a told budget check with one holding the same
        # values and new refs, and the gate treated the new one as never told.
        older = dict(AGENDA["checks"][0])
        newer = dict(older, id="C2", replaces=["C1"])
        other = dict(older, id="C3")
        document = {"version": 1, "objective": {"text": "Plan", "quote": OBJECTIVE}, "items": [],
                    "checks": [older, newer, other]}
        told = {"C1": AGENDA_TOLD}
        self.assertEqual(record.stated_checks(document, AGENDA_STATUS, told), {"C2"})
        self.assertEqual(record.stated_checks(document, AGENDA_STATUS, {"C2": AGENDA_TOLD}), {"C2"})
        document["checks"][1] = dict(newer, segments_min=[75, 20, 80])
        self.assertEqual(record.stated_checks(document, AGENDA_STATUS, told), set())
        # A value not told before can be named in this reply instead.
        self.assertEqual(record.stated_checks(document, AGENDA_STATUS + "\nSession 2 is now 80 minutes, my guess.",
                                              told), {"C2"})

    def test_an_assumed_price_per_unit_is_named_by_its_total(self):
        # Live (opus, 0.3.15): "my $280 catering estimate is still $80 over the
        # foundation's $200 cap" named the total, not the $7 a head it assumed.
        said = "40 people are coming. Dr. Okafor's travel is $250 and our budget is $600."
        budget = check(kind="within_budget", amounts=[{"unit": 7, "quantity": 40}, 250], total_cap=600)
        self.assertEqual(stated("My $280 catering estimate stays.", budget, said), {"C1"})
        self.assertEqual(stated("$7 a head is my estimate.", budget, said), {"C1"})
        self.assertEqual(stated("Catering comes to $280.", budget, said), set())
        # A total says nothing about an assumed head count.
        said = "Catering is $7 per person, Dr. Okafor's travel is $250 and our budget is $600."
        self.assertEqual(stated("My $280 catering estimate stays.", budget, said), set())
        self.assertEqual(stated("I assumed 40 people.", budget, said), {"C1"})

    def test_still_open_and_to_be_confirmed_mark_a_value_as_not_decided(self):
        # Live (opus, 0.3.15): "Still open from before: whether to go with the
        # newsletter or social ads, and whether launch day is Oct 3."
        launch = check(kind="before", first="08-20", second="10-03")
        said = "Today is August 20, and we launch on the first Saturday of October."
        for reply, expected in (("Still open from before: whether launch day is Oct 3.", {"C1"}),
                                ("Launch day: Oct 3 (TBD).", {"C1"}),
                                ("Launch on Oct 3, to be confirmed.", {"C1"}),
                                ("## Still open\n- Launch day, Oct 3", {"C1"}),
                                ("Launch day is Oct 3.", set())):
            with self.subTest(reply=reply):
                self.assertEqual(stated(reply, launch, said), expected)

    def test_an_overage_is_an_overrun(self):
        # Live (haiku, 0.3.15): "The 5-minute overage goes away" stated the overrun.
        late = check(kind="fits_window", start="09:45", segments_min=[75, 20, 75], end="12:30")
        said = "A 9:45 start, two 75-minute sessions and a 20-minute break, 12:30 close."
        self.assertEqual(stated("The 5-minute overage goes away with a shorter break.", late, said), {"C1"})
        self.assertEqual(stated("The 5-minute break goes away.", late, said), set())

    def test_a_told_assumption_does_not_state_a_conflict(self):
        late = check(kind="fits_window", start="09:00", segments_min=[75, 20, 75, 60], end="12:30")
        told = {"C1": ["start 09:00", "end 12:30", "segments_min 75", "segments_min 20", "segments_min 75",
                       "segments_min 60"]}
        self.assertEqual(stated(AGENDA_STATUS, late, OBJECTIVE, told), set())
        conflict = "The sessions end at 12:50, after the 12:30 close."
        self.assertEqual(stated(conflict + "\n" + AGENDA_STATUS, late, OBJECTIVE, told), {"C1"})

    def test_an_assumed_year_is_read_on_its_own(self):
        assumed = check(kind="before", first="2026-03-01", second="2026-03-03")
        said = "Copy is due March 1 and the launch is March 3."
        self.assertEqual(stated("I've assumed both dates are in 2026; is that right?", assumed, said), {"C1"})
        self.assertEqual(stated("The dates are in 2026.", assumed, said), set())

    def test_a_failing_check_with_an_assumed_value_needs_both_statements(self):
        late = check(kind="fits_window", start="09:30", segments_min=[60], end="10:00")
        said = "A 60-minute talk, close 10:00."
        conflict = "The session ends at 10:30, after the 10:00 close."
        self.assertEqual(stated(conflict, late, said), set())
        self.assertEqual(stated(conflict + "\nI assumed the 9:30 start.", late, said), {"C1"})
        self.assertEqual(stated("The 9:30 start is my assumption.", late, said), set())

    def test_passing_sourced_checks_and_missing_replies_state_nothing(self):
        fits = check(kind="fits_window", start="09:00", segments_min=[60], end="10:00")
        said = "Doors 9:00, a 60-minute talk, a 65-minute workshop, close 10:00."
        self.assertEqual(stated("Doors at 9:00 and done by 10:00.", fits, said), set())
        late = check(kind="fits_window", start="09:00", segments_min=[65], end="10:00")
        self.assertEqual(stated("It ends at 10:05, after the 10:00 close.", late, said), {"C1"})
        for reply in (None, "", 42, ["10:05 after 10:00"]):
            self.assertEqual(stated(reply, late, said), set(), reply)


class StatedStopGateTests(unittest.TestCase):
    """The Stop gate drops stated problems from its block and passes when all are stated."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "project")
        os.makedirs(os.path.join(self.project, ".rumbo"))
        self.record = os.path.join(self.project, ".rumbo", "record.json")
        self.state = os.path.join(self.tmp.name, "state")
        self.env = dict(os.environ, RUMBO_STATE_DIR=self.state)
        self.transcript = os.path.join(self.tmp.name, "t.jsonl")
        self.write(CONFLICTS)
        self.said(OBJECTIVE, SCHEDULE, START, PRINTER, BUDGET)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, document):
        with open(self.record, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

    def said(self, *messages):
        with open(self.transcript, "w", encoding="utf-8") as handle:
            for text in messages:
                handle.write(json.dumps({"type": "user", "origin": {"kind": "human"},
                                         "message": {"role": "user", "content": text}}) + "\n")

    def stop(self, reply, session="s1", chained=False, **extra):
        payload = dict({"session_id": session, "transcript_path": self.transcript,
                        "stop_hook_active": chained}, **extra)
        if reply is not None:
            payload["last_assistant_message"] = reply
        proc = subprocess.run([sys.executable, SCRIPT, "stop-gate", "--record", self.record],
                              input=json.dumps(payload), text=True, capture_output=True, env=self.env, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        return json.loads(proc.stdout)["reason"] if proc.stdout.strip() else None

    def marker(self, session, suffix):
        names = [name for name in os.listdir(self.state) if name.startswith(session + "-") and name.endswith(suffix)]
        if not names:
            return None
        with open(os.path.join(self.state, names[0]), encoding="utf-8") as handle:
            return handle.read()

    def test_a_status_line_passes_once_the_assumptions_were_told_in_full(self):
        self.write(AGENDA)
        self.said(OBJECTIVE, AGENDA_SAID)
        self.assertIsNone(self.stop(AGENDA_IN_FULL))
        self.assertEqual(sorted(json.loads(self.marker("s1", ".told"))["C1"]), sorted(AGENDA_TOLD))
        # A later turn's reply that only says the times are still assumed.
        self.assertIsNone(self.stop(AGENDA_STATUS))
        self.assertIsNone(self.marker("s1", ".blocks"))
        # Another session has not told the user anything.
        self.assertIn("C1: UNSOURCED fits_window", self.stop(AGENDA_STATUS, session="s2"))

    def test_an_assumed_value_not_yet_told_needs_the_full_statement(self):
        self.write(AGENDA)
        self.said(OBJECTIVE, AGENDA_SAID)
        self.assertIsNone(self.stop(AGENDA_IN_FULL))
        longer = json.loads(json.dumps(AGENDA))
        longer["checks"][0]["segments_min"].append(10)
        self.write(longer)
        reason = self.stop(AGENDA_STATUS)
        self.assertIn("C1: UNSOURCED fits_window draft agenda: start 09:00, end 12:30", reason)
        self.assertIn("segments_min 10", reason)
        # Told in full again, the new value joins the others.
        self.assertIsNone(self.stop(AGENDA_IN_FULL + "\nThen a 10-minute wrap-up, also my assumption.", chained=True))
        self.assertIn("segments_min 10", json.loads(self.marker("s1", ".told"))["C1"])
        self.assertIsNone(self.stop(AGENDA_STATUS))

    def test_told_values_are_forgotten_once_the_problems_are_gone(self):
        self.write(AGENDA)
        self.said(OBJECTIVE, AGENDA_SAID)
        self.assertIsNone(self.stop(AGENDA_IN_FULL))
        settled = json.loads(json.dumps(AGENDA))
        settled["items"][0]["quote"] = ("Start at 9:00 and close at 12:30: two 75-minute sessions "
                                        "with a 20-minute break.")
        self.write(settled)
        self.said(OBJECTIVE, AGENDA_SAID, settled["items"][0]["quote"])
        self.assertIsNone(self.stop("Done."))
        self.assertIsNone(self.marker("s1", ".told"))
        self.write(AGENDA)
        self.assertIn("C1: UNSOURCED fits_window", self.stop(AGENDA_STATUS))

    def test_without_a_session_id_a_status_line_is_not_enough(self):
        self.write(AGENDA)
        self.said(OBJECTIVE, AGENDA_SAID)
        self.assertIsNone(self.stop(AGENDA_IN_FULL, session=None))
        self.assertIn("C1: UNSOURCED fits_window", self.stop(AGENDA_STATUS, session=None))

    def test_a_reply_that_states_every_conflict_passes_without_using_a_block(self):
        self.assertIsNone(self.stop(SAYS_ALL))
        self.assertIsNone(self.marker("s1", ".blocks"))
        self.assertEqual(json.loads(self.marker("s1", ".failed")), ["C1", "C2", "C3"])

    def test_the_block_lists_only_what_the_reply_left_out(self):
        reason = self.stop(SAYS_C1 + "\nWorkshop: March 12. Printer: March 20.\n" + SAYS_C3)
        self.assertIn("C2: FAIL before", reason)
        self.assertNotIn("C1:", reason)
        self.assertNotIn("C3:", reason)
        self.assertIn("Before finishing, resolve each conflict", reason)

    def test_a_reply_that_states_nothing_gets_the_full_block(self):
        reason = self.stop("Here is your plan.")
        for check_id in ("C1", "C2", "C3"):
            self.assertIn(check_id + ": FAIL", reason)

    def test_without_the_reply_field_the_gate_blocks_as_before(self):
        reason = self.stop(None)
        for check_id in ("C1", "C2", "C3"):
            self.assertIn(check_id + ": FAIL", reason)

    def test_answering_a_block_with_the_rest_does_not_block_again(self):
        self.assertIn("C2:", self.stop(SAYS_C1 + "\n" + SAYS_C3))
        # The reply to that block states C2 but not the others: the problems are
        # unchanged, so the stop passes instead of asking about C1 and C3 next.
        self.assertIsNone(self.stop(SAYS_C2, chained=True))
        self.assertEqual(self.marker("s1", ".blocks"), "1")

    def test_a_later_turn_that_states_nothing_gets_the_short_repeat(self):
        self.assertIsNotNone(self.stop(SAYS_C1 + "\n" + SAYS_C3))
        reason = self.stop("Updated the plan.")
        self.assertTrue(reason.startswith("rumbo: still open, unchanged since the last block: C1 (fits_window), "
                                          "C2 (before), C3 (within_budget)."), reason)
        self.assertIn("in the user's terms rather than the record's ids", reason)
        self.assertIsNone(self.stop(SAYS_ALL))
        self.assertEqual(self.marker("s1", ".blocks"), "2")

    def test_the_repeat_names_each_check_by_its_label(self):
        # In live sessions the repeat named only "C5", and the agent wrote
        # "Still open: C5, ..." to a user who has never seen the record.
        document = json.loads(json.dumps(CONFLICTS))
        document["checks"][0]["label"] = "session schedule"
        self.write(document)
        self.assertIsNotNone(self.stop("Plan attached."))
        reason = self.stop("Plan updated.")
        self.assertIn("since the last block: C1 (session schedule), C2 (before), C3 (within_budget).", reason)

    def test_deleting_a_check_that_was_only_ever_stated_is_still_reported(self):
        self.assertIsNone(self.stop(SAYS_ALL))
        document = json.loads(json.dumps(CONFLICTS))
        document["checks"] = [c for c in document["checks"] if c["id"] != "C2"]
        self.write(document)
        reason = self.stop(SAYS_C1 + "\n" + SAYS_C3)
        self.assertIn("C2: check was failing and has been removed from the record", reason)
        self.assertNotIn("C1:", reason)

    def test_problems_that_are_not_checks_still_block(self):
        self.said(OBJECTIVE, SCHEDULE, START, PRINTER)
        reason = self.stop(SAYS_ALL)
        self.assertIn("items[3].quote: UNVERIFIED", reason)
        self.assertNotIn("FAIL", reason)

    def test_an_unreadable_transcript_still_blocks(self):
        os.remove(self.transcript)
        reason = self.stop(SAYS_ALL)
        self.assertIn("TRANSCRIPT_UNREADABLE", reason)
        self.assertNotIn("FAIL", reason)

    def test_a_ledger_problem_uses_its_own_count_when_the_checks_are_stated(self):
        with open(os.path.join(self.project, ".rumbo", "verified-quotes.json"), "w", encoding="utf-8") as handle:
            handle.write("not json")
        reason = self.stop(SAYS_ALL)
        self.assertIn("LEDGER_UNREADABLE", reason)
        self.assertNotIn("FAIL", reason)
        self.assertIsNone(self.marker("s1", ".blocks"))
        self.assertEqual(self.marker("s1", ".ledger-blocks"), "1")

    def test_an_assumption_the_reply_names_passes(self):
        document = json.loads(json.dumps(CONFLICTS))
        document["checks"] = [{"id": "C1", "kind": "fits_window", "start": "09:45", "segments_min": [75, 15, 75],
                               "end": "12:30", "refs": ["I1", "I2"]}]
        self.write(document)
        self.assertIn("C1: UNSOURCED fits_window", self.stop("The break is 15 minutes, so it fits."))
        self.assertIsNone(self.stop("I assumed a 15-minute break so it fits by 12:30; can you confirm?",
                                    session="s2"))


if __name__ == "__main__":
    unittest.main()
