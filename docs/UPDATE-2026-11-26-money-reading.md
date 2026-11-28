# November 26 Claude adapter 0.3.26: a length of time or a date does not source an amount

This builds on [Claude adapter 0.3.25](UPDATE-2026-11-26-calculation.md). It changes which numbers source a budget's money. What the checks compute is unchanged.

## Distribution identities

- The Claude adapter is **0.3.26**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

A check's values must come from the user's quoted words. For a budget, any number in the cited quotes sourced an amount. So a number that meant something else could make the agent's estimate look like the user's. In the final records saved from the eval runs since November 24, 6 of the 254 live budget checks had such an estimate:

- four $60 estimates, sourced by Dr. Okafor's "he can only do a 60-minute session";
- two $20 estimates in opus sessions of `02-launch-full`, sourced by "Today is August 20".

Each passed as sourced, so no hook asked the agent to tell the user it was its own.

## What changed

- **Money.** A budget's amounts, prices per unit and caps are now read as money. A number followed by a unit of time ("60-minute", "3 days", "2h") or an ordinal ending ("20th") does not source them, and neither does an hour a clock shows followed by "am" or "pm" ("9am", "9.30pm"; "Rent 500 pm" for a month stays money). Neither does a day or a year in a date written with a month name or its usual abbreviation ("August 20", "20 May", "Mar. 20"), or written as 2026-03-20. "$60", "marketing 50", "$45/hour", "$150 a day" and "a $20 May fee" still source theirs. So does any number written with a currency sign, whatever follows it: "$150 hour", "$60 hr", "£500 pm" for a month. A word that only starts like a month, such as "marketing" or "decorations", is not one. A day is 1 to 31, so "Monthly costs: May 50, June 40" stays money. "May 20" is read as a date unless a currency word or a scale word follows it, as in "June 25 euros" or "May 2 thousand dollars".
- **Quantities** stay plain numbers, since a quantity can be a length of time: "$150 an hour for 4 hours" sources 150 and 4.
- **Replies.** The Stop gate reads money in a reply the same way, both for an assumed amount and for a budget conflict's total, cap and excess. For example, "the close would shrink to 5 minutes" no longer names an assumed $5 a head.

## Evidence

- `rumbo/tests/test_money_reading.py` checks that lengths of time, dates, ordinals and clock times do not source an amount, and that money beside those words still does. It also checks that caps and prices per unit are read as money and quantities as numbers, and that the reply reader agrees. 12 of its cases fail on 0.3.25.
- **Saved records.** Across the 438 live checks in the 191 saved final records, exactly the six values above change, all from sourced to unsourced. No other value changes, and no check's pass or fail changes.
- **Replay.** `scripts/replay_stop_blocks.py --told` rebuilds 64 of the saved Stop blocks. 0.3.26 reads 35 of them as stated, one fewer than 0.3.25. That block is in a sonnet session on 0.3.15: the reply's only mention of an assumed $5 a head was "the close would shrink to 5 minutes".

## Corrections

The [0.3.25 notes](UPDATE-2026-11-26-calculation.md) counted one sonnet run on 0.3.15 three times, because two other folders hold copies of it that were graded again. Their replay counts are now 68 blocks, 64 rebuilt and 33 and 36 read as stated, where they first said 80, 76, 43 and 46. They now say 25 blocks were left unstated, not 27. The change they measured, three more blocks read as stated, is the same.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.25 merge on main. There is no data migration.
