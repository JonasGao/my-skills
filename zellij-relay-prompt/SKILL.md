---
name: zellij-relay-prompt
description: "Relay a prompt to another zellij pane running a coding agent (Claude Code, Codex, OpenCode, Aider, etc.), so that separate agent instance executes it. Use whenever the user wants to delegate or hand off a task to another coding-agent session in a different zellij pane - e.g. 'send this to the other pane', 'relay this prompt', 'ask the other agent to ...', 'delegate to pane X', 'run this in the retail-platform pane', or when coordinating work across multiple pane agents. Also use when the user refers to a zellij pane by id/title or wants one agent to drive another. Do NOT use to create a new pane; use zellij-pane-agent."
---

# Relay a prompt through zellij

Send a prompt to another zellij pane running a coding agent (Claude Code, Codex,
OpenCode, Aider, ...) so that pane runs it. This lets you parallelize work across
multiple agent sessions.

The relayed prompt is real - the target agent runs it. Only relay tasks you want
executed.

`scripts/` paths are relative to this skill's directory.

## If no pane agent exists yet

Use `zellij-pane-agent` to create one, then relay to it:
1. `bash <abs-path-to-zellij-pane-agent>/scripts/new-pane.sh` — creates a pane and starts the configured pane agent.
2. The new pane ID is printed; use it as the target for this skill's relay workflow.

## 你不需要读这些脚本

`scripts/` 下的脚本是稳定的实现细节。本文件"脚本接口"一节给出的说明是**完整且权威的** —— 脚本只做那里描述的事,没有隐藏行为。直接按签名调用即可;打开脚本源码阅读只会浪费 token。如果某次你确实想核对,运行 `脚本 --help` 而不是读源码。

## Workflow

1. **Find the target pane:**
   ```bash
   bash scripts/find-pane.sh
   ```
   Each line: `<pane-id>\t<title>\t<cwd>`. User named a pane - use it. One match -
   use it. Several - list them and ask. None - stop, tell the user to start a
   coding agent in another pane. (Override which commands count as agents via
   `$CODE_AGENT_RE`; default matches claude, codex, opencode, aider, gemini.)

2. **Choose a delegation mode.** For a tracked delegation, create a Reply route
   and request ID before staging the prompt:

   ```bash
   python3 scripts/create-reply-route.py
   ```

   Start the returned request's `wait-for-reply.py` command as a background task
   owned by the sending Agent. The waiter has no default deadline. For
   fire-and-forget, skip this step and do not include reply instructions.

3. **Stage the prompt** in the system temporary directory using a unique file
   for this relay. Use your file-writing tool, not `echo` - a file preserves
   backticks, `$`, quotes, and newlines. Include the route's generated reply
   instructions verbatim in a tracked task. Resolve the system temporary
   directory with `python3 -c 'import tempfile; print(tempfile.gettempdir())'`.

4. **Relay:**
   ```bash
   python3 scripts/relay.py <pane-id> <prompt-file>
   ```
   Reads the staged file, clears the target's input, types the prompt verbatim,
   and presses Enter. Prints chars sent or an error. Every staged file must be
   unique; the relay removes it after successful delivery.

5. **Confirm** the target pane ID to the user. Do not poll the pane for task
   progress. The sending Agent runtime receives completion through the waiter.
   A one-time delivery check is optional and does not indicate task progress:
   ```bash
   zellij action dump-screen --pane-id <pane-id> --path /tmp/relay-verify.txt && tail -15 /tmp/relay-verify.txt
   ```

## Reply workflow

`create-reply-route.py` prints JSON describing a new request and a ready-to-use
reply instruction. The sender starts `wait-for-reply.py <request-id>` in its
Agent runtime's background-task mechanism before relaying the prompt. The
receiver must submit exactly one terminal reply with `reply-to-request.py`:

```bash
python3 <abs-path-to-this-skill>/scripts/reply-to-request.py \
  <request-id> succeeded --summary-file <summary.md> --result-file <result.md>
```

The receiver may use `failed` instead of `succeeded`. The sender may run
`cancel-reply.py <request-id>` before a reply exists. An explicit waiter
deadline produces `timed_out`. The reply scripts do not inspect zellij or write
to any pane; the Reply route and its durable record are the transport.

## 脚本接口

每个脚本的"作用 / 参数 / 环境变量 / stdout / stderr & 退出码 / 关键行为"在这里给出
权威说明。脚本源码中没有任何上面没列出的隐藏行为。要快速核对,直接跑
`脚本 --help`。

### `scripts/find-pane.sh`

```bash
find-pane.sh [self-pane-id]
```
- **作用**: 列出当前 zellij 会话内**其他** coding-agent 窗格(自我排除)。
- **参数**: `self-pane-id`(可选,默认 `$ZELLIJ_PANE_ID`,空字符串则不过滤自身)。
- **环境变量**: `CODE_AGENT_RE`(默认 `claude|codex|opencode|aider|gemini`,
  一个用于匹配 `pane_command` 的 POSIX 扩展正则)。
