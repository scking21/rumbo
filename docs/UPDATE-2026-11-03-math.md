# November 3 time, date and money checks

This source candidate builds on main `2398b05`. It changes how the Claude adapter's checks read the user's numbers and what they compute. It does not change the Python engine, protocol versions or tools. Existing records stay valid, with one exception below.

## Prepared distribution identities

- The Claude adapter **0.3.9** carries the change below in `rumbo/scripts/record.py`, with `rumbo/SPEC.md` and the commitments skill updated to match.
- Python engine/package **0.3.5**, the OpenAI portable and Codex local adapters **0.3.6**, Sites **0.1.3** and both board apps are unchanged.

## Why

Recorded use of the adapter showed two kinds of wrong answer. Agents made a failing check pass by changing the user's numbers, which the source check exists to stop. The opposite also happened: honest records were blocked as `UNSOURCED` because the user wrote a value in a way the reader did not know (PR #10 fixed "March 20th", "9am", "2-hour" and "$1.5k"). A stress corpus of 42 planning statements, written in the style of the eval prompts, found 29 more of both kinds on 0.3.8.

## What changed

- **Durations in words.** "twenty-minute", "two hours", "an hour", "half an hour", "a quarter-hour", "three quarters of an hour", "an hour and a half", "2 and a half hours", "1 hour 15 minutes" and "2h30" now source their minutes. A rate or frequency ("$150 an hour", "fifty dollars an hour", "$150 per half hour", "every 2 hours"), a range ("3-5 hours"), the "an hour" inside "half an hour" and the whole hours of "one hour and a half" source nothing.
- **Amounts in words and scales.** "four hundred fifty dollars", "a thousand", "five thousand", "1.8 million" and "$2.5M" source their values, never the unscaled 1.8 or 2.5. A bare "5m" stays 5. "-€50" and "-£50" no longer source 50.
- **Price per unit.** An `amounts` entry can be `{"unit": 45, "quantity": 12}`. The script multiplies in exact decimals and names the product in a failure (`total 675 exceeds total_cap 600 by 75 (45 x 15 = 675)`). Each factor must be in the user's words. Before, the agent had to multiply itself, and the product it wrote was reported `UNSOURCED`.
- **Windows past midnight.** `fits_window` takes `end_next_day: true` ("9pm to 1am"). It is valid only when the end clock time is before the start, so it confirms what the times say and can never add a day to a same-day window. Clock times past midnight read `01:30 next day`, not `25:30`. This follows the OpenStreetMap `opening_hours` practice of writing the later time explicitly instead of wrapping it silently.
- **Dates.** "Feb 29" without a year is valid, and is compared in a leap year. Both ends of a range ("June 3-5", "12–14 July") are sourced, never the days between. An `MM-DD` failure of more than 182 days names the same-year assumption and says to ask the user for both years, which covers deadlines that cross a new year.
- **Agenda colons.** "9:00: welcome" sources 09:00. Only a colon followed by a digit starts seconds.
- **Cost.** The source check took time quadratic in the length of the quoted text. On 0.3.8, 80 KB of quoted numbers took about 47 s, past the hooks' 10 s timeout, and a hook that times out does not block. It is now linear (under a second for 250 KB).

## Hardened during review

Codex review found 20 ways the wider reading could be wrong, and each is fixed with a regression test. Most let a value the agent chose pass as the user's. A few blocked an honest record. Every fix errs on the strict side: a phrase the reader cannot read whole sources nothing. The rules that came out of it:

- Only the longest duration phrase counts, never a fragment of it. "two-and-a-half-hour" is 150, never 30, and "one hundred and one hours" is never 60.
- Whole hours continued by a fraction or a bare number ("an hour and a third", "1 hour and 20") source nothing alone. A fraction with its own "hour" ("1 hour, and a half-hour break") is a separate duration.
- A rate or frequency states no duration: "$150 an hour", "fifty dollars an hour", "per half hour", "every 2 hours", "twice an hour". A number counts as a price only with a currency sign, a currency word or "a"/"an", so "two half-hour sessions" is two durations.
- "three-quarter hour" and "three quarters of an hour" are 45. "three quarter-hour breaks" is three of 15. "three quarter hour", with no hyphen, sources nothing.
- A fraction followed by another unit ("two hours and a half day") sources nothing. A period after "hour" ends the sentence, so "1 hour. 15 minutes" is two durations.
- For amounts, "fifteen hundred" is 1500. A number that cannot be read whole, continued by a fraction ("one and a half thousand", "1 thousand and a half", checked after any scale word too), after a spelled decimal point ("five million" in "one point five million") or before a plural fraction ("three quarters"), sources nothing.
- A date-range end takes the shared month only when the other end names none of its own: "June 30–2 July" is June 30 and July 2, never June 2 or July 30.
- `end_next_day` is valid only when the end clock time is before the start.

