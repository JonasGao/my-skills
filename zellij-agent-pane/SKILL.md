---
name: zellij-agent-pane
description: "Create a new zellij pane and start a configured coding agent in it. Use when the user wants a fresh parallel agent pane, asks to spawn an agent in zellij, or delegates work to a new agent session. Do NOT use this for relaying a prompt to an existing pane; use zellij-relay-prompt."
---

# Open an Agent Pane

Create a new zellij pane through `scripts/new-pane.sh`. It starts only the
Agent command supplied by the user; it has no product-specific default. A
tracked delegation is delivered after the pane exists through
`zellij-relay-prompt`, so its Reply route and Reply waiter are ready before the
task is sent.

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

   - `0`: report the pane ID. Use `zellij-relay-prompt` for later interaction;
     for a tracked delegation, create its Reply route and start its Reply
     waiter before relaying the task.
   - `2`: parse the `ACTION_REQUIRED: missing=...` line. Ask the current user
     only for those listed values, use their answers for the second invocation,
     then run the script exactly once more.
   - `1`: show the `START_FAILED` diagnostic to the user and stop. Do not guess
     configuration or make another attempt.

When using `zellij-relay-prompt` after pane creation, omit `initial-prompt`.
That path does not require `ZAP_READY_MARK` and is the required path for a
tracked delegation. Supplying `initial-prompt` is the explicit
fire-and-forget path; it has no Reply route or Reply waiter.

For example, after the user supplies the Agent command and ready mark:

This direct initial-prompt example is fire-and-forget. Use the tracked
delegation workflow below when the sender must receive a result.

```bash
ZAP_AGENT_CMD="codex --full-auto" \
ZAP_AGENT_INIT="$HOME/.config/my-agent/init.sh" \
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
| `ZAP_AGENT_INIT` | none | Optional shell file sourced once before the Agent command; relative paths resolve from the target `cwd`. |
| `ZAP_INITIAL_PROMPT` | none | Fallback initial prompt. |
| `ZAP_FLOATING` | `0` | Set to `1` to create a floating pane. |
| `ZAP_READY_MARK` | none | Required literal screen mark when an initial prompt is supplied. |
| `ZAP_READY_TIMEOUT` | `30` | Positive seconds to wait for the ready mark. |
| `ZAP_DEBUG` | `0` | Set to `1` to emit launch and ready-wait diagnostics to stderr. |

`ZAP_AGENT_CMD` and `ZAP_AGENT_ENV` are interpreted by Bash. If
`ZAP_AGENT_INIT` is set, the file is sourced once in the same Bash process
before the Agent command is evaluated, so exported variables and shell
functions from the file are available to the command. `ZAP_AGENT_ENV` is
evaluated after the init file and therefore acts as the explicit per-launch
override for the Agent command. The inherited process environment is
authoritative. Use a current-user value only as an explicit per-launch
override; pass it unchanged. Never infer a command or recover a value from
historical material.

`ZAP_AGENT_INIT` is not an implicit `~/.bashrc` or `BASH_ENV` hook. It must name
an existing, readable file; a missing file or a non-zero status while sourcing
it fails the launch. The file is sourced non-interactively, so aliases are not
part of the Agent launch contract.

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
Direct initial prompts are fire-and-forget. A tracked delegation must be
staged and sent through `zellij-relay-prompt` only after its Reply waiter has
started.

Prompts over 2,000 bytes are written as uniquely named Markdown files in the
system temporary directory. The Agent receives a short pointer to read and
execute the task; the file is retained for debugging until the system cleans it
up. Short prompts are relayed directly and their temporary files are removed by
the script.

## Follow-Up Interaction

For a tracked delegation, use `zellij-relay-prompt` after the pane exists:

1. Create a Reply route with
   `<abs-path-to-zellij-relay-prompt>/scripts/create-reply-route.py`.
2. Start `<abs-path-to-zellij-relay-prompt>/scripts/wait-for-reply.py
   <request-id>` as a background task owned by the sending Agent. The default
   wait is unlimited.
3. Include the generated reply instructions in the staged task and relay it.
4. Let the Agent runtime consume the waiter's JSON stdout when it exits.

Do not append the retired `notify-complete.sh` completion-notice snippet and do
not poll the target pane for progress. Use the explicit fire-and-forget path
only when no reply is needed.
