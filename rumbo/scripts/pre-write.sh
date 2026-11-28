#!/bin/sh
# PreToolUse hook for file writes: show the decision record's open problems and undecided items before the write;
# a write with lines not yet shown is held once (see SPEC.md), later ones get the lines as context.
exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/record.py" pre-write --record "${CLAUDE_PROJECT_DIR}/.rumbo/record.json"
