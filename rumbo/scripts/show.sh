#!/bin/sh
# UserPromptSubmit hook: print the project's decision record summary, or the planning nudge.
exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/record.py" show --record "${CLAUDE_PROJECT_DIR}/.rumbo/record.json"
