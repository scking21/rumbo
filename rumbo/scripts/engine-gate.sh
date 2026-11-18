#!/bin/sh
# Stop hook: block (bounded) while the project's engine ledger shows lost acceptance or unclaimed changes.
exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engine_gate.py" --project "${CLAUDE_PROJECT_DIR}"
