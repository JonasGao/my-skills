# Zellij command reference (for pane management)

Loaded on demand when you need the raw command semantics.

## Create a new pane

```bash
zellij action new-pane --direction right --cwd /path/to/dir
```

Direction: `left`, `right`, `up`, `down`. The new pane becomes focused.

## List panes

```bash
zellij action list-panes --json
```

Each pane has `id`, `title`, `pane_command`, `pane_cwd`, `is_plugin`, `is_focused`.

## Send text into a pane

- `zellij action write --pane-id <id>` writes raw bytes — does **not** reach a
  coding agent's TUI input box. Don't use it for sending commands.
- `zellij action write-chars --pane-id <id> "text"` simulates typing — **does**
  enter the input box. Use this. Handles backticks, `$`, quotes, newlines literally.

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

```bash
zellij action dump-screen --pane-id <id> --path /tmp/out.txt
```
