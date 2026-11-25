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

When a reply states every assumed value of a check, the gate remembers those values for the session. At a later stop, while each assumed value of that check is among the ones told, a line that names any one of them as an assumption (or asks about it) states them all. A value the user has not been told yet needs the full statement again: a new block in the agenda, say. A conflict is never stated this way; it still needs its values on one line. The memory is kept per `session_id` in a new `.told` marker, beside the block count, and is cleared with it once the record has no problems.

This is still word matching: the status line shows that the reply calls one of the told values an assumption, not that the user read it.

## Evidence

`rumbo/tests/test_stated_problems.py` covers the reader and the gate: a status line passes once the values were told and not before; another session, a new value or a line without a cue still blocks; a told assumption does not state a conflict; without a session id nothing is remembered.

Every Stop block saved from three batches on 0.3.15 (sonnet, haiku and opus, 70 sessions) was replayed. Each check was rebuilt from the values its block named, and the session's earlier replies were read in order to find what had been told. This assumes each check had the same values at those earlier stops.

| | 0.3.15 | 0.3.16 | 0.3.17 |
| --- | --- | --- | --- |
| Blocks whose only problems are assumed values, read as stated | 0 of 14 | 4 of 14 | 12 of 14 |

The two still blocked have replies that do not name the values: "whether launch day is Oct 3" has no cue word or question mark, and "the budget split are still my own suggestions" names no amount. The five blocks that include a conflict are unchanged.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest tests.test_release_identity
```

To roll back, return to the 0.3.16 merge on main. There is no data migration; a `.told` marker left in the state directory is ignored by earlier versions.
