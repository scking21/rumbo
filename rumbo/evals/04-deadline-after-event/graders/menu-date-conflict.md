---
type: llm
focus: trace
weight: 1
---
Grade only what the assistant wrote to the person, across ALL of its text messages in this run (its final message may be a short follow-up after an end-of-turn hook; the main answer can be in an earlier message). Ignore the person's prompt, tool calls, tool results, hook output and file contents.

The caterer's stated deadline (May 12) falls three days after the dinner (May 9).
PASS only if the reply points out that the May 12 menu deadline is after the May 9 event, or asks the person to check that date.
FAIL if May 12 is listed as a deadline with no comment, or if the reply silently replaces it with a different date.
