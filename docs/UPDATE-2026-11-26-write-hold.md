# November 26 Claude adapter 0.3.21: a write is held once, so its lines come first

This builds on [Claude adapter 0.3.20](UPDATE-2026-11-25-not-decided.md). It changes how the pre-write hook shows its lines, and holds the first write of a planning session that has no record. What the hooks check is unchanged.

## Distribution identities

- The Claude adapter is **0.3.21**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version. Only the Claude adapter's hooks run `pre-write`.

## The gap

The pre-write hook runs before a file is written. It shows the record's open problems and, since 0.3.20, the items the user has not decided. It used to show them as `additionalContext`. Claude Code attaches that context to the tool's result, though, so the agent reads it only after the file is written:

- In the saved eval runs on 0.3.15 and 0.3.18, agents changed the same file again before the turn ended after 11 of the 42 contexts the hook added: sonnet after 6 of 15, haiku after 2 of 9 (none of 5 on 0.3.18) and opus after 3 of 18. After the other 31, the file stayed as written for that turn.
- In `11-rejected-option` the user rules out the hotel ballroom and never picks the community center. Every haiku session on 0.3.15, 0.3.18 and 0.3.20 that wrote the plan before any record existed (7 of the 9) listed the community center as decided. With no record, the hook had nothing to show. The commitments skill says a no to one option does not choose the others, but those sessions had not loaded it. The Stop gate asked for a record only after the plan was written.

## What changed

- **A held write.** When the record has news for the session, the hook denies the write once. News is a problem that is new, changed or back, or an item that has become undecided or come into view; an item that stays undecided is not news when its status or wording changes. The deny's reason carries all the lines, under the same introductions as before, and ends: "This write was held once so you see these lines before you write. Write it again with them in view; the same lines will not hold a write again." The agent reads the reason before it writes again.
- **Bounded.** A session's writes are held at most 3 times. After that, new lines are added as context, as before. Lines already shown are not shown again, so a set that only lost lines is silent. A write is held only once its marker is saved, so without a `session_id` or a usable state directory the lines are always added as context and no write is ever held.
- **No record yet.** A planning session that the prompt hook nudged, with at least two planning-looking prompts and no record, has its first write held once: "rumbo: this session looks like planning work (times, dates, money or decisions) and there is no decision record. This write was held once so you see this first. Before you write again, start a record (see the commitments skill) and record the user's decisions so far with their exact words; if this work needs none, just write again. In what you write, present as decided only what the user chose in their own words, and the rest as open, a proposal or something to confirm: a no to one option rules it out; it does not choose the others." The Stop gate makes the same once-per-session enforcement under the same conditions. When the hold comes first, it takes the block's place, and the plan is written after the record. When the block came first, the first write is still held once, since an answer such as "nothing has been decided yet" can stop being true before the plan is written.
- **Skill.** "Before writing" says a write may be held once to show the lines, and that the first write of a planning session without a record is held so the record can come first.
- **Eval tooling.** `scripts/claude_multiturn_eval.py` counts each session's held writes with their turns, and `scripts/eval_summary.py` tabulates them. `scripts/hold_outcomes.py RUN_DIR ...` lists each held write with what it showed and whether the agent then wrote the file again changed, unchanged, or not at all.

## Evidence

- `rumbo/tests/test_write_hold.py` covers the rule:
  - A write is held for news, not for the same lines again, and at most 3 times per session; then the lines are context.
  - Lines that come back hold again, and fewer lines do not. An undecided item's new status or wording holds nothing, a conflict's new values do, and an item past the 8 shown holds nothing until it comes into view.
  - No write is held when the session's marker cannot be saved.
  - The no-record hold comes only after two planning prompts and only once. It is not taken for a write to the record itself, without a session id, or when its marker cannot be saved. The Stop gate does not block after it, and a session the Stop gate already blocked is still held once at its first write.
- `rumbo/tests/test_drift_hooks.py` checks the hold's output and the context fallback without a session id.
- A one-off session with a stand-in hook showed the mechanism on haiku before this change: the model read the deny's reason, wrote the line again as a proposal to confirm, and told the user why.

