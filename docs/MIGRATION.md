# Migration from 0.2.2

The new engine is additive. Legacy `record.json` remains a planning aid and is not imported as an approved contract. The owner must review a new contract explicitly; old quotes or statuses never become human approval by conversion. New state uses `.rumbo/state.sqlite3`.

The Claude adapter keeps its hooks and commands. It now treats a missing or unreadable transcript as an explicit provenance problem under the existing maximum three blocks per session. This is bounded fail-closed checking, not an infinite enforcement barrier. Missing session identity retains the legacy `stop_hook_active` fallback. A restored readable transcript allows the gate to recover/reset.

Numeric/time/date source checks always include the objective and only active referenced items. Done/rejected items and every item replaced by another item are excluded. Missing or null `refs` retains a backward-compatible active-only fallback; explicit `[]` means objective-only. Unknown referenced IDs continue to fail validation. Rejected or replaced statements can no longer lend unrelated numbers to make checks pass.

Some old records now report UNSOURCED until their refs are corrected. The unchanged historical workshop fixture deliberately preserves incomplete refs; updated test expectations make this stricter behavior visible. The documented SPEC example has explicit correct refs.

Claude lifecycle hooks remain in the source release only. OpenAI local/public plugin archives use their own manifests and exclude those hooks; they do not claim a native universal Stop gate. Source and protocol formats are local 0.3.0; no automatic network or schema migration is performed.
