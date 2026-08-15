#!/usr/bin/env bash
# Create a new zellij pane and start a configured coding agent.
# Usage: new-pane.sh [direction] [cwd] [initial-prompt]
#   direction:      right | down | left | up (default: right; left/up
#                   fall back to right because zellij only supports right/down)
#   cwd:            working directory (default: current pane's cwd)
#   initial-prompt: optional task to relay after the agent shows its ready mark
# Outputs the new pane ID (e.g. terminal_42) on success.
#
# Environment:
#   ZAP_AGENT_CMD       required command that starts the coding agent
#   ZAP_AGENT_ENV       optional environment assignments prepended to the command
#   ZAP_INITIAL_PROMPT  fallback initial prompt if not given as the third argument
#   ZAP_FLOATING        set to 1 to create a floating pane
#   ZAP_READY_MARK      required literal mark to wait for when relaying a prompt
#   ZAP_READY_TIMEOUT   prompt-ready timeout in seconds (default: 30)
#
# Exit status:
#   0  pane created, and the initial prompt was sent when supplied
#   1  START_FAILED: configuration was valid but pane creation or relay failed
#   2  ACTION_REQUIRED: ask the user for the listed configuration, then retry once

set -euo pipefail

case "${1:-}" in
    --help|-h)
        awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "$0"
        exit 0
        ;;
esac

emit_start_failed() {
    printf 'START_FAILED: %s\n' "$*" >&2
    exit 1
}

is_positive_integer() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

get_current_tab_id() {
    local pane_id="${ZELLIJ_PANE_ID:-}"
    local tab_id

    if [ -n "$pane_id" ]; then
        tab_id=$(zellij action list-panes --json 2>/dev/null | \
            jq -r --argjson pid "$pane_id" '[.[] | select(.id == $pid) | .tab_id][0] // empty' 2>/dev/null)
    else
        tab_id=$(zellij action list-panes --json 2>/dev/null | \
            jq -r 'map(select(.is_focused == true)) | .[0].tab_id' 2>/dev/null)
    fi

    printf '%s\n' "$tab_id"
}

normalize_pane_id() {
    local raw="$1"
    local id

    id=$(printf '%s\n' "$raw" | grep -oE '\b(terminal|plugin)_[0-9]+\b' | tail -1)
    if [ -z "$id" ]; then
        id=$(printf '%s\n' "$raw" | grep -oE '\b[0-9]+\b' | tail -1)
        [ -n "$id" ] || return 1
    fi
    printf '%s\n' "$id"
}

wait_for_agent_ready() {
    local pane_id="$1"
    local tmpfile="/tmp/zellij-agent-ready-${pane_id}-${SCRIPT_PID}.txt"
    local elapsed=0

    while [ "$elapsed" -lt "$READY_TIMEOUT" ]; do
        rm -f "$tmpfile"
        zellij action dump-screen --pane-id "$pane_id" --path "$tmpfile" 2>/dev/null || true
        if grep -qF -- "$READY_MARK" "$tmpfile" 2>/dev/null; then
            rm -f "$tmpfile"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    rm -f "$tmpfile"
    return 1
}

print_action_required_and_exit() {
    local requested=0

    if [ -z "$AGENT_CMD" ]; then
        requested=1
    fi
    if [ -n "$INITIAL_PROMPT" ] && [ -z "$READY_MARK" ]; then
        requested=1
    fi
    [ "$requested" -eq 1 ] || return 0

    echo "ACTION_REQUIRED: launch configuration is incomplete." >&2
    echo "Ask the user for the following values, then run this script once more:" >&2
    if [ -z "$AGENT_CMD" ]; then
        echo "- ZAP_AGENT_CMD: the command, including any arguments, that starts their coding agent." >&2
    fi
    if [ -n "$INITIAL_PROMPT" ] && [ -z "$READY_MARK" ]; then
        echo "- ZAP_READY_MARK: a literal screen mark that proves the selected agent is ready for an initial prompt." >&2
    fi
    echo "Do not guess these values or retry again after that second invocation fails." >&2
    exit 2
}

# Arguments and configuration are collected before checking zellij so a missing
# command always yields an actionable diagnostic for the calling agent.
DIRECTION="${1:-right}"
CWD="${2:-$(pwd)}"
INITIAL_PROMPT="${3:-${ZAP_INITIAL_PROMPT:-}}"
AGENT_CMD="${ZAP_AGENT_CMD:-}"
AGENT_ENV="${ZAP_AGENT_ENV:-}"
FLOATING="${ZAP_FLOATING:-0}"
READY_MARK="${ZAP_READY_MARK:-}"
READY_TIMEOUT="${ZAP_READY_TIMEOUT:-30}"
SCRIPT_PID="$$"

print_action_required_and_exit

case "$DIRECTION" in
    right|down) ;;
    left|up) DIRECTION="right" ;;
    *) emit_start_failed "invalid direction '$DIRECTION'; use right, down, left, or up" ;;
esac

case "$FLOATING" in
    0|1) ;;
    *) emit_start_failed "ZAP_FLOATING must be 0 or 1" ;;
esac

if ! is_positive_integer "$READY_TIMEOUT"; then
    emit_start_failed "ZAP_READY_TIMEOUT must be a positive integer"
