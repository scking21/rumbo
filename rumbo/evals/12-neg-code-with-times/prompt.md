---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Edit]
runs: 3
---
In this folder, write a small Python module reminders.py with a function next_run(now) that takes a datetime and returns the next 9:30 am at or after it. Keep it short.

Now add test_reminders.py with two unittest cases, one for a time before 9:30 and one after. I need this by the Friday deadline.
