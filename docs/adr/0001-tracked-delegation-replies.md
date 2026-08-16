# Use Tracked Reply Routes for Delegations

Tracked delegations use a per-request private route with a durable JSON reply
record and a FIFO wake signal. The sending Agent runs one background Reply
waiter and resumes from its structured stdout; receiving Agents no longer type
completion messages into zellij panes. The route is the source of truth so
waiter restarts, cancellation, deadlines, and concurrent requests have
first-writer-wins semantics without pane polling.

## Status

Accepted

## Consequences

The protocol is POSIX-oriented and replaces the old `notify-complete.sh`
interface. Fire-and-forget remains an explicit mode with no reply route.
