#!/usr/bin/env python3
"""Relay the staged prompt to a zellij pane running a coding agent.

Usage: relay.py <pane-id> [prompt-file] [--force]

Reads the staged prompt, clears the target's input line, types it verbatim,
and submits it. Exits non-zero on failure.

The prompt file defaults to /tmp/zellij-relay-prompt-<pane-id>.md - per-target,
not a shared path, so concurrent relays to different panes don't clobber each
other. Pass an explicit path to override.

write-chars is used (not write) because it simulates typing and lands in the
coding agent's TUI input box; raw `write` bytes do not. Reading from a file
means backticks, $, quotes, and newlines all survive without shell escaping.

Use --force to relay to a non-agent pane (e.g., a plain shell). Without it,
the target's pane_command is checked against a known agent list and relaying
to a non-agent pane is refused — to avoid executing prompt text as shell
commands.
"""
import subprocess
import sys
import time
import json
import os
import re

# Regex of known coding agent commands (same default as find-pane.sh).
AGENT_RE = re.compile(
    os.environ.get("CODE_AGENT_RE", r"claude|codex|opencode|aider|gemini"),
    re.IGNORECASE,
)

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


def get_pane_info(pane):
    """Return the pane's metadata dict from list-panes, or None."""
    try:
        r = subprocess.run(
            ["zellij", "action", "list-panes", "--json"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    try:
        panes = json.loads(r.stdout)
    except (json.JSONDecodeError, TypeError):
        return None

    numeric_id = normalize_pane_id(pane)
    for p in panes:
        if p.get("id") == numeric_id:
            return p
    return None


def is_agent_pane(pane):
    """Check whether the pane is running a known coding agent."""
    info = get_pane_info(pane)
    if info is None:
        return False
    pane_cmd = info.get("pane_command") or ""
    return bool(AGENT_RE.search(pane_cmd))


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
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv

    if len(args) < 1:
        print("Usage: relay.py <pane-id> [prompt-file] [--force]", file=sys.stderr)
        sys.exit(2)

    pane = args[0]
    prompt_file = args[1] if len(args) > 1 else f"/tmp/zellij-relay-prompt-{pane}.md"
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

    # Guard 1: stale pane id.
    if not pane_exists(pane):
        print(
            f"Error: pane {pane} not found. "
            "Re-run scripts/find-pane.sh for a current id.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Guard 2: target is a coding agent (unless --force).
    if not force and not is_agent_pane(pane):
        print(
            f"Error: pane {pane} does not appear to be a coding agent. "
            "Relaying a prompt to a plain shell would execute it as shell commands. "
            "Use --force to override.",
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
