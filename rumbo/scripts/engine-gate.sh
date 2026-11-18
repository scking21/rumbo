#!/bin/sh
# Stop hook: report, once per problem, when work the owner accepted is no longer accepted.
exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engine_gate.py" --project "${CLAUDE_PROJECT_DIR}"
