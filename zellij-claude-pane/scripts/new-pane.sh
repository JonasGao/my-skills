#!/usr/bin/env bash
# Create a new zellij pane and start Claude Code in it.
# Usage: new-pane.sh [direction] [cwd] [initial-prompt]
#   direction:      left | right | up | down (default: right; only right/down
#                   are supported by zellij; others fall back to right)
#   cwd:            working directory (default: current pane's cwd)
#   initial-prompt: optional task to send to the new Claude session (best-effort)
# Outputs the new pane ID (e.g. terminal_42) on success.
#
# Env overrides:
#   ZCP_CLAUDE_CMD     binary name (default: claude)
#   ZCP_CLAUDE_ENV     extra env vars prepended to the command, e.g.
#                      ZCP_CLAUDE_ENV="ANTHROPIC_MODEL=sonnet DEBUG=1"
#   ZCP_INITIAL_PROMPT fallback initial prompt if not given as 3rd arg
#   ZCP_FLOATING       set to 1 to skip tiled attempt (use when layout
#                      is full and tiled panes turn into ghosts)

set -euo pipefail

DIRECTION="${1:-right}"
CWD="${2:-$(pwd)}"
INITIAL_PROMPT="${3:-${ZCP_INITIAL_PROMPT:-}}"
CLAUDE_CMD="${ZCP_CLAUDE_CMD:-claude}"
CLAUDE_ENV="${ZCP_CLAUDE_ENV:-}"
FLOATING="${ZCP_FLOATING:-0}"

# ── preflight ──────────────────────────────────────────────────────────

if ! zellij action list-panes --json &>/dev/null; then
    echo "Error: not in a zellij session" >&2
    exit 1
fi

# Normalize direction: zellij only supports right/down.
case "$DIRECTION" in
    left|up) DIRECTION="right" ;;
esac

CWD_ABS="$(cd "$CWD" 2>/dev/null && pwd || echo "$CWD")"
PANE_LABEL="claude: $(basename "$CWD_ABS")"

# Build the full command line to type into the new pane.
if [ -n "$CLAUDE_ENV" ]; then
    FULL_CMD="${CLAUDE_ENV} ${CLAUDE_CMD}"
else
    FULL_CMD="$CLAUDE_CMD"
fi

# ── helper: verify a pane actually renders (not a ghost) ───────────────

pane_is_alive() {
    local id="$1"
    local tmpfile="/tmp/zellij-pane-verify-${id}.txt"
    rm -f "$tmpfile"
    zellij action dump-screen --pane-id "$id" --path "$tmpfile" 2>/dev/null || return 1
    # A ghost pane has empty or near-empty screen (just "$" or whitespace).
    # A real pane has a shell prompt or running program with visible content.
    local size
    size=$(wc -c < "$tmpfile" 2>/dev/null || echo 0)
    rm -f "$tmpfile"
    [ "$size" -gt 10 ]   # more than a bare "$" prompt
}

# ── create the pane (tiled first, floating fallback) ───────────────────

new_id=""

if [ "$FLOATING" != "1" ]; then
    # Attempt 1: tiled pane.
    new_id=$(zellij action new-pane --direction "$DIRECTION" --cwd "$CWD" 2>&1)
    sleep 0.8

    if ! pane_is_alive "$new_id"; then
        echo "Warning: tiled pane $new_id is a ghost (layout may be full), retrying with --floating..." >&2
        new_id=""
    fi
fi

if [ -z "$new_id" ]; then
    # Attempt 2: floating pane (always works regardless of layout).
    new_id=$(zellij action new-pane --floating --cwd "$CWD" 2>&1)
    sleep 0.8

    if ! pane_is_alive "$new_id"; then
        echo "Error: floating pane $new_id is also unreachable" >&2
        exit 1
    fi
fi

# ── start Claude Code ──────────────────────────────────────────────────

zellij action write-chars --pane-id "$new_id" "$FULL_CMD"
sleep 0.2
zellij action send-keys --pane-id "$new_id" "Enter"

# Name the pane (zellij-level, does not interfere with the TUI).
zellij action rename-pane --pane-id "$new_id" "$PANE_LABEL"

echo "$new_id"

# ── optional initial prompt (best-effort) ──────────────────────────────

if [ -n "$INITIAL_PROMPT" ]; then
    # Wait for Claude Code to finish loading.
    sleep 5

    prompt_file="/tmp/zellij-claude-init-${new_id}.md"
    prompt_len=$(printf '%s' "$INITIAL_PROMPT" | wc -c)

    if [ "$prompt_len" -gt 2000 ]; then
        # Long prompt: write to file, send a short pointer.
        printf '%s' "$INITIAL_PROMPT" > "$prompt_file"
        pointer="请读取 ${prompt_file} 并完整执行其中的任务。完成后删除该文件。"
        python3 - "$new_id" "$pointer" <<'PYEOF'
import subprocess, sys, time
pane = sys.argv[1]
content = sys.argv[2]
subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Ctrl u"])
time.sleep(0.1)
subprocess.run(["zellij", "action", "write-chars", "--pane-id", pane, content])
time.sleep(0.3)
subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Enter"])
PYEOF
        echo "Sent pointer to $prompt_file (prompt was ${prompt_len} chars)."
    else
        # Short prompt: relay directly via write-chars.
        printf '%s' "$INITIAL_PROMPT" > "$prompt_file"
        python3 - "$new_id" "$prompt_file" <<'PYEOF'
import subprocess, sys, time
pane = sys.argv[1]
path = sys.argv[2]
with open(path, "r") as f:
    content = f.read()
if not content.strip():
    sys.exit(0)
subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Ctrl u"])
time.sleep(0.1)
subprocess.run(["zellij", "action", "write-chars", "--pane-id", pane, content])
time.sleep(0.3)
subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Enter"])
PYEOF
        rm -f "$prompt_file"
        echo "Sent initial prompt to pane $new_id (best-effort)."
    fi
fi
