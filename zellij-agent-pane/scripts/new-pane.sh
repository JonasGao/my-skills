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
#   ZAP_DEBUG           set to 1 to emit launch and ready-wait diagnostics to stderr
#
# Exit status:
#   0  pane created, and the initial prompt was sent when supplied
#   1  START_FAILED: configuration was valid but pane creation or relay failed
#   2  ACTION_REQUIRED: reports missing=ZAP_* names; ask only for those values, then retry once

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

debug() {
    [ "${DEBUG:-0}" = "1" ] || return 0
    printf 'ZAP_DEBUG: pid=%s %s\n' "$SCRIPT_PID" "$*" >&2
}

cleanup_startup_files() {
    rm -f "${STARTUP_STATUS_FILE:-}" "${STARTUP_ARM_FILE:-}"
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
    local dump_status
    local snapshot_bytes

    debug "ready wait started: pane=${pane_id} timeout_seconds=${READY_TIMEOUT}"
    while [ "$elapsed" -lt "$READY_TIMEOUT" ]; do
        rm -f "$tmpfile"
        debug "ready probe started: pane=${pane_id} attempt=$((elapsed + 1))"
        if zellij action dump-screen --pane-id "$pane_id" --path "$tmpfile" 2>/dev/null; then
            dump_status=0
        else
            dump_status=$?
        fi
        snapshot_bytes=0
        if [ -f "$tmpfile" ]; then
            snapshot_bytes=$(wc -c <"$tmpfile")
        fi
        if grep -qF -- "$READY_MARK" "$tmpfile" 2>/dev/null; then
            debug "ready probe finished: pane=${pane_id} attempt=$((elapsed + 1)) dump_screen_status=${dump_status} snapshot_bytes=${snapshot_bytes} mark_found=1"
            rm -f "$tmpfile"
            return 0
        fi
        debug "ready probe finished: pane=${pane_id} attempt=$((elapsed + 1)) dump_screen_status=${dump_status} snapshot_bytes=${snapshot_bytes} mark_found=0"
        sleep 1
        elapsed=$((elapsed + 1))
    done

    rm -f "$tmpfile"
    debug "ready wait timed out: pane=${pane_id} completed_attempts=${elapsed}"
    return 1
}

wait_for_agent_start() {
    local pane_id="$1"
    local status_file="$2"
    local arm_file="$3"
    local attempt

    AGENT_START_EXIT=""
    debug "agent startup check started: pane=${pane_id} window_tenths=10"
    for ((attempt = 1; attempt <= 10; attempt++)); do
        if [ -s "$status_file" ]; then
            if ! read -r AGENT_START_EXIT <"$status_file"; then
                AGENT_START_EXIT="unknown"
            fi
            rm -f "$status_file" "$arm_file"
            debug "agent startup check failed: pane=${pane_id} exit_status=${AGENT_START_EXIT} attempt=${attempt}"
            return 1
        fi
        sleep 0.1
    done

    rm -f "$status_file" "$arm_file"
    debug "agent startup check passed: pane=${pane_id} window_tenths=10"
    return 0
}

print_action_required_and_exit() {
    local missing=()
    local missing_csv

    if [ -z "$AGENT_CMD" ]; then
        missing+=(ZAP_AGENT_CMD)
    fi
    if [ -n "$INITIAL_PROMPT" ] && [ -z "$READY_MARK" ]; then
        missing+=(ZAP_READY_MARK)
    fi
    [ "${#missing[@]}" -gt 0 ] || return 0

    missing_csv=$(printf '%s,' "${missing[@]}")
    missing_csv=${missing_csv%,}
    echo "ACTION_REQUIRED: missing=${missing_csv}" >&2
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
DEBUG="${ZAP_DEBUG:-0}"
SCRIPT_PID="$$"
STARTUP_STATUS_FILE=""
STARTUP_ARM_FILE=""
AGENT_START_EXIT=""

trap cleanup_startup_files EXIT

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
case "$DEBUG" in
    0|1) ;;
    *) emit_start_failed "ZAP_DEBUG must be 0 or 1" ;;
