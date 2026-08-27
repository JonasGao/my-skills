# Task-Document Retention Mechanisms

Date: 2026-08-16

## Scope and Method

This review covers the four active repository skills, their current scripts and
supporting agent documentation. The two `*-workspace/` directories are ignored
evaluation artifacts rather than active skills; they are covered separately
below. A direct match means that a task is materialized as a file and the
receiving Agent is explicitly told to read the file and execute its contents.
Long-task documents are retained in the system temporary directory for immediate
debugging; script-owned cleanup of a staging file is recorded separately because
it does not require the target Agent to act.

Primary sources were the current `SKILL.md` contracts and their implementation
scripts. The ignored-workspace classification is based on the
[`*-workspace/` ignore rule](../../.gitignore#L1-L4) and the absence of their
files from `HEAD`'s tracked file list.

## Findings

| Surface | Match | Trigger | Target-facing instruction | Cleanup owner |
| --- | --- | --- | --- | --- |
| `zellij-pane-agent` | Direct | An initial prompt is supplied, the ready mark is found, and the prompt exceeds 2,000 **bytes** | `Read <file> and execute its complete task.` | System temporary-directory cleanup |
| `zellij-relay-prompt` | Direct | A staged relay prompt exceeds 2,000 Python string **characters** | `请读取 <file> 并完整执行其中的任务。` | System temporary-directory cleanup |
| `zellij-dev-loop` | Indirect | Its initial or fix task is sent through either skill above and crosses that skill's threshold | No instruction of its own; it delegates delivery | System temporary-directory cleanup when the delegated long-prompt path is selected |
| `configure-zellij-pane-agent` | No direct match | N/A | It only collects and displays `ZAP_*` configuration | N/A |

### 1. New pane agent: `zellij-pane-agent`

The skill contract says that prompts over 2,000 bytes are stored as unique
Markdown files in the system temporary directory. The Agent receives a pointer,
while the file remains available for immediate debugging until the system cleans
it up. [Skill contract](../../zellij-pane-agent/SKILL.md#L106-L114)

The implementation stages every initial prompt with Python's system-temporary
file API. When the byte count from `wc -c` is greater than 2,000, it relays only
this pointer into the new pane:

```text
Read <system-temp>/zellij-agent-init-<pane-id>-<unique>.md and execute its complete task.
```

Source: [`new-pane.sh`](../../zellij-pane-agent/scripts/new-pane.sh#L313-L342).

This path is available only after the new pane starts and displays
`ZAP_READY_MARK`; the launcher refuses an initial prompt without that mark.
[Readiness contract](../../zellij-pane-agent/SKILL.md#L106-L109)

For a prompt at or below 2,000 bytes, the launcher reads the staging file
itself, relays its contents directly, and runs `rm -f` itself. The target Agent
does not receive a file pointer and has no deletion responsibility.
[Short-prompt implementation](../../zellij-pane-agent/scripts/new-pane.sh#L343-L368)

### 2. Existing pane agent: `zellij-relay-prompt`

The relay contract describes the same pattern for long prompts: it writes the
complete task to a unique Markdown file in the system temporary directory,
tells the receiver to read it, and deliberately leaves it for system cleanup.
[Relay contract](../../zellij-relay-prompt/SKILL.md#L126-L133)

`relay.py` selects this path when `len(content) > 2000`, writes the long file,
and sends the following Chinese pointer through `write-chars`:

```text
请读取 <system-temp>/zellij-relay-long-<pane>-<unique>.md 并完整执行其中的任务。
```

Source: [`relay.py`](../../zellij-relay-prompt/scripts/relay.py#L171-L207).

On a successful relay, the script deletes the original staged prompt in the
system temporary directory by default, not the retained long task document.
[Cleanup implementation](../../zellij-relay-prompt/scripts/relay.py#L209-L215)

### 3. Developer-reviewer loop: `zellij-dev-loop`

This skill has no task-file implementation. It creates a pane through
`zellij-pane-agent` and sends initial and follow-up tasks through
`zellij-relay-prompt`, so it inherits both direct mechanisms when the delegated
prompt is long enough. [Initial-task workflow](../../zellij-dev-loop/SKILL.md#L20-L47)
[Fix-request workflow](../../zellij-dev-loop/SKILL.md#L73-L85)

### 4. Skills and documentation without the mechanism

- `configure-zellij-pane-agent` only asks for configuration values and emits a
  display-only shell block; it does not create a pane or write a task file.
  [Source](../../configure-zellij-pane-agent/SKILL.md#L8-L12)
- The zellij I/O references document pane commands only. Neither introduces a
  target-read-and-retain task document.
- `docs/agents/domain.md` requires agents to read context and ADR files before
  exploration, while `docs/agents/issue-tracker.md` tells agents to read a
  referenced ticket. Neither asks the reader to delete those documents.
  [Domain docs](../agents/domain.md#L5-L11) [Issue tracker](../agents/issue-tracker.md#L17-L19)
- `CLAUDE.md` similarly requires reading `AGENTS.md` first, without deletion.
  [Source](../../CLAUDE.md#L1-L3)

## Differences and Operational Consequences

1. **Delivery context:** `zellij-pane-agent` applies to a new pane's optional
   initial task; `zellij-relay-prompt` applies to a task delivered to an
   existing pane.
2. **Threshold unit:** the launcher compares byte count (`wc -c`), while
   `relay.py` compares Python character count (`len(content)`). Multibyte text
   can therefore take different paths at the same visible length.
3. **Temporary filename:** both paths use a unique Markdown file in the system
   temporary directory. This prevents same-pane relays from overwriting task
   documents before their receiver consumes them.
4. **Retention:** neither path asks the target to delete the file or verifies
   that it was read. A long-task document is intentionally available until the
   operating system's temporary-file policy removes it.
5. **Short-prompt contrast:** both mechanisms retain a staging file briefly,
   but that file is consumed and deleted by the sender-side script. Those paths
   are not target-read-and-delete mechanisms.

## Ignored Evaluation Copies and History

The ignored evaluation workspaces contain source snapshots, so a broad text
search finds additional copies of the pattern. They are evidence of prior or
evaluated behavior, not additional active mechanisms:

| Ignored copy | Contents | Relationship to active findings |
| --- | --- | --- |
| `zellij-claude-pane-workspace/skill-snapshot/` and `skill-new/` | A retired `zellij-claude-pane` implementation sends the Chinese read/delete pointer for prompts over 2,000 bytes and leaves a task document in `/tmp`. [Snapshot](../../zellij-claude-pane-workspace/skill-snapshot/zellij-claude-pane/scripts/new-pane.sh#L222-L272) [Evaluated version](../../zellij-claude-pane-workspace/skill-new/zellij-claude-pane/SKILL.md#L56-L60) | Historical predecessor of `zellij-pane-agent`, not active in this checkout. |
| `zellij-relay-prompt-workspace/skill-snapshot/` and `skill-new/` | Copies of the older relay handoff, including the fixed `/tmp` path and Chinese read/delete pointer. [Snapshot](../../zellij-relay-prompt-workspace/skill-snapshot/zellij-relay-prompt/scripts/relay.py#L129-L173) [Evaluated version](../../zellij-relay-prompt-workspace/skill-new/zellij-relay-prompt/SKILL.md#L126-L133) | Evaluation copies, not a distinct active path. |

The generic `zellij-agent-pane` (now `zellij-pane-agent`) replaced the tracked
`zellij-claude-pane` in commit `41d47c9`. The historical implementation has the same long-prompt
read/execute/delete design but is not an active skill in the current tree.
