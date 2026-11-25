# November 25 Claude adapter 0.3.17: an assumption already told needs only a status line

This builds on [Claude adapter 0.3.16](UPDATE-2026-11-25-time-ranges.md). It changes how the Stop gate reads a later reply about assumed values; nothing else the hooks check changes.

## Distribution identities

- The Claude adapter is **0.3.17**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The gap

The Stop gate passes a reply that tells the user which values are the agent's own assumptions, and it reads each reply on its own. A reply passes only when it names every assumed value of a check again, at every turn.

In long sessions the agent lays out a draft once, with every block of the agenda, and later turns are about other things. Their replies keep the assumption visible with one line, as the skill asks:

- "**Still my assumptions, so please confirm or correct them:** the 9:00 to 12:30 times and the block lengths in the schedule" (sonnet, turn 2)
- "**Agenda times:** the 9:00–12:30 schedule and every segment length are my suggestions. You haven't confirmed them yet." (opus, turn 4)

Neither names the block lengths, so the gate blocked both. Each block is one of the three a session gets, and the agent then repeated the agenda to the user.

## What changed

When a reply states every assumed value of a check, the gate remembers those values for the session. What was told for a check also counts for a check that replaces it, since agents often replace a check with one that has the same values and new refs.

At a later stop, each assumed value of a check must be named in the reply or have been told. Then the check is stated when the reply names one of its values as an assumption (or asks about it). It is also stated by a line that itself calls the check's budget, schedule or dates an assumption ("my catering and handout figures from the budget are still my estimates").

A value the user has not been told yet still needs the full statement: a new block in the agenda, say, or a new check that replaces nothing. A conflict is never stated this way; it still needs its values on one line. The memory is kept per `session_id` in a new `.told` marker, beside the block count, and is cleared with it once the record has no problems.

This is still word matching: the status line shows that the reply calls a told check an assumption, not that the user read it.

## Evidence

`rumbo/tests/test_stated_problems.py` covers the reader and the gate:

- A status line passes once the values were told and not before.
- Another session, a new value or a line without a cue still blocks.
- Told values carry to a check that replaces the told one, and a value not told can be named in the reply instead.
- A kind word counts only with a cue on its own line.
- A told assumption does not state a conflict, and nothing is remembered without a session id.

**Replay.** Every Stop block saved from three batches on 0.3.15 (sonnet, haiku and opus, 70 sessions) was replayed. Each check was rebuilt from the values its block named, and the session's earlier replies were read in order to find what had been told. This assumes each check had the same values at those earlier stops.

| | 0.3.15 | 0.3.16 | 0.3.17 |
| --- | --- | --- | --- |
| Blocks whose only problems are assumed values, read as stated | 0 of 14 | 4 of 14 | 13 of 14 |

The one still blocked says "whether launch day is Oct 3", with no cue word or question mark. The five blocks that include a conflict are unchanged.

**Live.** Three 15-turn `01-workshop-full` sessions on sonnet ran on a first version of this change, which keyed told values to the check's own id and needed a value on the line. They had 3 Stop blocks, against 6 in the three sessions of that case on 0.3.15. Two of the three came from those two limits:

- A budget check was replaced by one with the same values. The reply named $2 and $250 and called its figures estimates, and the check's other value, $80, had been told for the check it replaced.
- A reply said "My catering, handout and contingency figures from the budget are still my estimates".

Replayed with the told values each session's gate had saved, both pass on this version. The third block was a new check comparing catering with the $300 line cap. Its reply did not name the $7 a head it assumed, so it still blocks. The other six sessions planned for that run (`02-launch-full` and `08-dropped-option`) did not start, because the account reached its weekly usage limit; the 0.3.18 runs cover those cases. The judge was cut off too, and the 8 gradings it missed were given later with `--regrade --errors-only`: all 18 passed.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.16 merge on main. There is no data migration; a `.told` marker left in the state directory is ignored by earlier versions.
