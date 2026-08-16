#!/usr/bin/env python3
"""Relay the staged prompt to a zellij pane running a coding agent.

Usage:
    relay.py <pane-id> <prompt-file>

Positional arguments:
    pane-id       Target pane id (numeric like 354 or string like terminal_354,
                  plugin_42). Find candidates with scripts/find-pane.sh.
    prompt-file   Required unique path to the staged prompt.

Behavior:
    1. Reads the staged prompt from <prompt-file>.
    2. Guards the target pane: exits 1 if the target pane is not in
       `zellij action list-panes` (stale id).
    3. If the prompt exceeds 2000 chars, writes the full content to a unique
       Markdown file in the system temporary directory and sends a short
       Chinese pointer instead. Prints the retained file path to stderr.
    4. Sends Ctrl+u to clear the target's input line, write-chars the
       (possibly shortened) prompt verbatim, sleeps briefly, then sends
       Enter. write-chars is used (not write) because it simulates typing
       and lands in the coding agent's TUI input box; raw `write` bytes
       do not. Reading from a file means backticks, $, quotes, and
       newlines all survive without shell escaping.
    5. On success, deletes the staged prompt file (the original path, not
       the long-prompt pointer).

Exit codes:
    0   relay succeeded.
    1   runtime error (zellij unreachable, file not readable, empty file,
        Ctrl+u / write-chars / Enter failed, stale target pane, long-prompt
        temp file write failed).
    2   usage error (missing pane-id or prompt-file).

Side effects:
    - On success, deletes <prompt-file> (the staged prompt).
    - If the prompt exceeds 2000 chars, creates a unique current-user-only
      Markdown file in the system temporary directory containing the full text.
      The script and receiving agent both leave it for system-managed cleanup.

Full interface and contract: see SKILL.md.
"""
import subprocess
import sys
import time
import json
import os
import re
import tempfile

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


def long_prompt_prefix(pane):
    """Return a temp-file-safe prefix that remains useful when debugging."""
    safe_pane = re.sub(r"[^A-Za-z0-9_.-]", "_", str(pane))
    return f"zellij-relay-long-{safe_pane}-"


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ("--help", "-h"):
        print(__doc__)
        sys.exit(0)

    if len(sys.argv) < 3:
        print("Usage: relay.py <pane-id> <prompt-file>", file=sys.stderr)
        sys.exit(2)

    pane = sys.argv[1]
    prompt_file = sys.argv[2]
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

    # Guard: stale pane id.
    if not pane_exists(pane):
        print(
            f"Error: pane {pane} not found. "
            "Re-run scripts/find-pane.sh for a current id.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Handle long prompts: write to temp file, send a short pointer.
    if len(content) > TRUNCATION_THRESHOLD:
        prompt_length = len(content)
        pointer_file = ""
        try:
            fd, pointer_file = tempfile.mkstemp(
                prefix=long_prompt_prefix(pane),
                suffix=".md",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            location = pointer_file or "the system temporary directory"
            print(f"Error: cannot write {location}: {e}", file=sys.stderr)
            sys.exit(1)
        content = (
            f"请读取 {pointer_file} 并完整执行其中的任务。"
        )
        print(
            f"Warning: prompt is {prompt_length} chars (threshold {TRUNCATION_THRESHOLD}), "
            f"full content retained for debugging at {pointer_file}.",
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
    time.sleep(max(0.3, min(len(content) * 0.001, 1.0)))

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
