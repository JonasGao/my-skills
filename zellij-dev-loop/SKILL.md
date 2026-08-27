---
name: zellij-dev-loop
description: "Create a developer agent in a new pane while you act as reviewer in a fix-review cycle. Manually trigger when user says: 'you review, let another agent develop', 'dev-review loop', 'you only review', or explicitly wants developer/reviewer role separation."
---

# Developer-Reviewer Loop

Create a parallel agent to implement code while you review it, iterating through a
review-fix cycle until the code is complete and correct.

**Role separation:**
- **You (reviewer)**: Review code, identify issues, send feedback. Do NOT write code.
- **Developer agent**: Implements code, fixes issues. Runs in a separate pane.

This separation catches more bugs through independent review and lets each agent
focus on its strength.

## Workflow

### 1. Spawn the developer agent

Invoke the `zellij-pane-agent` skill to create a new pane agent:

```
Use zellij-pane-agent to open a new pane agent in this directory.
```

The skill creates the pane and starts the Agent command selected by the user. If the command is absent, its script returns an actionable diagnostic; ask the user for the listed values, then retry the script once. Save the new pane ID (e.g., `terminal_42`) for relaying prompts.

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
4. If clean → approve and close the loop

When code is satisfactory, inform the user: "The implementation is complete and reviewed.
No issues found."

### 7. (Optional) Close the developer pane

If no longer needed, close the developer pane using `zellij action close-pane`.

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
10. Review → clean. Inform user: "Implementation complete and reviewed."

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

All coordination happens through skill invocation — do not call the underlying scripts directly.
