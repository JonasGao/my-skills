#!/usr/bin/env bash
# Close the pane agent owned by the current developer-reviewer loop.
# Usage: close-pane.sh <terminal-pane-id>

set -u

case "${1:-}" in
    --help|-h)
        awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "$0"
        exit 0
        ;;
esac

emit_failed() {
    printf 'CLOSE_FAILED: %s\n' "$*" >&2
    exit 1
}

normalize_terminal_id() {
    local raw="$1"
    local numeric

    if [[ "$raw" =~ ^terminal_([0-9]+)$ ]]; then
        numeric="${BASH_REMATCH[1]}"
    elif [[ "$raw" =~ ^[0-9]+$ ]]; then
        numeric="$raw"
    else
        return 1
    fi

    while [ "${#numeric}" -gt 1 ] && [ "${numeric:0:1}" = "0" ]; do
        numeric="${numeric:1}"
    done
    printf '%s\n' "$numeric"
}

[ "$#" -eq 1 ] || emit_failed "expected one terminal pane ID"

pane_id="$1"
normalized_pane_id=$(normalize_terminal_id "$pane_id") || \
    emit_failed "invalid terminal pane ID '$pane_id'"

if [ -n "${ZELLIJ_PANE_ID:-}" ]; then
    normalized_self=$(normalize_terminal_id "$ZELLIJ_PANE_ID" 2>/dev/null || true)
    if [ -n "$normalized_self" ] && [ "$normalized_pane_id" = "$normalized_self" ]; then
        emit_failed "refusing to close the current pane '$pane_id'"
    fi
fi

zellij action close-pane --pane-id "$pane_id"
close_status=$?
if [ "$close_status" -ne 0 ]; then
    printf 'CLOSE_FAILED: pane=%s zellij_status=%s\n' "$pane_id" "$close_status" >&2
    exit "$close_status"
fi

printf 'CLOSED: pane=%s\n' "$pane_id"
