---
type: llm
focus: {source: file, path: reminders.py}
weight: 1
---
Grade the Python module below.

PASS only if next_run(now) returns 9:30 on now's date when now is at or before 9:30, and 9:30 on the next day when now is after 9:30, keeping now's timezone if it has one or treating naive datetimes as naive.
FAIL if it returns the wrong day for either case, returns another time, or does not define next_run.
