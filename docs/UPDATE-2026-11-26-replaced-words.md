# November 26 Claude adapter 0.3.22: a value in replaced words is not the agent's assumption

This builds on [Claude adapter 0.3.21](UPDATE-2026-11-26-write-hold.md). It changes what the hooks and `check` say about one kind of unsourced value; what they check is unchanged.

## Distribution identities

- The Claude adapter is **0.3.22**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

A check's values must come from the quotes of the items in its `refs`, and a replaced item's quote never counts. That is right when a decision drops an option: its values no longer apply, and `dropped_by` retires a check about it. It is wrong when a decision only chooses an option the record already holds.

In a live 0.3.21 session of `02-launch-full`, the user said "I want to do both marketing options". Haiku recorded that as a commitment that replaced the two items quoting the $650 newsletter rate and the $300 ads. From then on, every hook called the user's own prices unsourced:

- `check` printed `C3: UNSOURCED ... amounts 650, amounts 300 not in the user's quoted words`.
- The write hold showed `ASSUMPTION C3: amounts 650, amounts 300 not in the user's quoted words -> ask the user, or tell them plainly it is your assumption`.

That session's plan reported a total of $1,830, "$630 over". It added haiku's own guessed event costs to the user's committed $1,130 and missed the grader for the committed total.

In the saved runs on 0.3.15 to 0.3.21, 9 of the 93 live checks with unsourced values had values that only replaced items' words gave, in 7 sessions. One was this choice; the others were mostly options the user had dropped, such as Dr. Okafor's terms.

## What changed

- **A `SOURCE` line.** Before a write and at each prompt, an unsourced value that the quote of a replaced item would source gets its own line, and no `ASSUMPTION` line. That replaced item must be in the check's `refs`, or have been replaced by an item in them; without `refs`, any replaced item counts, but never a `done` or `rejected` one. For example: `SOURCE C3: amounts 650, amounts 300 are only in the words of I2 and I7, which I10 replaced -> if the user kept these values, they are not your assumption: source them from an item in this check's refs that is not replaced (take I2 and I7 out of I10's replaces, or quote the user's words that keep them); if the user dropped them, update the check without them, or set its dropped_by`. The agent's own values in the same check keep their `ASSUMPTION` line, and a failing check keeps its `CONFLICT` line.
- **`check` and the Stop gate** name the same words at the end of the check's line, `(only in the words of I2 and I7, which I10 replaced: ...)`, or after `; ` in a failing check's `(also unsourced: ...)`.
- **The values stay unsourced.** Only the agent knows whether a replacement chose an option or dropped it. So nothing passes that did not before, and `dropped_by` works as it did.
- **Skill.** "Sourced values" now says to record a choice among recorded options as its own item. That item replaces nothing whose values the choice keeps. An item is replaced only when the user's words change or drop it. The skill also says what a `SOURCE` line asks.
- **Eval tooling.** `scripts/replay_stop_blocks.py` reads the new form of these lines.

## Evidence

`rumbo/tests/test_replaced_sources.py` covers the new lines:

- a choice that replaced the items quoting its prices;
- a check that cites only the choice;
- the agent's own values beside the user's;
- a failing check;
- no line once the values have a live source;
- no line for words the check never cited, or for a rejected option;
- missing `refs`;
- a dropped check;
- `check` output, the write hold, and the Stop block.

`rumbo/tests/test_check_dropped.py` checks the new note on a dropped option's date, and `tests/test_replay_stop_blocks.py` checks that the replay still rebuilds lines that carry it.

**Live.** On this version, haiku ran `02-launch-full` six times and `08-dropped-option` three times, and sonnet ran `02-launch-full` once, graded by the same sonnet judge as before. Three more haiku sessions of `02-launch-full` ran on 0.3.21 alongside the second three, to compare like with like.

- **No `SOURCE` line appeared.** No session had a check whose values only replaced items' words gave. One haiku session recorded "I want to do both marketing options" as a commitment that replaced an item, as in the 0.3.21 session above, but it kept no budget check. So the line is shown live only where the tests show it.

| | Haiku, `02-launch-full` | committed total | Haiku, `08-dropped-option` | Sonnet, `02-launch-full` |
| --- | --- | --- | --- | --- |
| 0.3.22, first three | 13 of 18 | 0 of 3 | 11 of 12 | 6 of 6 |
| 0.3.22, second three | 17 of 18 | 2 of 3 | - | - |
| 0.3.21, beside the second three | 15 of 18 | 2 of 3 | - | - |

- **The committed total.** Every haiku session that missed it, on either version, added its own estimate of event costs ($460 to $650) to the user's $1,130 and called the plan over budget. Two of them, one on each version, also proposed dropping the newsletter the user had chosen. The second three show no difference between the versions, so the first three's 0 of 3 is how much haiku varies here, not the skill's new text. Haiku had 3 of 5 on 0.3.21 before, and 2 of 3 on 0.3.18.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.21 merge on main. There is no data migration.
