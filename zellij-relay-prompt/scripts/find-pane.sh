#!/usr/bin/env bash
# List other coding-agent panes in this zellij session.
# Usage: find-pane.sh [self-pane-id]   (default: $ZELLIJ_PANE_ID)
# Output, one per line: <pane-id>\t<title>\t<cwd>
# Empty output means no other coding-agent panes were found.
#
# A "coding agent" is any interactive AI coding TUI: Claude Code, Codex,
# OpenCode, Aider, Gemini CLI, etc. Discovery matches pane_command against a
# list of known agent command names - NOT the pane title, which agents set to
# task text or a spinner and is therefore unreliable.
#
# Override the matched commands via $CODE_AGENT_RE (a regex), e.g.:
#   CODE_AGENT_RE="claude|codex|myagent" bash scripts/find-pane.sh

AGENT_RE="${CODE_AGENT_RE:-claude|codex|opencode|aider|gemini}"
self="${1:-${ZELLIJ_PANE_ID:-}}"
zellij action list-panes --json 2>/dev/null | jq -r --arg self "$self" --arg re "$AGENT_RE" '
    .[]
    | select(.is_plugin == false)
    | select((.pane_command // "") | test($re))
    | select(.id != ($self | sub("^(terminal_|plugin_)"; "") | tonumber? // -1))
    | "\(.id)\t\(.title)\t\(.pane_cwd // "-")"
' 2>/dev/null
