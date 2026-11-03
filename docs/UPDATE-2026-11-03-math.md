# November 3 time, date and money checks

This source candidate builds on main `2398b05`. It changes how the Claude adapter's checks read the user's numbers and what they compute. It does not change the Python engine, protocol versions or tools. Existing records stay valid, with one exception below.

## Prepared distribution identities

- The Claude adapter **0.3.9** carries the change below in `rumbo/scripts/record.py`, with `rumbo/SPEC.md` and the commitments skill updated to match.
- Python engine/package **0.3.5**, the OpenAI portable and Codex local adapters **0.3.6**, Sites **0.1.3** and both board apps are unchanged.

## Why

Recorded use of the adapter showed two kinds of wrong answer. Agents made a failing check pass by changing the user's numbers, which the source check exists to stop. The opposite also happened: honest records were blocked as `UNSOURCED` because the user wrote a value in a way the reader did not know (PR #10 fixed "March 20th", "9am", "2-hour" and "$1.5k"). A stress corpus of 42 planning statements, written in the style of the eval prompts, found 29 more of both kinds on 0.3.8.

## What changed

- **Durations in words.** "twenty-minute", "two hours", "an hour", "half an hour", "a quarter-hour", "three quarters of an hour", "an hour and a half", "2 and a half hours", "1 hour 15 minutes" and "2h30" now source their minutes. A rate ("$150 an hour"), a range ("3-5 hours") and the "an hour" inside "half an hour" source nothing.
- **Amounts in words and scales.** "four hundred fifty dollars", "a thousand", "five thousand", "1.8 million" and "$2.5M" source their values, never the unscaled 1.8 or 2.5. A bare "5m" stays 5. "-€50" and "-£50" no longer source 50.
- **Price per unit.** An `amounts` entry can be `{"unit": 45, "quantity": 12}`. The script multiplies in exact decimals and names the product in a failure (`total 675 exceeds total_cap 600 by 75 (45 x 15 = 675)`). Each factor must be in the user's words. Before, the agent had to multiply itself, and the product it wrote was reported `UNSOURCED`.
- **Windows past midnight.** `fits_window` takes `end_next_day: true` ("9pm to 1am"). Clock times past midnight read `01:30 next day`, not `25:30`. This follows the OpenStreetMap `opening_hours` practice of writing the later time explicitly instead of wrapping it silently.
- **Dates.** "Feb 29" without a year is valid, and is compared in a leap year. Both ends of a range ("June 3-5", "12–14 July") are sourced, never the days between. An `MM-DD` failure of more than 182 days names the same-year assumption and says to ask the user for both years, which covers deadlines that cross a new year.
- **Agenda colons.** "9:00: welcome" sources 09:00. Only a colon followed by a digit starts seconds.
- **Cost.** The source check took time quadratic in the length of the quoted text. On 0.3.8, 80 KB of quoted numbers took about 47 s, past the hooks' 10 s timeout, and a hook that times out does not block. It is now linear (under a second for 250 KB).

## The one record that changes meaning

A `fits_window` check whose `end` is earlier than its `start` used to FAIL with a meaningless message ("ends 24:00, 1380 min after 01:00"). It is now `CHECK_BAD_VALUE` with the fix to apply: set `end_next_day: true` if the window really runs past midnight, otherwise correct the times. The Stop gate blocks on an invalid record as it did on the failing check.

## Verification, packaging and rollback

Run the Claude-adapter suite from `rumbo/`, the release identity checks from the repository root, and the suite on Python 3.9 in CI.

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

`rumbo/tests/test_math_phrasings.py` holds the new cases. Each honest phrasing passes and each invented value stays `UNSOURCED` or fails. The eval messages for the agenda overrun and the deadline after the event are unchanged. No eval rerun or installed-host verification is claimed. To roll back, return to `2398b05`. There is no data migration.