## Drift hooks from recent research

Three changes follow 2026 studies of agent drift. Each is backed by a single preprint, and none has been tried in an installed Claude Code session yet.

- **Re-show after compaction.** A `SessionStart` hook with matcher `compact` prints the record again right after Claude's context is compacted. In "Governance Decay" (arXiv:2606.22528), rules a compaction summary dropped were violated about 30% of the time, and re-injecting them after each compaction brought violations back to 0%. Before, Rumbo's record returned only with the next user prompt, so a compaction in the middle of a long autonomous turn left the agent without it until Stop.
- **Check before writing.** A `PreToolUse` hook on `Write`, `Edit`, `MultiEdit` and `NotebookEdit` adds the record's open problems to Claude's context before a file is written. It never blocks, skips writes to `.rumbo/`, and shows a given set of problems once per session. In "Intent Drift at SME Scale" (arXiv:2609.05975), a check against the stated purpose before each action took action drift from 13 of 15 runs to 0 of 15. Before, Rumbo checked only at Stop, after a plan file was already written.
- **Lead with specific corrections.** `show` now puts open problems first, each with the action to take, before the objective and items. In "Prompting Against Persona Drift" (arXiv:2609.24532), a correction naming the specific problem cut drift by 87%, against 38% for re-showing everything. Open problems now also survive `--max-chars` truncation, which used to cut them off the end.

## The one record that changes meaning

A `fits_window` check whose `end` is earlier than its `start` used to FAIL with a meaningless message ("ends 24:00, 1380 min after 01:00"). It is now `CHECK_BAD_VALUE` with the fix to apply: set `end_next_day: true` if the window really runs past midnight, otherwise correct the times. The Stop gate blocks on an invalid record as it did on the failing check.

## November 6 stacked fixes

These close false alarms and invented values that a November 6 audit of `record.py` found still present on this branch.

- **Afternoon times without am/pm.** A clock time with no am/pm, an hour from 1 to 12 and no leading zero, sources both halves of the day, so "out by 1:00" sources 13:00. Before, a correct afternoon schedule was `UNSOURCED` at 13:00 and FAILed at 01:00. "09:30", "13:30" and "9:30am" keep one reading.
- **Two scale words.** "one thousand and two thousand dollars" no longer sources 3000. A scale word no smaller than one already used ends the number, and the phrase sources nothing.
- **A spaced minus after a number.** "Step 1 - ten people" sources 10, not -10, as "Step 1 - 10 people" already did.
- **"half-an-hour"** sources 30.
- **Retractions.** "before" no longer counts as a pointer to an earlier decision, so "undo the last change before you send it" does not report `EARLIER_APPROVAL`.
- **Planning nudge.** A time joined by a colon to the word before it (`settings.json:12:30`), a slice (`a[1:20]`), an `HH:MM:SS` stamp and `line N:NN` no longer count as planning. "Dinner: 7:30" with a space still does, and "time:10:30" with none no longer does.

Still word matching: "minus 500" and "minus five hundred" source 500, and a new value with no retraction word ("let's go with $800 total") does not reopen an earlier approval.

## Verification, packaging and rollback

Run the Claude-adapter suite from `rumbo/`, the release identity checks from the repository root, and the suite on Python 3.9 in CI.

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

`rumbo/tests/test_math_phrasings.py` holds the new cases. Each honest phrasing passes and each invented value stays `UNSOURCED` or fails. The eval messages for the agenda overrun and the deadline after the event are unchanged. No eval rerun or installed-host verification is claimed. To roll back, return to `2398b05`. There is no data migration.

## November 4 Codex follow-up

The November 3 component versions above describe that update's original scope.
The subsequent OpenAI/Codex adapter candidate is **0.3.7**. It adds an explicit
commitments wrapper and skill using the canonical record checker, with matching
packaged source and regression checks. This does not install Claude hooks in
Codex or establish installed-host verification. The Python engine remains 0.3.5;
the Claude adapter remains 0.3.9.
