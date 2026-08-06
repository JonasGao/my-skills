# Zellij command reference (for relaying prompts)

Loaded on demand when you need the raw command semantics behind the relay.
For pane-creation commands (new-pane, rename, close), see
`zellij-claude-pane/zellij-io.md`.

## Pane ID formats

Zellij accepts both numeric (`42`) and string (`terminal_42`, `plugin_7`) ids
interchangeably. `list-panes --json` returns numeric ids; `new-pane` outputs
the string format. Scripts in both skills normalize both.

## List panes

```bash
zellij action list-panes --json
```

Each pane has `id`, `title`, `pane_command`, `pane_cwd`, `is_plugin`, `is_focused`.
`pane_command` is the reliable way to tell a coding-agent pane (`claude`, `codex`,
`opencode`, ...) from a plain shell (`/bin/bash`); titles are unreliable (task
text / spinner / app name).

## Dump screen

Viewport only:

```bash
zellij action dump-screen --pane-id <id> --path /tmp/out.txt
```

With full scrollback:

```bash
zellij action dump-screen --full --pane-id <id> --path /tmp/out.txt
```

## Send text into a pane

- `zellij action write --pane-id <id>` writes raw bytes - does **not** reach a
  coding agent's TUI input box. Don't use it for relaying.
- `zellij action write-chars --pane-id <id> "text"` simulates typing - **does** enter
  the input box. Use this. Handles backticks, `$`, quotes, newlines literally.

`write-chars` takes a single string argument, so for file contents use Python
(`scripts/relay.py` already does) to avoid the shell re-interpreting backticks/`$`.

## Send keys

```bash
zellij action send-keys --pane-id <id> "Enter"
zellij action send-keys --pane-id <id> "Ctrl u"   # clear the input line
```

`"Escape"` is not supported by zellij's send-keys.
