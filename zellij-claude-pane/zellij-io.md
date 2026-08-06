# Zellij command reference (for pane management)

Loaded on demand when you need the raw command semantics. For relay-specific
details (stale-id guards, multi-pane coordination), see zellij-relay-prompt's
`zellij-io.md`.

## Pane ID formats

Zellij accepts both numeric (`42`) and string (`terminal_42`, `plugin_7`) ids
interchangeably. `list-panes --json` returns numeric ids; `new-pane` outputs
the string format. Scripts in this skill normalize both.

## Create a new pane

```bash
zellij action new-pane --direction right --cwd /path/to/dir
zellij action new-pane --floating --cwd /path/to/dir
```

Direction: `right`, `down` (zellij only supports these two). The new pane
becomes focused. `new-pane` prints the created pane ID to stdout (e.g.
`terminal_42`) — always capture this output rather than inferring from
`list-panes` (floating panes don't appear there).

## List panes

```bash
zellij action list-panes --json
```

Each pane has `id`, `title`, `pane_command`, `pane_cwd`, `is_plugin`,
`is_floating`, `is_focused`. Note: `is_floating==true` panes may not appear
in list-panes on all zellij versions.

## Send text into a pane

- `zellij action write --pane-id <id>` writes raw bytes — does **not** reach a
  coding agent's TUI input box. Don't use it for sending commands.
- `zellij action write-chars --pane-id <id> "text"` simulates typing — **does**
  enter the input box. Use this. Handles backticks, `$`, quotes, newlines
  literally.

`write-chars` takes a single string argument. For file contents, use Python
to avoid the shell re-interpreting backticks/`$`/newlines — the same approach
used by `zellij-relay-prompt/scripts/relay.py`. Note: `write-chars` may
truncate content beyond ~2KB.

## Send keys

```bash
zellij action send-keys --pane-id <id> "Enter"
zellij action send-keys --pane-id <id> "Ctrl u"   # clear the input line
```

`"Escape"` is not supported by zellij's send-keys.

## Rename a pane

```bash
zellij action rename-pane --pane-id <id> "claude: myproject"
```

## Close / kill a pane

```bash
zellij action close-pane --pane-id <id>
```

## Dump screen

Viewport only:
```bash
zellij action dump-screen --pane-id <id> --path /tmp/out.txt
```

With full scrollback:
```bash
zellij action dump-screen --full --pane-id <id> --path /tmp/out.txt
```
