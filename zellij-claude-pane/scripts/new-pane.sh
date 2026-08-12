#!/usr/bin/env bash
# Create a new zellij pane and start Claude Code in it.
# Usage: new-pane.sh [direction] [cwd] [initial-prompt]
#   direction:      right | down | left | up (default: right; left/up
#                   fall back to right — zellij only supports right/down)
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
#   ZCP_READY_MARK     prompt glyph to poll for (default: ❯)
#   ZCP_READY_TIMEOUT  max seconds to wait for Claude startup (default: 30)
#
# Full interface and contract: see SKILL.md.

set -euo pipefail

case "${1:-}" in
    --help|-h)
        awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
        exit 0
        ;;
esac

# ── helpers ────────────────────────────────────────────────────────────

# Get the tab_id of the currently focused pane.
# Uses ZELLIJ_PANE_ID env var (provided by zellij) for reliable identification.
get_current_tab_id() {
    local tab_id
    local pane_id="${ZELLIJ_PANE_ID:-}"

    if [ -n "$pane_id" ]; then
        # Use ZELLIJ_PANE_ID for reliable identification
        tab_id=$(zellij action list-panes --json 2>/dev/null | \
                 jq -r --argjson pid "$pane_id" '.[] | select(.id == $pid) | .tab_id' 2>/dev/null)
    else
        # Fallback: use first focused pane (may be inaccurate with multiple clients)
        tab_id=$(zellij action list-panes --json 2>/dev/null | \
                 jq -r 'map(select(.is_focused == true)) | .[0].tab_id' 2>/dev/null)
    fi

    echo "$tab_id"
}

# Validate and normalize a pane ID from zellij's stdout.
# Accepts: terminal_42, plugin_7. Rejects: mixed stderr, empty, junk.
normalize_pane_id() {
    local raw="$1"
    local id
    # Extract the last line that looks like a valid pane ID.
    id=$(echo "$raw" | grep -oE '\b(terminal|plugin)_[0-9]+\b' | tail -1)
    if [ -z "$id" ]; then
        # Fallback: try the last non-empty line as a numeric id.
        id=$(echo "$raw" | grep -oE '\b[0-9]+\b' | tail -1)
        [ -n "$id" ] && echo "$id" || return 1
    fi
    echo "$id"
}

pane_is_alive() {
    local id="$1"
    local attempts="${2:-3}"
    local tmpfile="/tmp/zellij-pane-verify-${id}-${SCRIPT_PID}.txt"
    local i=0 size=0
    while [ "$i" -lt "$attempts" ]; do
        rm -f "$tmpfile"
        if zellij action dump-screen --pane-id "$id" --path "$tmpfile" 2>/dev/null; then
            size=$(wc -c < "$tmpfile" 2>/dev/null || echo 0)
            if [ "$size" -gt 10 ]; then
                rm -f "$tmpfile"
                return 0
            fi
        fi
        sleep 0.3
        i=$((i + 1))
    done
    rm -f "$tmpfile"
    return 1
}

wait_for_claude_ready() {
    local id="$1"
    local timeout_sec="${2:-$READY_TIMEOUT}"
    local tmpfile="/tmp/zellij-claude-ready-${id}-${SCRIPT_PID}.txt"
    local elapsed=0
    while [ "$elapsed" -lt "$timeout_sec" ]; do
        rm -f "$tmpfile"
        zellij action dump-screen --pane-id "$id" --path "$tmpfile" 2>/dev/null || true
        if grep -qi 'command not found\|not found\|no such file' "$tmpfile" 2>/dev/null; then
            rm -f "$tmpfile"
            return 2
        fi
        if grep -qF "$READY_MARK" "$tmpfile" 2>/dev/null; then
            rm -f "$tmpfile"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    rm -f "$tmpfile"
    return 1
}

# ── config & args ───────────────────────────────────────────────────────

DIRECTION="${1:-right}"
CWD="${2:-$(pwd)}"
INITIAL_PROMPT="${3:-${ZCP_INITIAL_PROMPT:-}}"
CLAUDE_CMD="${ZCP_CLAUDE_CMD:-claude}"
CLAUDE_ENV="${ZCP_CLAUDE_ENV:-}"
FLOATING="${ZCP_FLOATING:-0}"
READY_MARK="${ZCP_READY_MARK:-❯}"
READY_TIMEOUT="${ZCP_READY_TIMEOUT:-30}"
SCRIPT_PID="$$"

# ── preflight ──────────────────────────────────────────────────────────

if ! zellij action list-panes --json &>/dev/null; then
    echo "Error: not in a zellij session" >&2
    exit 1
fi

# Validate direction.
case "$DIRECTION" in
    right|down) ;;
    left|up)    DIRECTION="right" ;;
    *)          echo "Error: invalid direction '$1' — use right, down, left, or up" >&2; exit 1 ;;
esac

# Resolve and validate working directory.
if [ ! -d "$CWD" ]; then
    echo "Error: directory '$CWD' does not exist" >&2
    exit 1
