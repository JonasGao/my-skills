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

   The script automatically inherits the current process environment. Treat
   that environment as the launch configuration; do not inspect or print it.
   The only permitted override is an exact `ZAP_*` value the current user
   explicitly supplied for this launch. Do not use shell profiles, prior
   conversations, session logs, files, pane contents, or memory as a
   configuration source.

2. Handle its exit status exactly:

   - `0`: report the pane ID. Use `zellij-relay-prompt` for later interaction.
   - `2`: parse the `ACTION_REQUIRED: missing=...` line. Ask the current user
     only for those listed values, use their answers for the second invocation,
     then run the script exactly once more.
   - `1`: show the `START_FAILED` diagnostic to the user and stop. Do not guess
     configuration or make another attempt.

When using `zellij-relay-prompt` after pane creation, omit `initial-prompt`.
That path does not require `ZAP_READY_MARK`.

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
| `ZAP_DEBUG` | `0` | Set to `1` to emit launch and ready-wait diagnostics to stderr. |

`ZAP_AGENT_CMD` and `ZAP_AGENT_ENV` are interpreted by `bash -c`. The inherited
process environment is authoritative. Use a current-user value only as an
explicit per-launch override; pass it unchanged. Never infer a command or
recover a value from historical material.

Set `ZAP_DEBUG=1` when investigating a launch that appears to wait. Its stderr
records pane-creation boundaries and every ready-mark probe without printing
the Agent command, Agent environment, ready-mark text, or prompt. A final
`ready probe started` line with no corresponding `finished` line means the
underlying `zellij action dump-screen` call is blocking.

### Results

- `0`: Prints the new pane ID. zellij accepted the command and created the
  pane, and the Agent command remained running through the one-second startup
  check; with an initial prompt, the ready mark was found and the prompt was
  sent.
- `2`: Prints `ACTION_REQUIRED: missing=<comma-separated ZAP_* names>` to
  stderr, followed by descriptions of those inputs. The calling Agent requests
  exactly those names before its one retry.
- `1`: Prints a `START_FAILED` diagnostic to stderr. It covers invalid inputs,
  zellij failures, and failed prompt delivery.

Startup first requires `zellij action new-pane` to create the pane. The pane's
shell then reports an exit during its first second: the script returns
`START_FAILED` with that exit status (including `127` for a missing command).
An interactive Agent that remains running through that window is considered
started. `dump-screen` is used only to match `ZAP_READY_MARK` before input is
relayed; it is not a startup-success check.

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