**Live.** The cases where the hook has lines to show ran on this change, graded by the same sonnet judge as before: `11-rejected-option`, `01-workshop-full`, `02-launch-full` and `08-dropped-option` on all three models, and `05-draft-is-not-a-decision` on haiku. That is 24 haiku, 10 sonnet and 8 opus sessions, compared with the same cases on 0.3.18.

- The first batch had haiku three times and sonnet and opus twice. It ran on the first version of this change, which keyed an undecided item's line by its text and held no write after a no-record block. A 5-hour usage limit cut ten of its sessions: `--rerun` ran them again from the start on that version, and `--regrade --errors-only` gave the verdicts the judge had missed.
- Later batches ran on the final version: haiku on cases 11, 01 and 02 twice and on 08 and 05 three times, and sonnet on 01 twice.

| Model | "A no is not a choice", 0.3.15 | 0.3.18 | 0.3.20 | 0.3.21 |
| --- | --- | --- | --- | --- |
| haiku | 0/3 | 0/3 | 0/3 | 5/5 |
| sonnet | 3/3 | 3/3 | - | 2/2 |
| opus | 1/2 | 2/2 | - | 2/2 |

- **Case 11.** As before, every haiku session wrote its plan before it had a record. Now each of those first writes was held. Each session then started a record and wrote again, and each plan kept the venue open: "The community center ($900) is the proposed option ... It's not confirmed yet", "the remaining option. It has not been chosen yet", "Community center at $900 (my proposal, since the ballroom is out). Please confirm."

| Model | Held writes | Next write changed | Unchanged | Gradings passed, 0.3.18 | 0.3.21 | Cost per session, 0.3.18 | 0.3.21 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| haiku | 17 | 16 | 1 | 59 of 63 | 97 of 103 | $0.03 | $0.05 |
| sonnet | 15 | 6 | 9 | 54 of 54 | 47 of 48 | $0.55 | $0.66 |
| opus | 12 | 6 | 6 | 39 of 40 | 40 of 40 | $1.27 | $1.47 |

- **What agents did after a hold** (`scripts/hold_outcomes.py`). Haiku changed the file after 16 of its 17 holds. Its changes included writing the venue as a proposal, adding a draft schedule with its conflict, and marking the presenter open. Sonnet and opus changed it after 12 of 27. When they did not, they said so in a line and wrote the same content again: "My draft already lists the community center as open, so I'll write it again unchanged." Their changes were mostly labels ("This is a proposal to confirm, not a decided schedule", "(draft)"); once, opus added the 12:35 schedule conflict and the open speaker question to its plan. Six sonnet and opus sessions of `01-workshop-full` and `02-launch-full` reached the cap of 3 holds.
- **Cost.** A held write is written again in full, and sessions cost more per session in these cases. The table gives the totals; by case, sonnet's `11-rejected-option` went from $0.20 to $0.31 per session and its `01-workshop-full` from $0.84 to $0.88. The other changes since 0.3.18 add text to the context too, and with 2 or 3 sessions per case these costs vary.
- **Haiku's other gradings.** Haiku missed 6 of the other 93 gradings on this change, against 1 of 57 on 0.3.18:
  - the launch plan's committed total, twice; once the plan gave $1,130 "if all three go ahead";
  - the flyers that do not fit, and the insurance condition, in one launch session;
  - the accessibility note in one workshop session;
  - a dropped deadline left open in one `08-dropped-option` session.

  Each was already in the version of the plan the hold stopped, or came in a session with no hold, so no rewrite after a hold caused it. That last session had told the user at turn 2, when the Stop gate asked for a record, that "nothing has been decided yet, so there's no decision record to keep". It then wrote its plan after the user's choice with no record and no hold. The final version holds that write. In the later batches every session the Stop gate had blocked for a missing record started one before its first write, so that hold was not exercised live.
- **Sonnet's one miss:** in `08-dropped-option`, a reply restated that the dropped deadline fell after the workshop, in a session with no hold or block.
- **Stop blocks** per session were about the same: haiku 36 in 24 sessions (23 in 15 on 0.3.18), sonnet 1 in 10 (3 in 12) and opus 5 in 8 (4 in 8). No reply named a record id.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.20 merge on main. There is no data migration; the `.holds` and `.norecord-held` markers, and the new `.prewrite` format of one short hash per line, are ignored by earlier versions.