fi
if ! command -v python3 >/dev/null 2>&1 && [ -n "$INITIAL_PROMPT" ]; then
    emit_start_failed "python3 is required to relay the initial prompt"
fi
if ! zellij action list-panes --json >/dev/null 2>&1; then
    emit_start_failed "not in a zellij session"
fi

if [ ! -d "$CWD" ]; then
    emit_start_failed "directory '$CWD' does not exist"
fi
CWD_ABS="$(cd "$CWD" 2>/dev/null && pwd)" || emit_start_failed "cannot access '$CWD'"

CURRENT_TAB_ID=$(get_current_tab_id)
if [ -z "$CURRENT_TAB_ID" ] || [ "$CURRENT_TAB_ID" = "null" ]; then
    emit_start_failed "could not determine the current tab ID"
fi

dir_basename="$(basename "$CWD_ABS")"
if [ -z "$dir_basename" ] || [ "$CWD_ABS" = "/" ]; then
    dir_basename="root"
fi
PANE_LABEL="agent: ${dir_basename}"

if [ -n "$AGENT_ENV" ]; then
    FULL_CMD="${AGENT_ENV} ${AGENT_CMD}"
else
    FULL_CMD="$AGENT_CMD"
fi

launch_stdout=$(mktemp /tmp/zellij-agent-launch-stdout-XXXXXX)
launch_stderr=$(mktemp /tmp/zellij-agent-launch-stderr-XXXXXX)

launch_args=(action new-pane --block-until-exit-failure --tab-id "$CURRENT_TAB_ID" --cwd "$CWD_ABS")
if [ "$FLOATING" = "1" ]; then
    launch_args+=(--floating)
else
    launch_args+=(--direction "$DIRECTION")
fi

set +e
zellij "${launch_args[@]}" -- \
    bash -c 'exec bash -c "$1"' zellij-agent-launch "$FULL_CMD" >"$launch_stdout" 2>"$launch_stderr"
launch_status=$?
set -e

launch_output=$(<"$launch_stdout")
rm -f "$launch_stdout"

if [ "$launch_status" -ne 0 ]; then
    echo "START_FAILED: zellij could not create the Agent pane (launcher exit ${launch_status})." >&2
    if [ -s "$launch_stderr" ]; then
        echo "zellij diagnostics:" >&2
        tail -n 8 "$launch_stderr" >&2
    fi
    rm -f "$launch_stderr"
    exit 1
fi

new_id=$(normalize_pane_id "$launch_output") || {
    rm -f "$launch_stderr"
    emit_start_failed "zellij created a pane but did not return its pane ID"
}
rm -f "$launch_stderr"

if ! zellij action rename-pane --pane-id "$new_id" "$PANE_LABEL"; then
    emit_start_failed "created pane $new_id but could not rename it"
fi

printf '%s\n' "$new_id"

if [ -z "$INITIAL_PROMPT" ]; then
    exit 0
fi

if ! wait_for_agent_ready "$new_id"; then
    emit_start_failed "agent pane $new_id started but did not show ZAP_READY_MARK within ${READY_TIMEOUT}s; the initial prompt was not sent"
fi
printf 'Agent ready in pane %s.\n' "$new_id"

prompt_file="/tmp/zellij-agent-init-${new_id}-${SCRIPT_PID}.md"
prompt_len=$(printf '%s' "$INITIAL_PROMPT" | wc -c)

if ! printf '%s' "$INITIAL_PROMPT" >"$prompt_file"; then
    emit_start_failed "could not stage the initial prompt"
fi

if [ "$prompt_len" -gt 2000 ]; then
    pointer="Read ${prompt_file} and execute its complete task. Delete the file when finished."
    if ! python3 - "$new_id" "$pointer" <<'PYEOF'
import subprocess
import sys
import time

pane, content = sys.argv[1:]
for command in (
    ["zellij", "action", "send-keys", "--pane-id", pane, "Ctrl u"],
    ["zellij", "action", "write-chars", "--pane-id", pane, content],
):
    result = subprocess.run(command)
    if result.returncode:
        raise SystemExit(result.returncode)
    time.sleep(0.1)
result = subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Enter"])
raise SystemExit(result.returncode)
PYEOF
    then
        emit_start_failed "could not send the pointer for the initial prompt to pane $new_id"
    fi
    printf 'Sent prompt pointer to %s (prompt was %s chars).\n' "$prompt_file" "$prompt_len"
else
    if ! python3 - "$new_id" "$prompt_file" <<'PYEOF'
import subprocess
import sys
import time

pane, path = sys.argv[1:]
with open(path, "r", encoding="utf-8") as prompt_file:
    content = prompt_file.read()
for command in (
    ["zellij", "action", "send-keys", "--pane-id", pane, "Ctrl u"],
    ["zellij", "action", "write-chars", "--pane-id", pane, content],
):
    result = subprocess.run(command)
    if result.returncode:
        raise SystemExit(result.returncode)
    time.sleep(0.1)
result = subprocess.run(["zellij", "action", "send-keys", "--pane-id", pane, "Enter"])
raise SystemExit(result.returncode)
PYEOF
    then
        rm -f "$prompt_file"
        emit_start_failed "could not send the initial prompt to pane $new_id"
    fi
    rm -f "$prompt_file"
    printf 'Sent initial prompt to pane %s.\n' "$new_id"
fi
