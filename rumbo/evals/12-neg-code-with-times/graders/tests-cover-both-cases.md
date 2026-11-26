---
type: llm
focus: {source: file, path: test_reminders.py}
weight: 1
---
Grade the Python test file below.

PASS only if it is a unittest test file that calls next_run with a time before 9:30 and with a time after 9:30, and checks the result of each.
FAIL if either case is missing or the file does not use unittest.
