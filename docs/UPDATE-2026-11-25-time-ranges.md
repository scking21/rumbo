# November 25 Claude adapter 0.3.16: a schedule written as time ranges states its blocks

This builds on [Claude adapter 0.3.15](UPDATE-2026-11-24-assumed-years.md). It changes how the Stop gate reads the reply for an assumed schedule; nothing else the hooks check changes.

## Distribution identities

- The Claude adapter is **0.3.16**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`; its 0.3.8 release notes now say that without naming a Claude version, so they stay true as this adapter moves.

## The gap

The Stop gate lets a reply through when it tells the user which values are the agent's own assumptions. A value counts as told when a line names it and the line, its section or the reply's opening calls it an assumption. Minutes were named only as minutes ("75 minutes", "a 20-minute break"). A schedule is usually written as time ranges, and a range names no minutes.

In a 15-turn `01-workshop-full` session on 0.3.15 (sonnet), the first reply opened with "The start time, end time and every dollar figure in it are my assumptions, not decisions". It laid the draft out as rows such as "9:20–10:35 | Session 1". The gate found none of the block lengths named and blocked. That was one of the three blocks a session gets, and the session had used all three by its third turn.

## What changed

A segment's minutes are also named by a clock-time range that spans them: "9:20–10:35" names 75 and "11:50–12:05" names 15. Each end needs its minutes or a meridiem ("9:00", "9am"), so "30-50 people" stays a number range. On a known clock, with a meridiem on both ends or a 24-hour time, an end earlier than the start is the next day ("6pm–9am" and "18:00–09:00" are 900 minutes). With a meridiem on one end, the other end takes the half that gives the shorter range ("9:00 – 10:15pm" is 75 minutes). With neither, the range is read on a 12-hour clock, which can cross noon or midnight ("12:50–1:05" is 15 minutes). Review of this change found that an earlier version rolled every range over 12 hours, which read "6pm–9am" as 180 minutes. This applies only to assumed values: a conflict is still stated only by its end time and the window's end, or by the minutes over written with a minute unit.

## Evidence

`rumbo/tests/test_stated_problems.py` replays that reply; the test fails on 0.3.15 and passes here. Every Stop block in the saved live sessions whose only problem was an assumed schedule was replayed against both readers, rebuilding each check from the values the block named. There were two, both in that session. 0.3.16 reads the first as stated. The second, at the next turn, stays a block: that reply did not mention the schedule at all, and the gate asks for a one-line status for problems still open at a later turn.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.15 merge on main. There is no data migration.
