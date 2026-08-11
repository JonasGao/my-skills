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
import os
import re

# write-chars may truncate beyond ~2KB. Above this threshold, write the
# prompt to a temp file and send a short pointer instead.
TRUNCATION_THRESHOLD = 2000


def normalize_pane_id(pane):
    """Strip terminal_ / plugin_ prefix, return integer id."""
    pane_str = str(pane)
    for prefix in ("terminal_", "plugin_"):
        if pane_str.startswith(prefix):
            pane_str = pane_str[len(prefix):]
            break
    try:
        return int(pane_str)
    except ValueError:
        return pane_str  # non-standard id, pass through as-is


def pane_exists(pane):
    """Best-effort check that the pane id is currently live.

    Accepts both numeric ids (354) and string ids (terminal_354, plugin_42)."""
    try:
        r = subprocess.run(
            ["zellij", "action", "list-panes", "--json"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, OSError) as e:
        print(f"Error: cannot run zellij: {e}", file=sys.stderr)
        sys.exit(1)

    if r.returncode != 0:
        return True  # err on the side of allowing the relay
    try:
        panes = json.loads(r.stdout)
    except (json.JSONDecodeError, TypeError):
        return True

    numeric_id = normalize_pane_id(pane)
    return numeric_id in {p.get("id") for p in panes}


def make_sender(pane):
    """Return a function that runs a zellij action against `pane`."""
    def send(action, *extra):
        try:
            return subprocess.run(
                ["zellij", "action", action, "--pane-id", pane, *extra],
                capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            print("Error: zellij binary not found on PATH", file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            print(f"Error: cannot execute zellij: {e}", file=sys.stderr)
            sys.exit(1)
    return send


def main():
    if len(sys.argv) < 2:
        print("Usage: relay.py <pane-id> [prompt-file]", file=sys.stderr)
        sys.exit(2)

    pane = sys.argv[1]
    prompt_file = sys.argv[2] if len(sys.argv) > 2 else f"/tmp/zellij-relay-prompt-{pane}.md"
    send = make_sender(pane)

    # Read the staged prompt.
    try:
        with open(prompt_file, "r") as f:
            content = f.read()
    except OSError as e:
        print(f"Error: cannot read {prompt_file}: {e}", file=sys.stderr)
        sys.exit(1)
    if not content.strip():
        print(f"Error: {prompt_file} is empty", file=sys.stderr)
        sys.exit(1)

    # Guard 1: validate notify-complete.sh pane IDs in the prompt.
    # Agents sometimes invent a pane ID instead of using $ZELLIJ_PANE_ID;
    # catch this early so the target doesn't notify a wrong/non-existent pane.
    _NOTIFY_RE = re.compile(r'notify-complete\.sh\s+(terminal_\d+|plugin_\d+|\d+)')
    my_pane = os.environ.get("ZELLIJ_PANE_ID", "")
    for m in _NOTIFY_RE.finditer(content):
        ref_id = m.group(1)
        if my_pane and str(normalize_pane_id(ref_id)) != str(normalize_pane_id(my_pane)):
            print(
                f"Warning: notify-complete.sh references pane {ref_id}, "
                f"but your pane is {my_pane}. "
                f"Check <your-pane-id> in the notification snippet — "
                f"it must be YOUR pane ID, not the target's. "
                f"Run: echo $ZELLIJ_PANE_ID",
                file=sys.stderr,
            )

    # Guard 2: stale pane id.
    if not pane_exists(pane):
        print(
            f"Error: pane {pane} not found. "
            "Re-run scripts/find-pane.sh for a current id.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Handle long prompts: write to temp file, send a short pointer.
    if len(content) > TRUNCATION_THRESHOLD:
        pointer_file = f"/tmp/zellij-relay-long-{pane}.md"
        try:
            with open(pointer_file, "w") as f:
                f.write(content)
        except OSError as e:
            print(f"Error: cannot write {pointer_file}: {e}", file=sys.stderr)
            sys.exit(1)
        content = (
            f"请读取 {pointer_file} 并完整执行其中的任务。完成后删除该文件。"
        )
        print(
            f"Warning: prompt is {len(content)} chars (threshold {TRUNCATION_THRESHOLD}), "
            f"full content written to {pointer_file}.",
            file=sys.stderr,
        )

    # Clear any text already sitting in the target's input line.
    r = send("send-keys", "Ctrl u")
    if r.returncode != 0:
        print(f"Error: Ctrl+u failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Type the prompt.
    r = send("write-chars", content)
    if r.returncode != 0:
        print(f"Error: write-chars failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Let the target terminal finish processing the characters.
    time.sleep(max(0.2, min(len(content) * 0.001, 1.0)))

    r = send("send-keys", "Enter")
    if r.returncode != 0:
        print(f"Error: Enter failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Clean up the staged file now that the relay succeeded.
    try:
        os.remove(prompt_file)
    except OSError:
        pass

    print(f"Relayed {len(content)} chars to pane {pane} (from {prompt_file}).")


if __name__ == "__main__":
    main()
