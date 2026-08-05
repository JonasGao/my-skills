---
name: zellij-relay-prompt
description: "Relay a prompt to another zellij pane running a coding agent (Claude Code, Codex, OpenCode, Aider, etc.), so that separate agent instance executes it. Use whenever the user wants to delegate or hand off a task to another coding-agent session in a different zellij pane - e.g. 'send this to the other pane', 'relay this prompt', 'ask the other agent to ...', 'delegate to pane X', 'run this in the retail-platform pane', or when coordinating work across multiple parallel agent sessions. Also use when the user refers to a zellij pane by id/title or wants one agent to drive another."
---

# Relay a prompt through zellij

Send a prompt to another zellij pane running a coding agent (Claude Code, Codex,
OpenCode, Aider, ...) so that pane runs it. This lets you parallelize work across
multiple agent sessions.

The relayed prompt is real - the target agent runs it. Only relay tasks you want
executed.

`scripts/` paths are relative to this skill's directory.

## Workflow

1. **Find the target pane:**
   ```bash
   bash scripts/find-pane.sh
   ```
   Each line: `<pane-id>\t<title>\t<cwd>`. User named a pane - use it. One match -
   use it. Several - list them and ask. None - stop, tell the user to start a
   coding agent in another pane. (Override which commands count as agents via
   `$CODE_AGENT_RE`; default matches claude, codex, opencode, aider, gemini.)

2. **Stage the prompt** to `/tmp/zellij-relay-prompt-<pane-id>.md` (overwrite).
   Use your file-writing tool, not `echo` - a file preserves backticks, `$`, quotes,
   newlines. The filename is per-target so concurrent relays don't clobber each other.

3. **Relay:**
   ```bash
   python3 scripts/relay.py <pane-id>
   ```
   Reads `/tmp/zellij-relay-prompt-<pane-id>.md` by default, clears the target's
   input, types the prompt verbatim, presses Enter. Prints chars sent or an error.

4. **Confirm** the target pane ID to the user. Optionally verify it landed:
   ```bash
   zellij action dump-screen --pane-id <pane-id> --path /tmp/relay-verify.txt && tail -15 /tmp/relay-verify.txt
   ```

## Completion notification (optional, best-effort)

To have the target signal when done, append this to the staged prompt - it types a
message back into your pane as a new input line so you can pick up the result:

```
完成后运行: bash <abs-path-to-this-skill>/scripts/notify-complete.sh $ZELLIJ_PANE_ID "done: <summary>"
```

Use the absolute script path (the target may lack this skill). Best-effort: the
target may be busy or decline; if silent, check it with `dump-screen`.

## Troubleshooting

- No panes found / stale ID -> re-run `find-pane.sh` (IDs change when panes reopen).
- Target was busy -> wait, then re-run `relay.py`.
- Truncated long prompt -> split it, or hand off via a file the target reads.
- Agent not matched -> set `CODE_AGENT_RE` to include its command name.

See `zellij-io.md` for raw zellij command semantics.