- **stdout**: 命中时每行一条 `<pane-id>\t<title>\t<cwd>`(`cwd` 缺失时为 `-`);
  无命中时为空输出。
- **stderr / 退出码**: 退出 1 并打印到 stderr 的情况:不在 zellij 会话内、
  缺少 `jq`、`$CODE_AGENT_RE` 不是合法正则。
- **关键行为**: 依据 `pane_command` 匹配(不依据 title —— agents 会把 title
  设成任务文案或 spinner,不可靠);过滤掉插件窗格(`is_plugin == false`);按
  `self` 排除调用方所在的窗格;**Agents launched inside a shell** (即
  `pane_command == /bin/bash`) 不可见,要让 agent 成为 pane 的主命令才能被发现。

### `scripts/relay.py`

```bash
relay.py <pane-id> <prompt-file>
```
- **作用**: 把唯一 staged prompt 投递给目标 pane 上运行的 coding agent
  (清空输入 → write-chars 逐字输入 → Enter)。
- **参数**: `pane-id`(必填)和本次 relay 的唯一 `prompt-file`(必填)。
- **stdout**: 成功时打印 `Relayed N chars to pane <id> (from <file>).`。
- **stderr / 退出码**:
  - `0`:成功。
  - `1`:zellij、prompt 文件、目标 pane 或输入投递失败。
  - `2`:用法错误。
- **关键行为**:使用 `write-chars` 投递 TUI 输入；长 prompt 写入唯一的系统
  临时 Markdown 文件并发送读取指针；成功后只删除本次 staged prompt。
  不再解析或校验旧的 pane completion-notice。

### `scripts/create-reply-route.py`

```bash
create-reply-route.py [--temp-dir <directory>]
```
- **作用**: 创建 `0700` 私有 Reply route，生成不可预测的 UUID
  `request_id`，并准备回复记录、FIFO 和 waiter 锁。
- **stdout**: JSON 对象，包含 `schema_version`、`request_id`、`route_dir`、
  `wait_command`、`reply_command` 和 `cancel_command`。
- **退出码**: `0` 成功；`1` 系统临时目录或 route 创建失败。
- **关键行为**: `reply_command` 应原样加入 tracked delegation prompt。

### `scripts/wait-for-reply.py`

```bash
wait-for-reply.py <request-id> [--timeout <seconds>] [--temp-dir <directory>]
```
- **作用**: 由发件 Agent runtime 作为后台任务启动，等待一个 request 的
  Delegation reply；默认无限等待。
- **stdout**: 一个 JSON 终态记录，包含 `schema_version`、`request_id`、
  `status`、`summary`、`result_file` 和 `finished_at`。
- **退出码**: `0` 表示收到合法终态（包括 `failed`、`cancelled`、`timed_out`）；
  `1` 表示 route、协议、锁或 I/O 错误。
- **关键行为**: 只允许一个活动 waiter；先读取已有记录，再阻塞等待 FIFO；
  显式 deadline 到期时写入 `timed_out`；退出时不删除 route 或结果文件。

### `scripts/reply-to-request.py`

```bash
reply-to-request.py <request-id> <succeeded|failed> <summary-file> \
  [result-file] [--temp-dir <directory>]
```
- **作用**: 接收 Agent 提交一次 Delegation reply。
- **stdout**: 成功时输出 request ID 和结果文件路径；完全相同的重复提交也成功。
- **退出码**: `0` 表示新终态或幂等重复；`1` 表示 route、参数、文件、冲突、
  已终结或 I/O 错误。
- **关键行为**: 原子写入固定 schema 的 JSON；只能写 `succeeded` 或 `failed`；
  摘要必须是 UTF-8 且不超过 4 KiB；完整结果（如果提供）复制进 route。

### `scripts/cancel-reply.py`

```bash
cancel-reply.py <request-id> [summary-file] [--temp-dir <directory>]
```
- **作用**: 发件 Agent 取消一个尚未终结的 request 并唤醒 waiter。
- **stdout**: 取消后的 JSON 终态记录；相同取消请求幂等成功。
- **退出码**: `0` 表示写入 `cancelled`；`1` 表示 route 不存在、已有其它终态、
  参数/文件无效或 I/O 失败。
- **关键行为**: 取消是 first-writer-wins 的终态，迟到的接收方回复不得覆盖它。

## Troubleshooting

- No panes found / stale ID -> re-run `find-pane.sh` (IDs change when panes reopen).
- Target was busy -> wait, then re-run `relay.py`.
- A waiter failure -> inspect the JSON/error output and restart it with the same
  `request_id`; an already written terminal record is recoverable.
- A late reply or conflicting terminal -> the first recorded terminal status is
  authoritative; do not overwrite the route.
- Long prompts (>2KB) are automatically written to a temp file with a short pointer
  sent instead — relay.py will warn when this happens.
- Truncated long prompt -> split it, or hand off via a file the target reads.
- Agent not matched -> set `CODE_AGENT_RE` to include its command name.

See `zellij-io.md` for raw zellij command semantics.
