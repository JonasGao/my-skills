# Zellij Agent Skills

Skills for coordinating interactive coding agents in zellij. The vocabulary
distinguishes the generic agent runtime from any particular agent product.

## Language

**Pane agent**:
An independently running coding Agent launched in a zellij pane to perform
delegated work. It may use a different Agent product or session from the
delegating Agent; unlike a subagent, it is a separate runtime.
_Avoid_: Agent pane, agent pane, Claude pane, worker pane

**Developer-reviewer loop**:
A bounded collaboration cycle in which a reviewer delegates implementation to
a dedicated pane agent, reviews its work, and ends by delivering, cancelling,
or terminating the effort and releasing its owned resources.
_Avoid_: Agent session, review session

**Loop-owned pane agent**:
The pane agent created exclusively for one Developer-reviewer loop. It belongs
to that loop and is not reused by a later loop.
_Avoid_: shared pane agent, reusable developer pane

**Subagent**:
An Agent delegated within the same Agent session or tool runtime. It is an
independent task executor within that session, whereas a pane agent is a
separate zellij-launched runtime.
_Avoid_: pane agent when referring to same-session delegation

**Pane agent placement**:
The presentation of a new pane agent's zellij pane. It is either automatically
tiled by zellij or explicitly floating; directional placement is not part of
the model.
_Avoid_: Agent pane placement, pane direction, directional pane

**Agent command**:
The explicit command that starts the coding agent in a pane agent.
_Avoid_: Claude command

**Agent init file**:
An explicitly selected shell file sourced for an Agent launch to establish the
agent's startup environment. It is launch-scoped and is not an implicit shell
profile.
_Avoid_: bashrc, shell profile

**Launch diagnostic**:
An actionable result from the pane-launch script that states whether it can
start a pane agent and what input is needed when it cannot.
_Avoid_: generic error, setup hint

**Launch configuration**:
The user-supplied environment values used to create a pane agent, including
both reusable Agent settings and optional one-time task settings.
_Avoid_: setup script, automatic configuration

**Delegation reply**:
An atomically written terminal result for one Delegation request, containing a
status, summary, and a reference to the complete result. A receiving Agent can
produce `succeeded` or `failed`; cancellation and deadline outcomes come from
the sending side.
_Avoid_: completion notification, callback, pane input

**Delegation request**:
One task sent from a sending Agent to a receiving pane agent and identified by
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
unreachable pane agent is not itself a terminal status.
_Avoid_: done, completion notification

**Fire-and-forget delegation**:
An explicitly requested Delegation with no Reply route or Reply waiter; its
completion cannot trigger work in the sending Agent.
_Avoid_: untracked delegation, notification-only delegation
