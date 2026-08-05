---
name: zellij-claude-pane
description: "Create a new zellij pane and start a Claude Code session in it. Use whenever the user wants to spawn a parallel Claude Code instance in a new zellij pane — e.g. 'open a new claude pane', 'start claude in a new pane', 'spawn another claude', 'create a parallel claude session', 'new pane with claude', 'split pane and run claude', or when running multiple Claude Code instances side by side in zellij. Also use when the user wants to hand off a task to a fresh Claude session in its own pane. Do NOT use this for relaying prompts to an EXISTING agent pane — that is zellij-relay-prompt."
---

# Open a Claude Code pane in zellij

Create a new zellij pane and start a fresh Claude Code session in it. The pane
opens next to the current one, inherits the working directory, and is
automatically named (e.g. `claude: myproject`).

`scripts/` paths are relative to this skill's directory.

## Workflow

1. **Open the pane:**
   ```bash
   bash scripts/new-pane.sh [direction] [cwd] [initial-prompt]
   ```
   - `direction` (optional): `right` (default), `left`, `up`, `down`
   - `cwd` (optional): working directory (defaults to current pane's cwd)
   - `initial-prompt` (optional): task to send to the new Claude session

   The script creates the pane, waits for the shell, types `claude` + Enter,
   names the pane, and outputs the new pane ID.

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
CLAUDE_INITIAL_PROMPT="Review the auth module" bash scripts/new-pane.sh
```

The prompt is written to a temp file and relayed via `write-chars`, so
backticks, `$`, quotes, and newlines all survive intact.

If you need reliable prompt delivery to an **existing** pane, use
`zellij-relay-prompt` instead — it's built for that.

## Custom Claude command

If the binary has a different name:
```bash
CLAUDE_CMD="claude-code" bash scripts/new-pane.sh
```

## Choosing between this skill and zellij-relay-prompt

| Situation | Use |
|-----------|-----|
| Need a brand-new Claude session in its own pane | `zellij-claude-pane` |
| Want to hand off a task to an **existing** agent pane | `zellij-relay-prompt` |
| Not sure if a pane exists yet | `zellij-claude-pane` (create one), then relay |

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/new-pane.sh` | Create a new pane, start Claude Code, optionally send a prompt |

See `zellij-io.md` for raw zellij command semantics.
