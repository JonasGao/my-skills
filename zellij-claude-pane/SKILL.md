---
name: zellij-claude-pane
description: "Create a new zellij pane and start a Claude Code session in it. Use whenever the user wants to spawn a parallel Claude Code instance in a new zellij pane — e.g. 'open a new claude pane', 'start claude in a new pane', 'spawn another claude', 'create a parallel claude session', 'new pane with claude', 'split pane and run claude', or when running multiple Claude Code instances side by side in zellij. Also use when the user wants to hand off a task to a fresh Claude session in its own pane. Do NOT use this for relaying prompts to an EXISTING agent pane — that is zellij-relay-prompt."
---

# Open a Claude Code pane in zellij

Create a new zellij pane and start a fresh Claude Code session in it. The pane
opens next to the current one, inherits the working directory, and is
automatically named (e.g. `claude: myproject`).

If the tiled layout is full, the script falls back to `--floating` automatically.

`scripts/` paths are relative to this skill's directory.

## 你不需要读这些脚本

`scripts/` 下的脚本是稳定的实现细节。本文件"脚本接口"一节给出的说明是**完整且权威的** —— 脚本只做那里描述的事,没有隐藏行为。直接按签名调用即可;打开脚本源码阅读只会浪费 token。如果某次你确实想核对,运行 `脚本 --help` 而不是读源码。

## 脚本接口

### `scripts/new-pane.sh`

```bash
bash scripts/new-pane.sh [direction] [cwd] [initial-prompt]
```
- **作用**: 在当前 tab 中创建一个新的 zellij pane,启动 Claude Code,并(可选)发送初始 prompt。
- **参数**:
  - `direction` (默认 `right`): 新 pane 的方向。`right`/`down` 原样使用;`left`/`up` 静默回退为 `right`;其他值 → 退出 1。
  - `cwd` (默认 `$(pwd)`,即当前 pane 的工作目录): 新 pane 的工作目录。目录不存在或无法访问 → 退出 1。
  - `initial-prompt` (默认 `${ZCP_INITIAL_PROMPT:-}`): 可选任务,会自动键入新 Claude 会话(尽力而为)。未提供时跳过提示发送。
- **环境变量**:
  - `ZCP_CLAUDE_CMD` (默认 `claude`): Claude Code 的可执行命令。
  - `ZCP_CLAUDE_ENV` (默认空): 拼到命令前的额外环境变量,例如 `ZCP_CLAUDE_ENV="ANTHROPIC_MODEL=sonnet DEBUG=1"`,会前置为 `ANTHROPIC_MODEL=sonnet DEBUG=1 claude`。
  - `ZCP_INITIAL_PROMPT` (默认空): 第 3 个位置参数未给时的回退 prompt。
  - `ZCP_FLOATING` (默认 `0`): 设为 `1` 跳过 tiled 尝试,直接用 `--floating`。
  - `ZCP_READY_MARK` (默认 `❯`): 轮询等待 Claude 启动完成时匹配的 prompt 字符。
  - `ZCP_READY_TIMEOUT` (默认 `30`): 等待 Claude 启动完成的最大秒数。
- **stdout**: 成功时输出新 pane ID(例如 `terminal_42`)到 stdout。可选 prompt 阶段还会输出以下状态行(同样到 stdout):`Claude Code ready in pane <id>.`、`Sent initial prompt to pane <id> (best-effort).`、`Sent pointer to <file> (prompt was N chars).`。
- **stderr / 退出码**:
  - 不在 zellij 会话内 → stderr 打印 `Error: not in a zellij session`,退出 1。
  - 非法 direction → stderr 打印 `Error: invalid direction 'X' — use right, down, left, or up`,退出 1。
  - cwd 不存在 → stderr 打印 `Error: directory 'X' does not exist`,退出 1。
  - cwd 无法访问 → stderr 打印 `Error: cannot access 'X'`,退出 1。
  - 无法解析当前 tab_id → stderr 打印 `Error: could not determine current tab ID`,退出 1。
  - 提供了 initial-prompt 但 `python3` 不可用 → stderr 打印 `Error: python3 is required to relay the initial prompt`,退出 1。
  - tiled 尝试产生 ghost(布局已满)→ stderr 打印 `Warning: tiled pane <id|none> is a ghost (layout may be full), retrying with --floating...`,关闭该 ghost,转 floating。
  - floating 仍不可达 → stderr 打印 `Error: floating pane <id|none> is also unreachable`,退出 1。
  - `wait_for_claude_ready` 返回 2(Claude 命令找不到)→ stderr 打印 `Error: Claude command 'X' not found in pane <id>. The prompt was NOT sent — it would be executed as shell commands. Install Claude Code in the new pane or set ZCP_CLAUDE_CMD.`,退出 1。
  - `wait_for_claude_ready` 等待超时(返回 1)→ stderr 打印 `Warning: Claude Code did not show prompt within <N>s, sending anyway...`,继续发送 prompt,不退出。
  - python 转发的 write-chars 失败(短 prompt)→ stderr 打印 `Warning: python relay exited with code N (prompt may not have been sent)`,不退出。
