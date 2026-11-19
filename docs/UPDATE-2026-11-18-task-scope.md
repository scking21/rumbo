# November 18 task-scope follow-up

This source candidate builds on main `84658a255425e643ed12f0ea6163916a960ed070`. It finishes the opt-in `revision_scope` from [the November 18 update](UPDATE-2026-11-18.md) in three places that still used the contract-wide rule. Default contracts are unchanged. Versions stay as they are: Claude adapter **0.3.9**, Python engine/package **0.3.5**, OpenAI adapters **0.3.6**, Sites candidate **0.1.3**.

## What changed

- **Decision requests** under task scope carry the task's fingerprint like artifacts, evidence and decisions do. The board marks a request historical only when its own task's agreement changed. Before, rewording one task marked every task's requests as "Historical request · prior contract revision".
- **The stale-artifact error** under task scope says the artifact was registered before that task's definition, goal or constraints changed. Before, it named contract revisions, which do not decide staleness under task scope.
- **The owner portal's revision form** states the rule the contract uses. Under task scope it says a revision makes a task's work stale only when that task's definition, or the shared goal or constraints, change.

## Behaviour to know

- The fingerprint compares what was agreed, not the revision history. Rewording a task and then restoring the earlier wording brings the records made under that wording back into force, including an earlier acceptance.
- Code from before `revision_scope` reads a scoped ledger under the contract-wide rule. Work recorded while on that older code has no fingerprint, so after returning to current code it reads as stale under task scope, and records from before the rollback can apply again.

## Verification and rollback

```sh
python3 -m unittest discover -s tests -p 'test_task_scope.py'
python3 -m unittest discover -s tests -p 'test_owner.py'
python3 -m unittest discover -s tests -p 'test_board.py'
```

To roll back, return to `84658a255425e643ed12f0ea6163916a960ed070`. There is no data migration; requests recorded with a fingerprint keep it and older code ignores it.
