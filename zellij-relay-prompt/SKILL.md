---
name: zellij-relay-prompt
description: "Relay a prompt to another zellij pane running a coding agent (Claude Code, Codex, OpenCode, Aider, etc.), so that separate agent instance executes it. Use whenever the user wants to delegate or hand off a task to another coding-agent session in a different zellij pane - e.g. 'send this to the other pane', 'relay this prompt', 'ask the other agent to ...', 'delegate to pane X', 'run this in the retail-platform pane', or when coordinating work across multiple parallel agent sessions. Also use when the user refers to a zellij pane by id/title or wants one agent to drive another. Do NOT use to CREATE a new pane — that is zellij-claude-pane."
---

# Relay a prompt through zellij

Send a prompt to another zellij pane running a coding agent (Claude Code, Codex,
OpenCode, Aider, ...) so that pane runs it. This lets you parallelize work across
multiple agent sessions.

The relayed prompt is real - the target agent runs it. Only relay tasks you want
executed.

`scripts/` paths are relative to this skill's directory.

## If no agent pane exists yet

Use `zellij-claude-pane` to create one, then relay to it:
1. `bash <abs-path-to-zellij-claude-pane>/scripts/new-pane.sh` — creates pane, starts Claude.
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

2. **Stage the prompt** to `/tmp/zellij-relay-prompt-<pane-id>.md` (overwrite).
   Use your file-writing tool, not `echo` - a file preserves backticks, `$`, quotes,
   newlines. The filename is per-target so concurrent relays don't clobber each other.

3. **Relay:**
   ```bash
   python3 scripts/relay.py <pane-id>
   ```
   Reads `/tmp/zellij-relay-prompt-<pane-id>.md` by default, clears the target's
   input, types the prompt verbatim, presses Enter. Prints chars sent or an error.

4. **Confirm** the target pane ID to the user. Optionally verify it landed:
   ```bash
   zellij action dump-screen --pane-id <pane-id> --path /tmp/relay-verify.txt && tail -15 /tmp/relay-verify.txt
   ```

## Completion notification (optional, best-effort)

To have the target signal when done, append this to the staged prompt - it types a
message back into your pane as a new input line so you can pick up the result:

```
完成后运行: bash <abs-path-to-this-skill>/scripts/notify-complete.sh <your-pane-id> "done: <summary>"
```

Replace `<your-pane-id>` with your own pane ID — the notification goes back to
**you**, not to the target. **Must run `echo $ZELLIJ_PANE_ID` first — never
guess or invent a number.** relay.py will warn if it detects a mismatch.

Use the absolute script path (the target may lack this skill). Best-effort: the
target may be busy or decline; if silent, check it with `dump-screen`.

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
relay.py <pane-id> [prompt-file]
```
- **作用**: 把已 stage 的 prompt 投递给目标 pane 上运行的 coding agent
  (清空输入 → write-chars 逐字输入 → Enter)。
- **参数**:
  - `pane-id`(必填):目标 pane id,数字(如 `354`)或字符串(如
    `terminal_354`、`plugin_42`)均可。
  - `prompt-file`(可选,默认 `/tmp/zellij-relay-prompt-<pane-id>.md`):
    按目标命名,这样对不同 pane 的并发 relay 不会相互覆盖。
- **环境变量**: `ZELLIJ_PANE_ID`(可选,用于 Guard 1 校验 prompt 中
  `notify-complete.sh` 引用是否指向调用方自身)。
- **stdout**: 成功时打印 `Relayed N chars to pane <id> (from <file>).`。
- **stderr / 退出码**:
  - `0`:成功。
  - `1`:运行时错误 —— zellij 不可达、prompt 文件读不到、文件为空、
    `Ctrl+u` / `write-chars` / `Enter` 任一失败、目标 pane 已失效、
    长 prompt 临时文件写入失败。
  - `2`:用法错误(没传 `<pane-id>`)。
- **关键行为**:
  - **序列**:`send-keys Ctrl+u` → `write-chars <content>` → 短暂 sleep
    (按字符数自适应,`max(0.2, min(len*0.001, 1.0))` 秒)→ `send-keys Enter`。
    用 `write-chars` 而非 `write`,因为前者模拟键入会落到 coding agent 的
    TUI 输入框,后者不会。
  - **Guard 1(警告,非阻塞)**:如果 prompt 中出现了
    `notify-complete.sh <pane-id>` 形式、且其 `<pane-id>` 解析后与
    `$ZELLIJ_PANE_ID` 不一致,向 stderr 打印警告,提示调用方核对 `<your-pane-id>`
    是否写错(常见错误:agents 凭空编造 pane id,而不是用 `$ZELLIJ_PANE_ID`)。
  - **Guard 2(阻塞,退出 1)**:如果 `<pane-id>` 不在当前 `zellij action
    list-panes` 里,直接退出 1,提示"重新跑 find-pane.sh"。
  - **长 prompt 截断(`> 2000` 字符)**:把完整内容写入
    `/tmp/zellij-relay-long-<pane>.md`(此文件**不会被 relay.py 删除**,
    由接收方读取并自行清理),然后发送一个简短的中文指针
    ("请读取 <file> 并完整执行其中的任务。完成后删除该文件。");向 stderr
    打印一条 warning 提示发生了截断。
  - **副作用**:成功后**删除**原 staged prompt 文件(默认
    `/tmp/zellij-relay-prompt-<pane>.md`,或显式传入的 `prompt-file`);
    不会删除长 prompt 临时文件。

### `scripts/notify-complete.sh`

```bash
notify-complete.sh <target-pane-id> <message>
```
- **作用**: 给另一个 zellij pane 发送一条完成通知(best-effort)。
- **参数**: `target-pane-id`(必填)、`message`(必填,会原样发出)。
- **环境变量**: `ZELLIJ_PANE_ID`(用于自环守卫)。
- **stdout**: 成功时无输出。
- **stderr / 退出码**:
  - `0`:成功(`write-chars` + `Enter` 都通过)。
  - `1`:用法错误(参数少于 2)、自环(见下)、不在 zellij 会话内、目标 pane
    不可达(dump-screen 失败)、`write-chars` / `send-keys` 任一失败。
- **关键行为**:
  - **自环守卫**:若 `target-pane-id` 归一化后等于调用方自己的 `$ZELLIJ_PANE_ID`,
    拒绝执行并打印提示 —— 大概率是 prompt 中把 `$ZELLIJ_PANE_ID` 当字面量
    留给了接收方,而接收方在自己的 shell 里展开成了它自己的 id;应由发件方在
    staging 时把 sender 自己的 pane id 填进去(在发件 pane 里跑
    `echo $ZELLIJ_PANE_ID`)。
  - **存活性检查**:先 `zellij action dump-screen --pane-id <id> --path
    /tmp/zellij-notify-check-$$.txt`,失败则拒绝(临时检查文件立即 `rm -f`)。
  - **发送内容**:`✓ <message>`(自带前缀)→ `sleep 0.2` → `Enter`。
  - **Best-effort**:不保证目标 pane 一定读到(可能忙/可能拒收);静默时用
    `dump-screen` 核查。

## Troubleshooting

- No panes found / stale ID -> re-run `find-pane.sh` (IDs change when panes reopen).
- Target was busy -> wait, then re-run `relay.py`.
- Long prompts (>2KB) are automatically written to a temp file with a short pointer
  sent instead — relay.py will warn when this happens.
- Truncated long prompt -> split it, or hand off via a file the target reads.
- Agent not matched -> set `CODE_AGENT_RE` to include its command name.

See `zellij-io.md` for raw zellij command semantics.
