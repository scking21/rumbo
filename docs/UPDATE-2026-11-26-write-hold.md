# November 26 Claude adapter 0.3.21: a write is held once, so its lines come first

This builds on [Claude adapter 0.3.20](UPDATE-2026-11-25-not-decided.md). It changes how the pre-write hook shows its lines, and moves the one no-record enforcement of a session from the Stop gate to the first write when that comes first. What the hooks check is unchanged.

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

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.20 merge on main. There is no data migration; the `.holds` and `.norecord-held` markers, and the new `.prewrite` format of one short hash per line, are ignored by earlier versions.