fi
CWD_ABS="$(cd "$CWD" 2>/dev/null && pwd)" || { echo "Error: cannot access '$CWD'" >&2; exit 1; }

# Get current tab ID to ensure pane is created in the same tab.
CURRENT_TAB_ID=$(get_current_tab_id)
if [ -z "$CURRENT_TAB_ID" ]; then
    echo "Error: could not determine current tab ID" >&2
    exit 1
fi

# Build pane label (handle / and trailing-slash edge cases).
dir_basename="$(basename "$CWD_ABS")"
if [ -z "$dir_basename" ] || [ "$CWD_ABS" = "/" ]; then
    dir_basename="root"
fi
PANE_LABEL="claude: ${dir_basename}"

# Build the full command line to type into the new pane.
if [ -n "$CLAUDE_ENV" ]; then
    FULL_CMD="${CLAUDE_ENV} ${CLAUDE_CMD}"
else
    FULL_CMD="$CLAUDE_CMD"
fi

if [ -n "$INITIAL_PROMPT" ] && ! command -v python3 &>/dev/null; then
    echo "Error: python3 is required to relay the initial prompt" >&2
    exit 1
fi

# ── create the pane (tiled first, floating fallback) ───────────────────

new_id=""
tiled_id=""

if [ "$FLOATING" != "1" ]; then
    # Attempt 1: tiled pane, starting Claude directly.
    raw=$(zellij action new-pane --direction "$DIRECTION" --tab-id "$CURRENT_TAB_ID" --cwd "$CWD_ABS" -- $FULL_CMD 2>/dev/null) || true
    tiled_id=$(normalize_pane_id "$raw")
    sleep 0.8

    if [ -n "$tiled_id" ] && pane_is_alive "$tiled_id"; then
        new_id="$tiled_id"
    else
        echo "Warning: tiled pane ${tiled_id:-<none>} is a ghost (layout may be full), retrying with --floating..." >&2
        # Close the ghost pane so it doesn't linger.
        if [ -n "$tiled_id" ]; then
            zellij action close-pane --pane-id "$tiled_id" 2>/dev/null || true
        fi
    fi
fi

if [ -z "$new_id" ]; then
    # Attempt 2: floating pane, starting Claude directly.
    raw=$(zellij action new-pane --floating --tab-id "$CURRENT_TAB_ID" --cwd "$CWD_ABS" -- $FULL_CMD 2>/dev/null) || true
    new_id=$(normalize_pane_id "$raw")

    if [ -z "$new_id" ] || ! pane_is_alive "$new_id"; then
        echo "Error: floating pane ${new_id:-<none>} is also unreachable" >&2
        exit 1
    fi
fi

# ── name the pane ──────────────────────────────────────────────────────

# Name the pane (zellij-level, does not interfere with the TUI).
zellij action rename-pane --pane-id "$new_id" "$PANE_LABEL"

echo "$new_id"

# ── optional initial prompt (best-effort) ──────────────────────────────

if [ -n "$INITIAL_PROMPT" ]; then
    ready_rc=0
    wait_for_claude_ready "$new_id" || ready_rc=$?

    case "$ready_rc" in
        0)
            echo "Claude Code ready in pane $new_id."
            ;;
        2)
            echo "Error: Claude command '$FULL_CMD' not found in pane $new_id." >&2
            echo "The prompt was NOT sent — it would be executed as shell commands." >&2
            echo "Install Claude Code in the new pane or set ZCP_CLAUDE_CMD." >&2
            exit 1
            ;;
        *)
            echo "Warning: Claude Code did not show prompt within ${READY_TIMEOUT}s, sending anyway..." >&2
            ;;
    esac

    prompt_file="/tmp/zellij-claude-init-${new_id}-${SCRIPT_PID}.md"
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
r = subprocess.run(["zellij", "action", "write-chars", "--pane-id", pane, content])
if r.returncode != 0:
    sys.exit(r.returncode)
time.sleep(0.3)
subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Enter"])
PYEOF
        py_rc=$?
        echo "Sent pointer to $prompt_file (prompt was ${prompt_len} chars)."
    else
        # Short prompt: relay directly via write-chars.
        printf '%s' "$INITIAL_PROMPT" > "$prompt_file"
        python3 - "$new_id" "$prompt_file" <<'PYEOF'
import subprocess, sys, time, os
pane = sys.argv[1]
path = sys.argv[2]
with open(path, "r") as f:
    content = f.read()
if not content.strip():
    sys.exit(0)
subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Ctrl u"])
time.sleep(0.1)
r = subprocess.run(["zellij", "action", "write-chars", "--pane-id", pane, content])
if r.returncode != 0:
    sys.exit(r.returncode)
time.sleep(0.3)
subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Enter"])
PYEOF
        py_rc=$?
        rm -f "$prompt_file"
        if [ "$py_rc" -ne 0 ]; then
            echo "Warning: python relay exited with code $py_rc (prompt may not have been sent)" >&2
        else
            echo "Sent initial prompt to pane $new_id (best-effort)."
        fi
    fi
fi
