---
name: configure-zellij-agent-pane
description: Collect and display the environment configuration for a zellij Agent pane.
---

# Configure Zellij Agent Pane

Collect a Launch configuration for `zellij-agent-pane`. Ask the user for every
setting below, then display only the requested `export ZAP_*=...` lines.

Do not run a command, create a pane, modify a shell profile, write a config
file, or set environment variables in the current process.

## Required Collection

Ask these three questions in order. Do not infer values.

1. Ask for `ZAP_AGENT_CMD`, the complete command and arguments that start the
   user's coding Agent. This value is required.
2. Ask for `ZAP_AGENT_ENV`, the optional environment assignments that precede
   the Agent command. The user may provide it or explicitly choose no value.
   Preserve a value exactly as supplied, including sensitive values.
3. Ask whether to use a floating pane. Record `ZAP_FLOATING=1` for yes or
   `ZAP_FLOATING=0` for no.

## Optional Collection

After the required settings, explicitly present all remaining settings before
asking which ones the user wants to configure:

- `ZAP_INITIAL_PROMPT`: a one-time task to send when the Agent starts.
- `ZAP_READY_MARK`: the literal screen mark required to send that task safely.
- `ZAP_READY_TIMEOUT`: positive seconds to wait for the ready mark; the launch
  script uses `30` when this variable is omitted.
- `ZAP_DEBUG`: set to `1` to emit launch and ready-wait diagnostics to stderr;
  the script uses `0` when this variable is omitted.

Ask whether the user wants one-time prompt delivery.

- If no, omit all three optional variables from the final output.
- If yes, collect `ZAP_INITIAL_PROMPT` and `ZAP_READY_MARK`; both are required
  together. Then ask whether to set `ZAP_READY_TIMEOUT` or use the script's
  default of `30`.

Ask whether the user wants diagnostic logging. If yes, include
`ZAP_DEBUG=1`; otherwise omit it and use the script default of `0`.

## Output

Show a single POSIX-shell block containing every collected setting and no
unselected optional setting. Quote every value with single quotes. Within a
value, encode each literal single quote as `'"'"'` so the user can paste the
result unchanged.

```bash
export ZAP_AGENT_CMD='codex --full-auto'
export ZAP_AGENT_ENV='API_BASE=https://example.test'
export ZAP_FLOATING='0'
export ZAP_INITIAL_PROMPT='Review the auth module'
export ZAP_READY_MARK='>'
export ZAP_READY_TIMEOUT='45'
export ZAP_DEBUG='1'
```

State that this is a display-only result: the user chooses where to apply it.
The collection is complete only after every required setting is represented and
every optional setting was either emitted or explicitly declined.
