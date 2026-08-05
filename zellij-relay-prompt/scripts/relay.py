#!/usr/bin/env python3
"""Relay the staged prompt to a zellij pane running a coding agent.

Usage: relay.py <pane-id> [prompt-file]

Reads the staged prompt, clears the target's input line, types it verbatim,
and submits it. Exits non-zero on failure.

The prompt file defaults to /tmp/zellij-relay-prompt-<pane-id>.md - per-target,
not a shared path, so concurrent relays to different panes don't clobber each
other. Pass an explicit path to override.

write-chars is used (not write) because it simulates typing and lands in the
coding agent's TUI input box; raw `write` bytes do not. Reading from a file
means backticks, $, quotes, and newlines all survive without shell escaping.
"""
import subprocess
import sys
import time
import json


def pane_exists(pane):
    """Best-effort check that the pane id is currently live. Never blocks on a
    zellij failure (returns True so the caller can proceed and let zellij error)."""
    r = subprocess.run(["zellij", "action", "list-panes", "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return True
    try:
        ids = {p.get("id") for p in json.loads(r.stdout)}
    except (json.JSONDecodeError, TypeError):
        return True
    try:
        return int(pane) in ids
    except ValueError:
        return pane in ids


def make_sender(pane):
    """Return a function that runs a zellij action against `pane`."""
    def send(action, *extra):
        return subprocess.run(
            ["zellij", "action", action, "--pane-id", pane, *extra],
            capture_output=True, text=True,
        )
    return send


def main():
    if len(sys.argv) < 2:
        print("Usage: relay.py <pane-id> [prompt-file]", file=sys.stderr)
        sys.exit(2)
    pane = sys.argv[1]
    prompt_file = sys.argv[2] if len(sys.argv) > 2 else f"/tmp/zellij-relay-prompt-{pane}.md"
    send = make_sender(pane)

    try:
        with open(prompt_file, "r") as f:
            content = f.read()
    except OSError as e:
        print(f"Error: cannot read {prompt_file}: {e}", file=sys.stderr)
        sys.exit(1)
    if not content.strip():
        print(f"Error: {prompt_file} is empty", file=sys.stderr)
        sys.exit(1)

    # Guard against stale pane ids: zellij silently drops actions to a pane that
    # no longer exists, which would otherwise look like a successful relay.
    if not pane_exists(pane):
        print(f"Error: pane {pane} not found. Re-run scripts/find-pane.sh for a current id.",
              file=sys.stderr)
        sys.exit(1)

    # Clear any text already sitting in the target's input line.
    send("send-keys", "Ctrl u")

    # Type the prompt. Characters are sent as input events, so they reach the
    # input box literally regardless of shell-special content.
    r = send("write-chars", content)
    if r.returncode != 0:
        print(f"Error: write-chars failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Let the target terminal finish processing the characters before submitting.
    time.sleep(0.2)
    send("send-keys", "Enter")

    print(f"Relayed {len(content)} chars to pane {pane} (from {prompt_file}).")


if __name__ == "__main__":
    main()
