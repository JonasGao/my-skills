#!/usr/bin/env bash
# Launch a fresh Hunk session in a new Herdr tab (TUI) or herdr-core terminal,
# then wait until it registers with the Hunk daemon.
# Success: one JSON line on stdout {env, repo, session_id, address|tab_id/pane_id, name?}.
# Failure: non-zero exit, diagnostics (incl. launch screen dump) on stderr.
set -euo pipefail

POLL_INTERVAL=3   # seconds between session-list checks
POLL_TRIES=10     # ~30s total

die() { echo "launch-hunk: $*" >&2; exit 1; }

command -v jq >/dev/null 2>&1 || die "jq is required"
command -v hunk >/dev/null 2>&1 || die "hunk not in PATH"
# core spawns with the login environment, not our PATH: always pass absolute paths
HUNK_BIN=$(command -v hunk)

# --- 0. environment, repo root, baseline -----------------------------------
if [ "${HERDR_ENV:-}" = "1" ]; then
  ENV=tui
  command -v herdr >/dev/null 2>&1 || die "HERDR_ENV=1 but herdr not in PATH"
elif [ -n "${HC_TERMINAL_ID:-}" ]; then
  ENV=core
  command -v hc >/dev/null 2>&1 || die "HC_TERMINAL_ID set but hc not in PATH"
else
  die "not inside Herdr (need HERDR_ENV=1 for TUI or HC_TERMINAL_ID for core)"
fi

REPO=$(git rev-parse --show-toplevel 2>/dev/null) || die "not inside a git repository"
BASELINE=$(hunk session list --json | jq -c '[.sessions[].sessionId]') \
  || die "hunk session list failed (daemon unreachable?)"

# --- 1. launch hunk diff in a new tab / terminal ---------------------------
ADDR="" NAME="" TAB_ID="" PANE_ID=""
if [ "$ENV" = core ]; then
  LIVE_NAMES=$(hc ls --json | jq -r '.terminals[].name // empty')
  NAME=hunk-review; n=2
  while grep -qx "$NAME" <<<"$LIVE_NAMES"; do NAME="hunk-review-$n"; n=$((n+1)); done
  LAUNCH=$(hc run --bg --outlive-parent --json --name "$NAME" --cwd "$REPO" "$HUNK_BIN" diff 2>&1) \
    || die "hc run failed: $LAUNCH"
  ADDR=$(jq -r '.address // empty' <<<"$LAUNCH")
  [ -n "$ADDR" ] || die "no terminal address in hc run response: $LAUNCH"
else
  TAB_JSON=$(herdr tab create --cwd "$REPO" --label hunk-review 2>&1) \
    || die "herdr tab create failed: $TAB_JSON"
  TAB_ID=$(jq -r '.tab.id // .tab_id // .id // empty' <<<"$TAB_JSON")
  PANE_ID=$(jq -r '.pane.id // .pane_id // .panes[0].id // .panes[0].pane_id // empty' <<<"$TAB_JSON")
  if [ -z "$PANE_ID" ] && [ -n "$TAB_ID" ]; then
    PANE_ID=$(herdr pane list --json | jq -r --arg t "$TAB_ID" \
      '[(.panes // .items // [])[] | select((.tab_id // .tabId // .tab) == $t)][0] | (.id // .pane_id // empty)')
  fi
  [ -n "$PANE_ID" ] || die "cannot resolve pane id from tab create response: $TAB_JSON"
  herdr pane run "$PANE_ID" "$HUNK_BIN diff" >/dev/null || die "herdr pane run failed"
fi

dump_screen() {
  echo "--- launch screen ($ENV) ---" >&2
  if [ "$ENV" = core ]; then hc read "$ADDR" --lines 40 >&2 || true
  else herdr pane read "$PANE_ID" --lines 40 >&2 || true; fi
}

# --- 2. wait for a session id absent from the baseline ---------------------
for _ in $(seq 1 "$POLL_TRIES"); do
  sleep "$POLL_INTERVAL"
  if [ "$ENV" = core ]; then
    STATE=$(hc get "$ADDR" --json | jq -r '.state // empty')
    if [ "$STATE" = finished ]; then
      dump_screen
      die "hunk exited before registering a session (exit=$(hc get "$ADDR" --json | jq -r '.exit_code // "?"'))"
    fi
  fi
  NEW=$(hunk session list --json | jq -c \
    --argjson base "$BASELINE" --arg repo "$REPO" \
    '[.sessions[] | select(.sessionId as $s | $base | index($s) | not)]
     | sort_by(.repoRoot != $repo) | .[0] // empty')
  if [ -n "$NEW" ]; then
    SID=$(jq -r '.sessionId' <<<"$NEW")
    if [ "$ENV" = core ]; then
      jq -cn --arg repo "$REPO" --arg sid "$SID" --arg addr "$ADDR" --arg name "$NAME" \
        '{env:"core", repo:$repo, session_id:$sid, address:$addr, name:$name}'
    else
      jq -cn --arg repo "$REPO" --arg sid "$SID" --arg tab "$TAB_ID" --arg pane "$PANE_ID" \
        '{env:"tui", repo:$repo, session_id:$sid, tab_id:$tab, pane_id:$pane}'
    fi
    exit 0
  fi
done

dump_screen
die "no new Hunk session within $((POLL_INTERVAL * POLL_TRIES))s; if Hunk is visibly running, see hunk-review skill 'Common errors' (localhost/sandbox)"