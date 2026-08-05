#!/bin/bash
# Send a completion notification to another zellij pane
# Usage: notify-complete.sh <target-pane-id> <message>
# Example: notify-complete.sh terminal_239 "任务完成: echo 命令执行成功"

if [ $# -lt 2 ]; then
    echo "Usage: $0 <target-pane-id> <message>" >&2
    exit 1
fi

TARGET_PANE="$1"
MESSAGE="$2"

# Send the notification message to the target pane
zellij action write-chars --pane-id "$TARGET_PANE" "✓ $MESSAGE"
sleep 0.2
zellij action send-keys --pane-id "$TARGET_PANE" "Enter"