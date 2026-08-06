#!/bin/bash
# Send a completion notification to another zellij pane.
# Usage: notify-complete.sh <target-pane-id> <message>
# Example: notify-complete.sh terminal_329 "done: echo 命令执行成功"
#
# Best-effort: verifies the target pane exists before sending. If the target
# is stale or unreachable, exits non-zero with a message to stderr.

if [ $# -lt 2 ]; then
    echo "Usage: $0 <target-pane-id> <message>" >&2
    exit 1
fi

TARGET_PANE="$1"
MESSAGE="$2"

# Guard: refuse to notify ourselves (self-loop).
my_id="${ZELLIJ_PANE_ID:-}"
my_id_numeric=""
# Normalize our own id for comparison.
for prefix in "terminal_" "plugin_"; do
    if [[ "$my_id" == "${prefix}"* ]]; then
        my_id_numeric="${my_id#${prefix}}"
        break
    fi
done
[ -z "$my_id_numeric" ] && my_id_numeric="$my_id"

target_normalized="$TARGET_PANE"
for prefix in "terminal_" "plugin_"; do
    if [[ "$target_normalized" == "${prefix}"* ]]; then
        target_normalized="${target_normalized#${prefix}}"
        break
    fi
done

if [ "$target_normalized" = "$my_id_numeric" ] && [ -n "$my_id_numeric" ]; then
    echo "notify-complete.sh: Error: refusing to notify own pane ($TARGET_PANE)" >&2
    exit 1
fi

# Check zellij is reachable.
if ! zellij action list-panes --json &>/dev/null; then
    echo "notify-complete.sh: Error: not in a zellij session" >&2
    exit 1
fi

# Best-effort liveness check via dump-screen.
if ! zellij action dump-screen --pane-id "$TARGET_PANE" --path /tmp/zellij-notify-check-$$.txt 2>/dev/null; then
    echo "notify-complete.sh: Error: pane $TARGET_PANE is unreachable (stale id?)" >&2
    rm -f /tmp/zellij-notify-check-$$.txt
    exit 1
fi
rm -f /tmp/zellij-notify-check-$$.txt

# Send the notification.
if ! zellij action write-chars --pane-id "$TARGET_PANE" "✓ $MESSAGE"; then
    echo "notify-complete.sh: Error: write-chars to $TARGET_PANE failed" >&2
    exit 1
fi
sleep 0.2
if ! zellij action send-keys --pane-id "$TARGET_PANE" "Enter"; then
    echo "notify-complete.sh: Error: send-keys to $TARGET_PANE failed" >&2
    exit 1
fi
