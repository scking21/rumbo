# November 26 Claude adapter 0.3.25: a value the reply calls its calculation is stated

This builds on [Claude adapter 0.3.24](UPDATE-2026-11-26-number-overflow.md). It adds words the Stop gate reads as calling a value the agent's own; what the hooks check is unchanged.

## Distribution identities

- The Claude adapter is **0.3.25**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

A value the agent works out from the user's words is not in their words either, so its check reports it as unsourced: a deadline 10 days before the user's event, or the minutes between their arrival time and their first session. The Stop gate passes such a value once the reply names it and calls it the agent's own, for example an assumption, an estimate, a guess or a proposal. A calculation was not one of those words.

So two live sessions were blocked for telling the user just that:

- Opus on 0.3.21, in `02-launch-full`: "By my calculation, 10 days before October 3 is **September 23**, and that's the latest the proof can arrive."
- Haiku on 0.3.19, in `01-workshop-full`: "The 45-minute arrival window is my calculation from 9:00 to 9:45." The check was a schedule that ran past the close, and the reply stated that conflict too. The next turn got the short repeat block.

## What changed

- **Reader.** "calculate", "calculated", "calculates", "calculating", "calculation" and "calculations" now call a value the agent's own, as "estimate" does. That holds on the value's line, in its section, or in the reply's opening, but not after "you" or "your" and at most two more words ("your calculation"). "calculator" does not count. A later status line works the same way: "Sep 23 as the insurance deadline is still my calculation".
- **Skill.** "Sourced values" says that a value worked out from the user's words is not in their words either, so say it is your calculation. "Stopping" lists the word with the others.

## Evidence

- `rumbo/tests/test_stated_problems.py` checks both live replies and other forms of the word. It checks a status line after the date was told in full, and that "your calculation", "calculator" and a reply with none of these words state nothing. Against 0.3.24, it fails.
- **Replay.** `scripts/replay_stop_blocks.py --told` read the 68 Stop blocks with check problems saved from the eval runs since November 24, counting once a run that was graded again in other folders. It rebuilds 64 of them; the other 4 are repeats whose checks it cannot recover. 0.3.24 reads 33 of the 64 as stated, and 0.3.25 reads 36: the two blocks above and the haiku one's repeat. No block that 0.3.24 read as stated changed. (These notes first gave 80, 76, 43 and 46, counting one sonnet run on 0.3.15 three times.)

## Left as it is

The 25 other blocks that 0.3.25 does not read as stated, not counting repeats, were read by hand. In most of them, the reply does not name the values the block lists, or presents them as the user's. Five replies name them in ways the reader does not take:

- estimates summed in one table row ("Supplies + contingency | $120" for $70 and $50), in two blocks;
- one value named in one reply and the other two in the next, so that no single reply names them all;
- "Confirm the 30- and 10-minute arrival and welcome splits.";
- "Two open items from before are still waiting on you: whether the 9:00–9:30 arrival and 12:20–12:30 wrap-up lengths work".

Reading these would take sums of values, a memory of values told one at a time, or wider words. Each could also let a value pass that was never disclosed, so they wait for more cases.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.24 merge on main. There is no data migration.
