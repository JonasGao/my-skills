---
name: zellij-agent-pane
description: "Create a new zellij pane and start a configured coding agent in it. Use when the user wants a fresh parallel agent pane, asks to spawn an agent in zellij, or delegates work to a new agent session. Do NOT use this for relaying a prompt to an existing pane; use zellij-relay-prompt."
---

# Open an Agent Pane

Create a new zellij pane through `scripts/new-pane.sh`. It starts only the
Agent command supplied by the user; it has no product-specific default.

`scripts/` paths are relative to this skill directory. The script interface
below is authoritative. Do not inspect the script unless it must be changed.

## Two-Stage Launch

1. Run the script once with the requested direction, working directory, and
   optional initial prompt.

   ```bash
   bash scripts/new-pane.sh [direction] [cwd] [initial-prompt]
   ```

2. Handle its exit status exactly:

   - `0`: report the pane ID. Use `zellij-relay-prompt` for later interaction.
   - `2`: read every `ACTION_REQUIRED` line. Ask the current user only for the
     listed values, set the returned `ZAP_*` variables, then run the script
     exactly once more.
   - `1`: show the `START_FAILED` diagnostic to the user and stop. Do not guess
     configuration or make another attempt.

For example, after the user supplies the Agent command and ready mark:

```bash
ZAP_AGENT_CMD="codex --full-auto" \
ZAP_READY_MARK="›" \
bash scripts/new-pane.sh right /path/to/project "Review the auth module"
```

## Script Interface

### Arguments

```bash
bash scripts/new-pane.sh [direction] [cwd] [initial-prompt]
```

- `direction`: `right` (default) or `down`; `left` and `up` fall back to
  `right`.
- `cwd`: working directory, defaulting to the current pane's directory.
- `initial-prompt`: optional task to send after the Agent displays its ready
  mark. It overrides `ZAP_INITIAL_PROMPT`.

### Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `ZAP_AGENT_CMD` | none | Required command, with any arguments, that starts the Agent. |
| `ZAP_AGENT_ENV` | none | Optional shell environment assignments prepended to the Agent command. |
| `ZAP_INITIAL_PROMPT` | none | Fallback initial prompt. |
| `ZAP_FLOATING` | `0` | Set to `1` to create a floating pane. |
| `ZAP_READY_MARK` | none | Required literal screen mark when an initial prompt is supplied. |
| `ZAP_READY_TIMEOUT` | `30` | Positive seconds to wait for the ready mark. |

`ZAP_AGENT_CMD` and `ZAP_AGENT_ENV` are interpreted by `bash -c`. Obtain their
values from the user and pass them unchanged; never infer or invent a command.

### Results

- `0`: Prints the new pane ID. zellij accepted the command and created the
  pane; with an initial prompt, the ready mark was found and the prompt was
  sent.
- `2`: Prints an `ACTION_REQUIRED` diagnostic to stderr. It names every input
  the calling Agent must request before its one retry.
- `1`: Prints a `START_FAILED` diagnostic to stderr. It covers invalid inputs,
  zellij failures, and failed prompt delivery.

Startup success is the exit status from `zellij action new-pane`: success means
zellij created the pane and accepted the Agent command. `dump-screen` is used
only to match `ZAP_READY_MARK` before input is relayed; it is not a startup-
success check.

### Prompt Delivery

The script refuses to send an initial prompt without `ZAP_READY_MARK`. This
prevents task text from being typed into a shell before the Agent is ready.

Prompts over 2,000 bytes are written to
`/tmp/zellij-agent-init-<pane-id>-<pid>.md`; the Agent receives a short pointer
and removes the file after reading it. Short prompts are relayed directly and
their temporary files are removed by the script.

## Follow-Up Interaction

Use `zellij-relay-prompt` after the pane exists. Append its completion-notice
snippet unless the user explicitly asks for fire-and-forget execution. Do not
poll the pane for progress.