- **关键行为**:
  - **tried-first → floating 回退**: 默认先尝试 tiled pane,通过 `pane_is_alive` 校验;若不存活(被识别为 ghost),先 `close-pane` 关闭它,再 fallback 到 `--floating`。`ZCP_FLOATING=1` 跳过 tiled,直接 floating。
  - **同 tab 创建**: 用 `ZELLIJ_PANE_ID` + `zellij action list-panes --json` 解析当前 tab_id,新 pane 通过 `--tab-id "$CURRENT_TAB_ID"` 创建在与调用者相同的 tab 中(避免新建到别的 tab)。
  - **pane 命名**: 新 pane 被重命名为 `claude: <cwd 的 basename>`,若 basename 为空或 cwd 是 `/` 则用 `root`。
  - **Claude 启动探测**: 调 `wait_for_claude_ready` 轮询 `dump-screen`,匹配 `ZCP_READY_MARK`(默认 `❯`)即认为就绪;若 stdout 中出现 `command not found`/`not found`/`no such file` 文本则返回 2(认为是 Claude 命令缺失)。
  - **长 prompt 处理(>2000 字节)**: 写入 `/tmp/zellij-claude-init-<pane-id>-<pid>.md`,然后通过 `zellij action write-chars` 发送一段短中文指针(`请读取 <file> 并完整执行其中的任务。完成后删除该文件。`)。文件**保留不删**,留给 Claude 自己读取。
  - **短 prompt 处理(≤2000 字节)**: 同样先写到 `/tmp/zellij-claude-init-<pane-id>-<pid>.md`,再用 python 读出该文件内容,通过 `write-chars` 直接发送;发送成功后**删除该临时文件**。
  - **python3 依赖**: 一旦提供了 initial-prompt(无论长短),必须可用 `python3`(用于 `Ctrl u` 清行 + `write-chars` + `Enter` 的发送协议);缺少则直接退出 1。
  - **临时文件残留**: 长 prompt 路径会留下 `/tmp/zellij-claude-init-<pane-id>-<pid>.md`,由目标 Claude 会话读取并自行删除(或人工清理);短 prompt 路径的同名文件会在成功后被脚本自动删除。
  - **可执行校验**: 内部 `pane_is_alive` 通过 `dump-screen` 连续探测(默认 3 次)验证 pane 真的渲染到屏幕,防止误把 ghost 当成正常 pane。

## Workflow

1. **Open the pane:**
   ```bash
   bash scripts/new-pane.sh [direction] [cwd] [initial-prompt]
   ```
   - `direction` (optional): `right` (default), `down`. zellij only supports
     `right`/`down`; `left`/`up` silently fall back to `right`.
   - `cwd` (optional): working directory (defaults to current pane's cwd)
   - `initial-prompt` (optional): task to send to the new Claude session

   The script tries tiled first, verifies the pane rendered, and falls back
   to `--floating` if the pane turns out to be a ghost (layout full). Outputs
   the new pane ID (e.g. `terminal_42`).

2. **Confirm** the new pane is running. Optionally verify:
   ```bash
   zellij action dump-screen --pane-id <id> --path /tmp/claude-verify.txt && tail -5 /tmp/claude-verify.txt
   ```

## Sending an initial prompt

Pass a task as the third argument to have it automatically typed into the new
Claude session (best-effort — Claude Code must have finished loading):

```bash
bash scripts/new-pane.sh right /home/god/myproject "Review the auth module for security issues"
```

Or via env:
```bash
ZCP_INITIAL_PROMPT="Review the auth module" bash scripts/new-pane.sh
```

**Long prompts (>2KB):** the script writes the prompt to
`/tmp/zellij-claude-init-<pane-id>.md` and sends a short pointer instead,
avoiding `write-chars` truncation. If the prompt is short, it's relayed
directly via `write-chars` with special characters preserved.

If you need reliable prompt delivery to an **existing** pane, use
`zellij-relay-prompt` instead — it's built for that.

## Follow-up interaction

After creating a pane, use `zellij-relay-prompt` for communication — **do not
poll the new pane's screen** (`dump-screen`) to check progress.

- **Default**: append a completion-notification snippet to the relayed prompt
  so the worker pane signals back when done. Wait for that notification, then
  continue.

  ```
  完成后运行: bash <abs-path-to-zellij-relay-prompt>/scripts/notify-complete.sh <your-pane-id> "done: <summary>"
  ```

- **If the user says "don't wait"** or "fire and forget": skip the
  notification snippet. The worker runs independently; the user will
  interact with it directly.

See `zellij-relay-prompt` SKILL.md for the full relay + notify workflow.

## Configuration

**Claude command priority** (highest to lowest):
1. User's request (e.g. "use `claude --dangerously-skip-permissions`") — pass via `ZCP_CLAUDE_CMD`
2. `ZCP_CLAUDE_CMD` env var
3. Default: `claude`

| Env var | Default | Purpose |
|---------|---------|---------|
| `ZCP_CLAUDE_CMD` | `claude` | Binary name for Claude Code |
| `ZCP_CLAUDE_ENV` | — | Extra env vars prepended to the command (e.g. `ANTHROPIC_MODEL=sonnet`) |
| `ZCP_INITIAL_PROMPT` | — | Fallback if no 3rd arg given |
| `ZCP_FLOATING` | `0` | Set to `1` to skip tiled attempt entirely |
| `ZCP_READY_MARK` | `❯` | Prompt glyph polled to detect Claude Code ready |
| `ZCP_READY_TIMEOUT` | `30` | Max seconds to wait for Claude Code startup |

## Choosing between this skill and zellij-relay-prompt

| Situation | Use |
|-----------|-----|
| Need a brand-new Claude session in its own pane | `zellij-claude-pane` |
| Want to hand off a task to an **existing** agent pane | `zellij-relay-prompt` |
| Create a new pane, then send follow-up tasks to it | `zellij-claude-pane` (create), then `zellij-relay-prompt` (interact) |

See `zellij-io.md` for raw zellij command semantics.
