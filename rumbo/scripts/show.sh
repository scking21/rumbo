#!/bin/sh
# UserPromptSubmit and SessionStart (after compaction) hook: print the decision record summary, or the planning nudge.
exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/record.py" show --record "${CLAUDE_PROJECT_DIR}/.rumbo/record.json"
