---
name: zellij-dev-loop
description: "Create a developer agent in a new pane while you act as reviewer in a fix-review cycle. Manually trigger when user says: 'you review, let another agent develop', 'dev-review loop', 'you only review', or explicitly wants developer/reviewer role separation."
---

# Developer-Reviewer Loop

Create a parallel agent to implement code while you review it, iterating through a
review-fix cycle until the code is complete, reviewed, and its pane is released.

**Role separation:**
- **You (reviewer)**: Review code, identify issues, send feedback. Do NOT write code.
- **Developer agent**: Implements code, fixes issues. Runs in a separate pane.

This separation catches more bugs through independent review and lets each agent
focus on its strength.

## Workflow

### 1. Spawn the developer agent

Every new Developer-reviewer loop starts with a fresh Loop-owned pane agent.
Invoke the `zellij-pane-agent` skill to create it:

```
Use zellij-pane-agent to open a new pane agent in this directory.
```

The skill creates the pane and starts the Agent command selected by the user. If the command is absent, its script returns an actionable diagnostic; ask the user for the listed values, then retry the script once. Save the new pane ID (e.g., `terminal_42`) as the ID owned by this loop. Use that exact ID for relaying and teardown.

Wait for the session to load (~5-10 seconds) before sending tasks.

### 2. Send the initial task

Create a tracked delegation through `zellij-relay-prompt`, then send the
implementation task:

```
Create a Reply route and start its Reply waiter as a background task. Use
zellij-relay-prompt to send this task to pane <developer-pane-id>:

Implement a user authentication module with:
- JWT token generation
- Password hashing with bcrypt
- Login/logout endpoints

```

The staged task must include the generated `reply-to-request.py` command. The
reviewer Agent remains free to inspect other work while the Reply waiter runs.

### 3. Consume the waiter result

When the background Reply waiter exits, consume its JSON stdout. Do not poll the
developer pane or use `dump-screen` to infer completion. A `failed` result is a
valid terminal result and should be reviewed as such; infrastructure errors
from the waiter require restarting it with the same request ID.

### 4. Review the implemented code

Now review what the developer produced. **Use the code-review skill** for structured
review:

```
/code-review
```

If code-review skill is not available, manually read the changed files and check:

- **Correctness**: Does it do what was requested?
- **Security**: Any vulnerabilities?
- **Edge cases**: Error handling, input validation.
- **Code quality**: Naming, structure, comments.

The code-review skill provides a systematic review process — rely on it when available.

### 5. If issues found → send fix requests

When you find problems, invoke `zellij-relay-prompt` to send fix requests:

```
Use zellij-relay-prompt to send this to pane <developer-pane-id>:

Fix the following issues:

1. Security vulnerability (auth.js:45): Use bcrypt.compare() instead of ==
2. Missing error handling (auth.js:28): Add try-catch around JWT sign
3. Hardcoded secret (auth.js:15): Load from JWT_SECRET env var

```

**Be specific**: Include file paths, line numbers, and exact fixes needed. This lets the developer act quickly.

### 6. Loop until clean

Repeat steps 3-5 until the review finds no issues:

1. Consume the Reply waiter result
2. Review the fixes
3. If issues remain → send fix request
4. If clean and the required verification passed → teardown and deliver

If a `failed` result can still be repaired, keep the pane and send a new tracked
fix request. A failure ends the loop only when the effort is blocked or stopped.

### 7. Teardown the loop

Always teardown the Loop-owned pane agent when the work is deliverable, the user
cancels or stops it, or the effort is blocked and this loop is ending. Work is
deliverable when it meets the requested scope, the final review is clean, and
the required verification has passed. Do not wait for an additional user
confirmation.

Use only the pane ID saved in step 1:

```bash
bash scripts/close-pane.sh <developer-pane-id>
```

Run teardown in this order:

1. Invoke `close-pane.sh` once.
2. If a Delegation request is still active, invoke its generated
   `cancel-reply.py` command. If a reply won the race, its existing Terminal
   status remains authoritative.
3. Consume the Reply waiter result so no waiter remains active.
4. Report `CLOSED` or `CLOSE_FAILED` with the pane ID. A close failure does not
   change whether completed code is deliverable, but it must be visible to the
   user.

On successful delivery, close the pane before the final user response. Once
teardown starts, retire its pane ID even if closing fails. A later development
or fix request starts a new loop and invokes `zellij-pane-agent` for a fresh
pane. Never rediscover or reuse a pane from a completed or terminated loop.

#### Close script interface

```bash
bash scripts/close-pane.sh <terminal-pane-id>
```

- Accepts a numeric ID or `terminal_<number>` returned by pane creation.
- Refuses to close the current reviewer pane identified by `$ZELLIJ_PANE_ID`.
- Calls `zellij action close-pane` for that exact ID without discovering other
  panes, terminating the pane agent process with its pane. Zellij treats an
  absent pane as a successful no-op.
- Prints `CLOSED: pane=<id>` and exits `0` when the close action succeeds.
- Prints `CLOSE_FAILED: ...` and exits non-zero for invalid input, self-close,
  or a zellij error.

## Best Practices

**For the reviewer (you):**
- Stay objective. Your job is to find problems, not to rewrite the code yourself.
- Be specific in feedback. "Fix the bug" is unhelpful; "Line 45: use bcrypt.compare instead of ==" is actionable.
- Prioritize issues. Critical bugs > style issues. Don't nitpick trivialities.
- Use the code review skill if available — it provides structured review.

**For the developer (via your prompts):**
- Provide clear, specific task descriptions.
- Include acceptance criteria when relevant.
- Ask the developer to submit a structured Delegation reply on completion.

**Communication pattern:**
- Always include the generated reply command in tracked prompts.
- Put the short completion summary in the reply summary file and place longer
  output in the optional result file.

## Example Session

**User**: "Create a REST API for a todo list. You review, let another agent implement."

**You (reviewer)**:
1. Invoke `zellij-pane-agent` → creates pane agent `terminal_15`
2. Create a Reply route, start its waiter, and invoke `zellij-relay-prompt` → sends task "Implement a REST API for a todo list with CRUD endpoints..."
3. The waiter returns a `succeeded` JSON result with the API summary
4. Invoke `/code-review` on the changes → find 3 issues
5. Create a new tracked request and invoke `zellij-relay-prompt` → sends "Fix these 3 issues..."
6. The new waiter returns a `succeeded` JSON result
7. Review fixes → find 1 remaining issue
8. Create another tracked request and invoke `zellij-relay-prompt` → sends "Fix validation in POST /todos..."
9. The waiter returns a `succeeded` JSON result
10. Review and verification → clean
11. Invoke `scripts/close-pane.sh terminal_15` → `CLOSED: pane=terminal_15`
12. Inform user: "Implementation complete and reviewed. Developer pane `terminal_15` closed."

## When to use this skill

- User explicitly asks for review/implementation separation
- Complex feature where independent review adds value
- User wants to learn by watching another agent implement
- Code quality is critical (security, production systems)
- You need to parallelize: review one feature while developer implements another

## Dependencies

This skill orchestrates other skills:

- **zellij-pane-agent**: Creates the developer pane agent (invoke via Skill tool)
- **zellij-relay-prompt**: Relays prompts to the developer (invoke via Skill tool)
- **code-review**: Reviews implemented code (invoke via `/code-review`)

Use dependency skills for launch, relay, and review. Use this skill's
`scripts/close-pane.sh` only for teardown of the pane ID created by this loop.
