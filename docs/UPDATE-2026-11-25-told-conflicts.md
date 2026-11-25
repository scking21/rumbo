# November 25 Claude adapter 0.3.19: a conflict already told needs only a status line

This builds on [Claude adapter 0.3.18](UPDATE-2026-11-25-empty-record.md). It changes how the Stop gate reads a later reply about a conflict; nothing else the hooks check changes.

## Distribution identities

- The Claude adapter is **0.3.19**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

Since 0.3.17, an assumption a reply has told the user in full needs only a status line at later turns. A conflict did not work that way: every reply had to state it with its full values, either the time the plan reaches and the end it misses, or the minutes over with an overrun word.

In the live 0.3.18 runs ([results](EVAL-RESULTS-2026-11-25.md#0318-against-0315)), haiku kept fuller records than before, and the gate blocked several later replies that did keep an open conflict in view:

- "**Still open:** the 9:45 schedule conflict, the 30- and 10-minute assumptions, and whether to use Dr. Okafor." (turn 11)
- "**Schedule:** The 9:45 start still ends at 12:35. Choose one of the fixes I listed" (turn 13)

Both came after a reply that had stated the 12:35 overrun of the 12:30 close in full. Neither names the 12:30 close, so the gate blocked them as repeats.

## What changed

- **A told conflict.** When a reply states a check's conflict in full, the gate remembers it for the session as the check's failing detail ("09:45 + 170 min ends 12:35, 5 min after 12:30"), in the same `.told` marker as told assumptions. While that same conflict holds, for the check or one it replaces, a later line states it in either of two ways:
  - it names one of the conflict's values (the time reached, the end, the minutes over, a date, the total, the cap or the excess) with an overrun or ordering word or the word "still": "the 9:45 start still ends at 12:35";
  - it names the check's kind (budget, schedule, dates and the like) with an overrun or ordering word: "the 9:45 schedule conflict", "we are still over budget".
  
  A changed conflict, a 12:40 end say, needs its full values again. A line with a value and no such word ("we end at 12:35") does not count, and neither does a line that only says the schedule is still being drafted.
- **Remembered part by part.** A reply's conflict and its assumed values are now each remembered when that reply states them in full, even if it leaves the other out. Before, a reply was remembered only when it stated everything about the check at once.

## Evidence

`rumbo/tests/test_stated_problems.py` covers the rule:

- The status lines above pass once the conflict was told, and not before.
- A changed conflict, another check, or a line without the right word still blocks.
- Each part is remembered on its own.
- At the gate, a session's second stop passes on a status line, another session's does not, and a changed conflict blocks again.

Every saved Stop block was replayed with `scripts/replay_stop_blocks.py --told`:

| Saved runs | Conflict blocks read as stated, 0.3.18 | 0.3.19 |
| --- | --- | --- |
| On 0.3.15 (70 sessions) | 3 of 5 | 4 of 5 |
| On 0.3.18 (88 sessions) | 0 of 7 | 4 of 7 |

The blocks whose problems are all assumed values are unchanged: 15 of 15 and 0 of 5. The five blocks newly read as stated:

- The two haiku status lines above.
- An opus reply that stated "the $650 total is $50 over the $600 budget" in full. Its assumed values had been told at the stop before, which the part-by-part memory now keeps.
- Two opus replies about a budget whose record was out of date: the check still held an estimate the user's quotes had since replaced. Each reply said the plan was still over budget, with the new totals ("Both quotes go over budget, by different amounts"). The gate no longer blocks those replies. The hook that runs before a file write still lists the check's conflict, once per session while it stays the same, until the agent updates the record.

Four conflict blocks are still not read as stated. In one, no reply had stated the conflict in full. In the other three the conflict now counts as stated. The same block also holds assumed values, told earlier, that the reply did not mention again with a word that calls them assumptions: the $60 handouts, a 45-minute arrival block, and the 30- and 10-minute slots. The replay assumes each check had the same values at the session's earlier stops.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.18 merge on main. There is no data migration; a conflict remembered in a `.told` marker is ignored by earlier versions.
