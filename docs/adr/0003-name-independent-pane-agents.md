# Name Independent Pane Agents Explicitly

Use `pane agent` for an independently running Agent launched in a zellij pane
to perform delegated work, and use `subagent` for same-session delegation. The
skill identifiers `zellij-pane-agent` and `configure-zellij-pane-agent` encode
that distinction; the old `zellij-agent-pane` names are not retained as aliases
because they make the pane sound like the Agent and blur the runtime boundary.

## Status

Accepted
