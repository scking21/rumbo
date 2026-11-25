# November 25 Claude adapter 0.3.18: a record with only its objective gets one nudge

This builds on [Claude adapter 0.3.17](UPDATE-2026-11-25-told-assumptions.md). It adds one prompt-time line and one Stop-gate nudge for a record that holds nothing but its objective, a line about years to the no-record nudge, two lines to the commitments skill, and three readings to how the Stop gate reads a reply.

## Distribution identities

- The Claude adapter is **0.3.18**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

The Stop gate checks what the record holds: failing checks, assumed values, quotes the user never said. A record with only its objective holds none of these, so every stop passes, however many decisions, dates and amounts the user gives.

In repeated runs of every eval case on 0.3.15 (sonnet three times each, haiku three times each, opus twice each; graded by a sonnet judge; see [the results](EVAL-RESULTS-2026-11-25.md)), 39 sessions started a record. Four of them never added an item, over 3 to 15 turns:

| Session | Items and checks at the end | Failed gradings |
| --- | --- | --- |
| haiku, `01-workshop-full` | 0 and 0 | none |
| haiku, `02-launch-full` | 0 and 0 | 3 of 6: budget total, flyers that do not fit, the insurance condition |
| haiku, `11-rejected-option` | 0 and 0 | 1 of 2, as in the two haiku sessions that did keep a record |
| opus, `02-launch-full` | 0 and 0 | 4 of 6: ads first, budget total, dates to hit, flyers that do not fit |

Those two launch sessions account for 7 of the 8 failed launch gradings on haiku and opus. In the opus one, the user asked for both marketing options, and the final plan listed the newsletter as dropped. The agent had decided that on its own, and no record item held the user's words to check it against. The haiku launch session had started its record only because the Stop gate's no-record nudge asked for one; it then recorded nothing. No sonnet session left its record empty.

## What changed

- **Prompt hook.** While the record has no items and no checks, `show` adds one line after the objective: "rumbo: no decisions recorded yet. As the user decides, drafts or rules things out, add items with their exact words, and a check for any schedule, deadline or budget (see the commitments skill)." It also counts planning-looking prompts, as it does when there is no record.
- **Stop gate.** With such a record and no other problem, the gate blocks once per session, once the session has had two planning-looking prompts. It asks the agent to record the user's decisions so far with their exact words and a check for any schedule, deadline or budget, or to tell the user in one line why the work does not need them. It never blocks a stop that comes right after a block, and a new `.empty` marker keeps it to once per session.
- **No-record nudge.** When the prompt names a month and day but no year, the nudge adds: "rumbo: the dates here have no year. Keep them without one in what you write, and ask if the year matters." In `04-deadline-after-event` ("Our fundraiser dinner is on May 9 ..."), every haiku and opus reply put the dates in 2027 and no sonnet reply did. That one-turn case starts no record, so the skill's rule against adding a year was never read; the nudge is the only text the plugin adds to such a session. "May" counts only with its capital, so "may 3 people come?" is not a date.
- **Skill.** "A record with only its objective checks nothing: once you start one, record the decisions the user has already made, and keep adding them." And, before writing: "In what you write, only `commitment` items are decided. Present a `draft`, `preference`, `authorized`, `uncertain` or `deferred` item as open, a proposal or something to confirm. A no to one option rules that option out; it does not choose the others." In `11-rejected-option`, one haiku session's record held the community center as `uncertain`, and its plan still listed it as decided; the skill had not said that the status decides how an item is written.
- **Reading the reply.** Of the five saved blocks that included a conflict, one came from a record that was out of date with the reply. The other four replies named their conflicts, and three of them stated every problem in a way the gate did not read:
  - Two named an assumed price per unit by its total: "my $280 catering estimate is still **$80 over the foundation's $200 cap**", where the record's assumed value was the $7 a head behind the $280. An assumed unit is now also named by its own entry's total (unit × quantity). A total never names an assumed head count, which it does not show. Review of this change found that entries sharing a price ($7 for 40 and $7 for 10) were matched by the price alone, so the $280 also stated the $70; each entry now takes only its own total.
  - One said "The 5-minute overage goes away", and "overage" was not an overrun word. Now it is.

  Replayed with each check rebuilt from its block's values, all three pass on this version and none on 0.3.15. The fourth is a later turn's "blocked on the 12:35 overrun I raised earlier", which names the overrun without the 12:30 close, and it still blocks.

  The one block of only assumed values that 0.3.17 still did not read said "Still open from before: whether to go with the newsletter or social ads, and whether launch day is Oct 3". "Still open", "to be confirmed", "TBC" and "TBD" now mark a value as not decided, as "unconfirmed" does. With them, the replay reads all 14 such blocks as stated.

## Evidence

`rumbo/tests/test_empty_record.py` covers the empty record:

- The prompt hook names the empty record and stops once the record has an item.
- The Stop gate nudges after two planning prompts and not before, only once per session, never right after a block, and per session.
- A record with an item or a check is not nudged, and other problems (an unverified objective quote) are reported first.
- Nothing is counted without a session id.

`rumbo/tests/test_stated_problems.py` covers the new readings with the live replies' wording, including a total that does not name an assumed head count.

`rumbo/tests/test_nudge_year.py` checks that the year line comes with the nudge for dates without a year, and not for a prompt with a year, without a date, with "may" as a verb, or once the nudge has been shown.

**Live.** Every case was run again on this version with the same models, run counts and judge (88 sessions; see [the results](EVAL-RESULTS-2026-11-25.md#0318-against-0315)). Gradings passed rose from 230 to 242 of 248: sonnet 93 of 93 on both versions, haiku 83 to 88 of 93, opus 54 to 61 of 62. Empty records fell from 4 to 1, case-04 replies on haiku and opus that named a year from 5 of 5 to 1 of 5, and the launch case now fails one grading on each of haiku and opus. Stop blocks fell on sonnet (7 to 3) and opus (14 to 5) and rose on haiku (11 to 23), whose fuller records gave the gate more to check. Haiku still writes the remaining venue in `11-rejected-option` as decided, 0 of 3.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.17 merge on main. There is no data migration; an `.empty` marker left in the state directory is ignored by earlier versions.
