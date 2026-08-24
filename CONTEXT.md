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

**Agent init file**:
An explicitly selected shell file sourced for an Agent launch to establish the
agent's startup environment. It is launch-scoped and is not an implicit shell
profile.
_Avoid_: bashrc, shell profile

**Launch diagnostic**:
An actionable result from the pane-launch script that states whether it can
start an Agent pane and what input is needed when it cannot.
_Avoid_: generic error, setup hint

**Launch configuration**:
The user-supplied environment values used to create an Agent pane, including
both reusable Agent settings and optional one-time task settings.
_Avoid_: setup script, automatic configuration

**Delegation reply**:
An atomically written terminal result for one Delegation request, containing a
status, summary, and a reference to the complete result. A receiving Agent can
produce `succeeded` or `failed`; cancellation and deadline outcomes come from
the sending side.
_Avoid_: completion notification, callback, pane input

**Delegation request**:
One task sent from a sending Agent to a receiving Agent pane and identified by
an opaque request ID. It can have at most one Terminal status, and the first
successfully recorded Terminal status is authoritative. The sending Agent can
cancel it at any point before that status exists.
_Avoid_: message, job

**Tracked delegation**:
A Delegation request with a Reply route and Reply waiter, whose terminal result
is delivered back to the sending Agent runtime.
_Avoid_: synchronous delegation, notification-only delegation

**Reply route**:
The private per-request channel owned by the sending Agent through which the
sending Agent receives exactly one Delegation reply.
_Avoid_: notification target, pane input, zellij channel

**Reply waiter**:
A per-request background task owned by the sending Agent that waits
indefinitely for an explicit terminal Delegation reply without blocking the
Agent's other work.
_Avoid_: polling loop, daemon, scheduler

**Terminal status**:
The explicit `succeeded`, `failed`, `cancelled`, or `timed_out` outcome of a
Delegation request. The default Reply waiter has no deadline, so `timed_out`
is only possible when the sender explicitly configures one; a missing or
unreachable Agent pane is not itself a terminal status.
_Avoid_: done, completion notification

**Fire-and-forget delegation**:
An explicitly requested Delegation with no Reply route or Reply waiter; its
completion cannot trigger work in the sending Agent.
_Avoid_: untracked delegation, notification-only delegation
