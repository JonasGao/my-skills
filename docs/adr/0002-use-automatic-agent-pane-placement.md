# Use Automatic Agent Pane Placement

Agent pane launches use zellij's automatic tiled placement, while floating
placement remains an explicit launch configuration. We removed directional
placement from the launch interface because zellij can return a pane ID without
registering the pane when a directional launch targets a detached session;
branching on client attachment would make otherwise identical launches behave
differently and would preserve an unreliable contract.

## Status

Accepted

## Consequences

Existing callers must remove the positional direction argument. Calls that
still begin with `right`, `down`, `left`, or `up` fail with a targeted migration
diagnostic instead of being interpreted as a working directory.
