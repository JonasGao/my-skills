---
name: zellij-claude-pane
description: "Create a new zellij pane and start a Claude Code session in it. Use whenever the user wants to spawn a parallel Claude Code instance in a new zellij pane — e.g. 'open a new claude pane', 'start claude in a new pane', 'spawn another claude', 'create a parallel claude session', 'new pane with claude', 'split pane and run claude', or when running multiple Claude Code instances side by side in zellij. Also use when the user wants to hand off a task to a fresh Claude session in its own pane. Do NOT use this for relaying prompts to an EXISTING agent pane — that is zellij-relay-prompt."
---

# Open a Claude Code pane in zellij

Create a new zellij pane and start a fresh Claude Code session in it. The pane
opens next to the current one, inherits the working directory, and is
automatically named (e.g. `claude: myproject`).

If the tiled layout is full, the script falls back to `--floating` automatically.

`scripts/` paths are relative to this skill's directory.

## Workflow

1. **Open the pane:**
   ```bash
   bash scripts/new-pane.sh [direction] [cwd] [initial-prompt]
   ```
   - `direction` (optional): `right` (default), `down`. zellij only supports
     `right`/`down`; `left`/`up` silently fall back to `right`.
   - `cwd` (optional): working directory (defaults to current pane's cwd)
   - `initial-prompt` (optional): task to send to the new Claude session

   The script tries tiled first, verifies the pane rendered, and falls back
   to `--floating` if the pane turns out to be a ghost (layout full). Outputs
   the new pane ID (e.g. `terminal_42`).

2. **Confirm** the new pane is running. Optionally verify:
   ```bash
   zellij action dump-screen --pane-id <id> --path /tmp/claude-verify.txt && tail -5 /tmp/claude-verify.txt
   ```

## Sending an initial prompt

Pass a task as the third argument to have it automatically typed into the new
Claude session (best-effort — Claude Code must have finished loading):

```bash
bash scripts/new-pane.sh right /home/god/myproject "Review the auth module for security issues"
```

Or via env:
```bash
ZCP_INITIAL_PROMPT="Review the auth module" bash scripts/new-pane.sh
```

**Long prompts (>2KB):** the script writes the prompt to
`/tmp/zellij-claude-init-<pane-id>.md` and sends a short pointer instead,
avoiding `write-chars` truncation. If the prompt is short, it's relayed
directly via `write-chars` with special characters preserved.

If you need reliable prompt delivery to an **existing** pane, use
`zellij-relay-prompt` instead — it's built for that.

## Follow-up interaction (relay prompts to the new pane)

After creating a pane, ongoing communication uses `zellij-relay-prompt`:

- **Send more prompts** — use `scripts/find-pane.sh` + `scripts/relay.py` from
  `zellij-relay-prompt` to relay follow-up tasks.
- **Get notified when done** — append this to any relayed prompt so the
  target pane signals back when finished:

  ```
  完成后运行: bash <abs-path-to-zellij-relay-prompt>/scripts/notify-complete.sh <your-pane-id> "done: <summary>"
  ```

  This types a `✓` message into your pane. Best-effort — if silent, check the
  target with `dump-screen`.

See `zellij-relay-prompt` SKILL.md for full relay workflow.

## Configuration

**Claude command priority** (highest to lowest):
1. User's request (e.g. "use `claude --dangerously-skip-permissions`") — pass via `ZCP_CLAUDE_CMD`
2. `ZCP_CLAUDE_CMD` env var
3. Default: `claude`

| Env var | Default | Purpose |
|---------|---------|---------|
| `ZCP_CLAUDE_CMD` | `claude` | Binary name for Claude Code |
| `ZCP_CLAUDE_ENV` | — | Extra env vars prepended to the command (e.g. `ANTHROPIC_MODEL=sonnet`) |
| `ZCP_INITIAL_PROMPT` | — | Fallback if no 3rd arg given |
| `ZCP_FLOATING` | `0` | Set to `1` to skip tiled attempt entirely |

## Choosing between this skill and zellij-relay-prompt

| Situation | Use |
|-----------|-----|
| Need a brand-new Claude session in its own pane | `zellij-claude-pane` |
| Want to hand off a task to an **existing** agent pane | `zellij-relay-prompt` |
| Create a new pane, then send follow-up tasks to it | `zellij-claude-pane` (create), then `zellij-relay-prompt` (interact) |

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/new-pane.sh` | Create a new pane, start Claude Code, optionally send a prompt |

See `zellij-io.md` for raw zellij command semantics.
