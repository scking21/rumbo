#!/bin/sh
# Stop hook: block (bounded) while the decision record has unresolved problems.
exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/record.py" stop-gate --record "${CLAUDE_PROJECT_DIR}/.rumbo/record.json"
