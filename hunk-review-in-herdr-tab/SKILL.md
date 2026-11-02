---
name: hunk-review-in-herdr-tab
description: "在 Herdr 新建 tab 启动一个新 Hunk 实例，用 hunk-review 技能引导审查当前会话的工作区改动"
disable-model-invocation: true
---

# 在 Herdr 新 tab 中启动 Hunk 并引导审查

三步编排：用 `herdr` 技能新建 tab → 在其中启动 Hunk TUI → 用 `hunk-review` 技能引导审查。本文件只描述编排流，CLI 语法一律以两个技能的文档为准。

## 执行步骤

### 0. 前置检查

1. 确认处于 Herdr 管理的 pane 中（`HERDR_ENV` 检查）——失败则停止
2. 记录仓库根目录（`git rev-parse --show-toplevel`），后续 tab cwd 以此为准
3. 记录当前已有的 Hunk 会话作为基线，用于稍后识别新会话

### 1. `herdr` — 新建 tab 并启动 Hunk

加载 `herdr` 技能，在其规则下新建一个 tab，cwd 设为步骤 0.2 记录的仓库根目录。在该 tab 的 pane 中运行 `hunk diff` 启动 Hunk TUI。TUI 必须跑在真实终端中，禁止在本会话直接运行交互式 hunk 命令。

### 2. 等待新会话上线

轮询 Hunk 会话列表（约每 3 秒、最多 30 秒），直到出现**基线中不存在**的新会话，记下其 session-id。超时则用 `herdr` 技能读 pane 输出诊断；若 Hunk 在跑而会话列表找不到，按 `hunk-review` 技能「Common errors」处理。后续操作一律用显式 session-id。

### 3. `hunk-review` — 引导审查

加载 `hunk-review` 技能，按其工作流审查该会话已加载的改动。结束时给一段总结。

## 边界

- 本命令创建的 tab/pane 保持不动，让 Hunk 继续运行
- 不关闭、不重排非本命令创建的 tab/pane/workspace
- 所有 Herdr 控制命令以步骤 0 的检查通过为前提
