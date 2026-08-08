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

Invoke the `zellij-claude-pane` skill to create a new pane:

```
Use zellij-claude-pane to open a new pane in this directory.
```

The skill creates the pane and starts a fresh Claude Code session. It outputs the new pane ID (e.g., `terminal_42`) — save it for relaying prompts.

Wait for the session to load (~5-10 seconds) before sending tasks.

### 2. Send the initial task

Invoke the `zellij-relay-prompt` skill to send the implementation task:

```
Use zellij-relay-prompt to send this task to pane <developer-pane-id>:

Implement a user authentication module with:
- JWT token generation
- Password hashing with bcrypt
- Login/logout endpoints

When done, notify me.
```

The zellij-relay-prompt skill handles staging the prompt and relaying it to the target pane. Always include a completion notification request so the developer signals when finished.

### 3. Wait for completion notification

The developer will send a notification when finished. Wait for this signal.

If you don't receive a notification after a reasonable time, check the developer pane status using `zellij action dump-screen`.

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

When done, notify me.
```

**Be specific**: Include file paths, line numbers, and exact fixes needed. This lets the developer act quickly.

### 6. Loop until clean

Repeat steps 3-5 until the review finds no issues:

1. Wait for developer notification
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
- Ask the developer to notify you on completion.

**Communication pattern:**
- Always request completion notification in your prompts to the developer.
- Include a brief summary in the notification (e.g., "done: auth module ready").

## Example Session

**User**: "Create a REST API for a todo list. You review, let another agent implement."

**You (reviewer)**:
1. Invoke `zellij-claude-pane` → creates pane `terminal_15`
2. Invoke `zellij-relay-prompt` → sends task "Implement a REST API for a todo list with CRUD endpoints..."
3. Developer notifies: "done: API implemented"
4. Invoke `/code-review` on the changes → find 3 issues
5. Invoke `zellij-relay-prompt` → sends "Fix these 3 issues..."
6. Developer notifies: "done: issues fixed"
7. Review fixes → find 1 remaining issue
8. Invoke `zellij-relay-prompt` → sends "Fix validation in POST /todos..."
9. Developer notifies: "done: validation fixed"
10. Review → clean. Inform user: "Implementation complete and reviewed."

## When to use this skill

- User explicitly asks for review/implementation separation
- Complex feature where independent review adds value
- User wants to learn by watching another agent implement
- Code quality is critical (security, production systems)
- You need to parallelize: review one feature while developer implements another

## Dependencies

This skill orchestrates other skills:

- **zellij-claude-pane**: Creates the developer pane (invoke via Skill tool)
- **zellij-relay-prompt**: Relays prompts to the developer (invoke via Skill tool)
- **code-review**: Reviews implemented code (invoke via `/code-review`)

All coordination happens through skill invocation — do not call the underlying scripts directly.