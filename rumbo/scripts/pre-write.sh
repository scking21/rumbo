#!/bin/sh
# PreToolUse hook for file writes: add the decision record's open problems to the agent's context; never blocks.
exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/record.py" pre-write --record "${CLAUDE_PROJECT_DIR}/.rumbo/record.json"
