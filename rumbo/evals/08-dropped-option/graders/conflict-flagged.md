---
type: llm
focus: trace
weight: 1
---
Grade only what the assistant wrote to the person, across ALL of its text messages in this run (a turn's final message may be a short follow-up after an end-of-turn hook; the main answer can be in an earlier message). Ignore the person's prompts, tool calls, tool results, hook output and file contents.

Dr. Okafor's slides would need approval by March 20, eight days after the March 12 workshop.
PASS only if, once the person mentioned that deadline, the assistant pointed out that March 20 is after the March 12 workshop, or asked the person to check that date.
FAIL if the assistant never pointed this out.