esac
debug "launch configuration validated: floating=${FLOATING} prompt_present=$([ -n "$INITIAL_PROMPT" ] && printf 1 || printf 0) agent_env_present=$([ -n "$AGENT_ENV" ] && printf 1 || printf 0) ready_mark_present=$([ -n "$READY_MARK" ] && printf 1 || printf 0) ready_timeout_seconds=${READY_TIMEOUT}"
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
STARTUP_STATUS_FILE=$(mktemp /tmp/zellij-agent-start-status-XXXXXX)
STARTUP_ARM_FILE=$(mktemp /tmp/zellij-agent-start-arm-XXXXXX)
rm -f "$STARTUP_STATUS_FILE"

# Interactive Agents normally keep running. A zellij --block-until-* option
# would therefore hold this launcher open instead of returning the pane ID.
launch_args=(action new-pane --tab-id "$CURRENT_TAB_ID" --cwd "$CWD_ABS")
if [ "$FLOATING" = "1" ]; then
    launch_args+=(--floating)
else
    launch_args+=(--direction "$DIRECTION")
fi

set +e
debug "pane creation started: direction=${DIRECTION} floating=${FLOATING}"
zellij "${launch_args[@]}" -- \
    bash -c '
        startup_status="$1"
        startup_arm="$2"
        agent_command="$3"
        trap '\''agent_exit=$?; if [ -e "$startup_arm" ]; then printf "%s\\n" "$agent_exit" >"$startup_status"; fi'\'' EXIT
        bash -c "$agent_command"
    ' zellij-agent-launch "$STARTUP_STATUS_FILE" "$STARTUP_ARM_FILE" "$FULL_CMD" >"$launch_stdout" 2>"$launch_stderr"
launch_status=$?
set -e

launch_output=$(<"$launch_stdout")
rm -f "$launch_stdout"
debug "pane creation finished: zellij_exit=${launch_status} pane_id_returned=$([ -n "$launch_output" ] && printf 1 || printf 0)"

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
debug "pane creation identified: pane=${new_id}"

if ! zellij action rename-pane --pane-id "$new_id" "$PANE_LABEL"; then
    emit_start_failed "created pane $new_id but could not rename it"
fi
debug "pane renamed: pane=${new_id}"

if ! wait_for_agent_start "$new_id" "$STARTUP_STATUS_FILE" "$STARTUP_ARM_FILE"; then
    case "$AGENT_START_EXIT" in
        127)
            emit_start_failed "agent command exited during startup with status 127 (command not found); ask the user to correct ZAP_AGENT_CMD or ZAP_AGENT_ENV, then retry once"
            ;;
        0)
            emit_start_failed "agent command exited during startup with status 0; ask the user for a command that keeps the coding agent running, then retry once"
            ;;
        *)
            emit_start_failed "agent command exited during startup with status ${AGENT_START_EXIT}; ask the user to correct ZAP_AGENT_CMD or ZAP_AGENT_ENV, then retry once"
            ;;
    esac
fi

printf '%s\n' "$new_id"

if [ -z "$INITIAL_PROMPT" ]; then
    debug "launch complete: pane=${new_id} prompt_delivery=skipped"
    exit 0
fi

if ! wait_for_agent_ready "$new_id"; then
    emit_start_failed "agent pane $new_id started but did not show ZAP_READY_MARK within ${READY_TIMEOUT}s; the initial prompt was not sent"
fi
printf 'Agent ready in pane %s.\n' "$new_id"
debug "prompt delivery started: pane=${new_id} prompt_bytes=$(printf '%s' "$INITIAL_PROMPT" | wc -c)"

prompt_len=$(printf '%s' "$INITIAL_PROMPT" | wc -c)

# tempfile selects the platform's system temporary directory and creates the
# task document with current-user-only access.
prompt_file=$(printf '%s' "$INITIAL_PROMPT" | python3 -c '
import os
import sys
import tempfile

fd, path = tempfile.mkstemp(
    prefix=f"zellij-agent-init-{sys.argv[1]}-",
    suffix=".md",
)
try:
    with os.fdopen(fd, "wb") as prompt_file:
        prompt_file.write(sys.stdin.buffer.read())
except BaseException:
    try:
        os.unlink(path)
    except OSError:
        pass
    raise
print(path)
' "$new_id") || {
    emit_start_failed "could not stage the initial prompt"
}

if [ "$prompt_len" -gt 2000 ]; then
    pointer="Read ${prompt_file} and execute its complete task."
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
    printf 'Sent prompt pointer to %s (prompt was %s bytes).\n' "$prompt_file" "$prompt_len"
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
debug "prompt delivery finished: pane=${new_id}"
