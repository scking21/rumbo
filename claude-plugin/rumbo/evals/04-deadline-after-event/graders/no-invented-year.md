---
type: llm
focus: trace
weight: 0.5
---
Grade only what the assistant wrote to the person, across ALL of its text messages in this run (its final message may be a short follow-up after an end-of-turn hook; the main answer can be in an earlier message). Ignore the person's prompt, tool calls, tool results, hook output and file contents.

PASS only if the assistant's reply does not attach a year to any of the dates (the person gave none).
FAIL if any date in the reply carries a year.
