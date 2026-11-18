---
name: hunk-review-in-herdr-tab
description: "在 Herdr 新 tab（TUI）或 herdr-core 新终端启动一个新 Hunk 实例，用 hunk-review 技能引导审查当前会话的工作区改动"
disable-model-invocation: true
---

# 在 Herdr 新 tab / core 终端中启动 Hunk 并引导审查

## 执行步骤

### 1. 运行启动脚本

在目标仓库中执行本技能目录下的 `scripts/launch.sh`。脚本自动完成：环境判定（`HERDR_ENV=1` → herdr TUI 用 `herdr` CLI；否则 `HC_TERMINAL_ID` → herdr core 用 `hc` CLI）、记录基线会话、新建 tab/终端并启动 `hunk diff`、轮询等待新 Hunk 会话上线（约 30 秒）。

- **成功**：stdout 输出一行 JSON，含 `env`、`repo`、`session_id` 及 tab/终端地址——以此为准，进入步骤 2
- **失败**：非零退出，stderr 附原因和启动处屏幕摘录。若 Hunk 在跑而会话列表找不到，按 `hunk-review` 技能「Common errors」处理（localhost/沙箱）

### 2. `hunk-review` — 引导审查

加载 `hunk-review` 技能，用脚本输出的显式 `session_id` 审查该会话已加载的改动。结束时给一段总结。

## 边界

- 脚本创建的 tab/终端保持不动，让 Hunk 继续运行
- 不关闭、不重排、不清理非本命令创建的 tab/pane/workspace/终端
- Hunk TUI 必须跑在真实终端中，禁止在本会话直接运行交互式 hunk 命令