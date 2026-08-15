# Zellij Agent Skills

Skills for coordinating interactive coding agents in zellij. The vocabulary
distinguishes the generic agent runtime from any particular agent product.

## Language

**Agent pane**:
A zellij pane whose primary process is an interactive coding agent.
_Avoid_: Claude pane, worker pane

**Agent command**:
The explicit command that starts the coding agent in an Agent pane.
_Avoid_: Claude command

**Launch diagnostic**:
An actionable result from the pane-launch script that states whether it can
start an Agent pane and what input is needed when it cannot.
_Avoid_: generic error, setup hint

**Launch configuration**:
The user-supplied environment values used to create an Agent pane, including
both reusable Agent settings and optional one-time task settings.
_Avoid_: setup script, automatic configuration
