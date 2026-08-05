#!/usr/bin/env bash
# Create a new zellij pane and start Claude Code in it.
# Usage: new-pane.sh [direction] [cwd] [initial-prompt]
#   direction:      left | right | up | down (default: right)
#   cwd:            working directory (default: current pane's cwd)
#   initial-prompt: optional task to send to the new Claude session (best-effort)
# Outputs the new pane ID on success.
#
# Env overrides:
#   CLAUDE_CMD           command name (default: claude)
#   CLAUDE_INITIAL_PROMPT fallback initial prompt if not given as 3rd arg

set -euo pipefail

DIRECTION="${1:-right}"
CWD="${2:-$(pwd)}"
INITIAL_PROMPT="${3:-${CLAUDE_INITIAL_PROMPT:-}}"
CLAUDE_CMD="${CLAUDE_CMD:-claude}"

# ── preflight ──────────────────────────────────────────────────────────

if ! zellij action list-panes --json &>/dev/null; then
    echo "Error: not in a zellij session" >&2
    exit 1
fi

for dep in jq comm; do
    if ! command -v "$dep" &>/dev/null; then
        echo "Error: required tool '$dep' not found" >&2
        exit 1
    fi
done

CWD_ABS="$(cd "$CWD" 2>/dev/null && pwd || echo "$CWD")"
PANE_LABEL="claude: $(basename "$CWD_ABS")"

# ── create the pane ────────────────────────────────────────────────────

before=$(zellij action list-panes --json | jq -r '.[].id' | sort)
zellij action new-pane --direction "$DIRECTION" --cwd "$CWD"
sleep 0.5

after=$(zellij action list-panes --json | jq -r '.[].id' | sort)
new_id=$(comm -13 <(echo "$before") <(echo "$after"))

if [ -z "$new_id" ]; then
    echo "Error: could not determine new pane ID" >&2
    exit 1
fi

# ── start Claude Code ──────────────────────────────────────────────────

sleep 0.8   # let the shell finish initializing
zellij action write-chars --pane-id "$new_id" "$CLAUDE_CMD"
sleep 0.2
zellij action send-keys --pane-id "$new_id" "Enter"

# Name the pane (zellij-level, does not interfere with the TUI).
zellij action rename-pane --pane-id "$new_id" "$PANE_LABEL"

echo "$new_id"

# ── optional initial prompt (best-effort) ──────────────────────────────

if [ -n "$INITIAL_PROMPT" ]; then
    # Wait for Claude Code to finish loading.
    sleep 5

    # Write prompt to a temp file so special characters survive verbatim.
    prompt_file="/tmp/zellij-claude-init-${new_id}.md"
    printf '%s' "$INITIAL_PROMPT" > "$prompt_file"

    # Use python to relay the file contents — same approach as
    # zellij-relay-prompt, avoids shell escaping issues.
    python3 - "$new_id" "$prompt_file" <<'PYEOF'
import subprocess, sys, time
pane = sys.argv[1]
path = sys.argv[2]
with open(path, "r") as f:
    content = f.read()
if not content.strip():
    sys.exit(0)
# Clear any text already in the input line.
subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Ctrl u"])
time.sleep(0.1)
subprocess.run(["zellij", "action", "write-chars", "--pane-id", pane, content])
time.sleep(0.3)
subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Enter"])
PYEOF

    rm -f "$prompt_file"
    echo "Sent initial prompt to pane $new_id (best-effort)."
fi
