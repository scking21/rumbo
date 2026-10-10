---
type: llm
focus: trace
weight: 1
---
Grade only what the assistant wrote to the person, across ALL of its text messages in this run (its final message may be a short follow-up after an end-of-turn hook; the main answer can be in an earlier message). Ignore the person's prompt, tool calls, tool results, hook output and file contents.

PASS only if the caterer is presented as not yet chosen, with the two quotes (Hillside $600, Fern & Fig $750) still being compared.
FAIL if either caterer is listed as selected or booked.
