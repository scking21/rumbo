---
type: llm
focus: trace
weight: 1
---
Grade only what the assistant wrote to the person, across ALL of its text messages in this run (its final message may be a short follow-up after an end-of-turn hook; the main answer can be in an earlier message). Ignore the person's prompt, tool calls, tool results, hook output and file contents.

PASS only if the assistant's reply says lists are mutable and tuples are immutable (or equivalent).
FAIL otherwise.
