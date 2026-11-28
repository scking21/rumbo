
### Rechecking an accepted task

When the request is to verify an approved artifact while retaining its acceptance, call `rumbo_verify_checks` with its exact task and revisions and `preserve_approval: true` if advertised. Use its checks and observed status for the handoff. Finish any other task that explicitly needs new receipts with `rumbo_run_checks` on that other task. An ambiguous request to “check again” can proceed by verification; ask which evidence should change only if the distinction blocks a requested outcome.

The protection holds check recording on this connection for the observed task, contract revision and artifact revision. It does not follow a restart or a revision change. On resumption, read current state and verify again with preservation if the request still applies. When the person explicitly requests new evidence on a protected target, pass its verification's one-use `record_after_verification` to `rumbo_run_checks` on those same revisions. Their existing instruction is sufficient. After an uncertain recording result, inspect state before considering another receipt. The token identifies a protected observation and grants no authority.
