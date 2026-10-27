---
name: feishu-notify
description: 通过飞书（Feishu/Lark）接口发送通知：支持群机器人 webhook 和应用机器人（app bot，可发群消息与私聊）。当用户说「飞书通知我」「发个飞书消息」「飞书提醒」「notify me on Feishu」「send a Feishu message」，或其他技能/脚本需要一条命令把消息推到用户飞书时使用。Do NOT use this for 非 飞书 平台的通知（钉钉/企微/Slack 用对应平台技能），也不要用于需要接收用户回复的双向机器人场景（本技能只发不收）。
---

# feishu-notify

把一条消息发到用户的飞书：纯文本或 Markdown 卡片，发给群机器人的群，
或应用机器人可达的群/私聊。可从任意 Agent 工具或其他脚本调用——脚本为
纯 Node（≥18、零依赖），在 shell 里运行即可，不依赖特定工具。

## 信任契约与安全红线（先读这一段）

- `scripts/` 下的脚本接口以下文为准，**不需要阅读脚本源码**。
- 凭证只存在于用户级配置文件（缺省 `~/.config/feishu-notify/config.json`，
  可用环境变量 `FEISHU_NOTIFY_CONFIG` 指定路径）。**不要读取、cat、复制该文件**，
  不要把其中的任何值（url/secret/keyword/appId/appSecret/receiveId）写进命令行、
  对话或任何输出。
- 所有脚本的输出都经过掩码设计（只显示尾 4 位或「有/无」）——直接转述即可。
- 未配置或配置损坏时（`send`/`targets` 退出码 2），你的全部职责是打印一行：
  `请在自己的终端运行: node <本技能目录的绝对路径>/scripts/configure.mjs`
  不要代跑 configure（它是给用户终端的交互式脚本），也不要代填任何凭证。
- 详细决策见仓库 `docs/adr/0004`。

## 脚本接口

三个脚本都在 `scripts/` 下，均支持 `--help`/`-h`（打印 usage，退出 0）。

### send.mjs — 发送

```sh
node scripts/send.mjs [--target <名称>] [--card] [--title <标题>] [消息文本]
```

- `--target`：目标名；缺省用配置里的 `default`（或唯一目标）。
- `--card`：发 Markdown 卡片（标题头 + markdown 正文）；缺省发纯文本。
- `--title`：卡片标题，仅配合 `--card`；缺省「通知」。
- 消息文本：其余参数拼接；无参数且 stdin 是管道时读 stdin（适合长文本/管道）。

| 输出 | 含义 |
|---|---|
| stdout 一行 `sent to <目标> (<类型>)`，退出 0 | 发送成功 |
| stderr 中文错误，退出 1 | 用法错误 |
| stderr 含「配置」，退出 2 | 未配置/配置损坏/无 default → 打印 configure 路径（见上） |
| stderr 含「目标」，退出 3 | 目标不存在或字段缺失 → 提示用 `targets.mjs` 查看 |
| stderr「发送失败：…」，退出 4 | 发送失败（错误已翻译成中文，含原因与修法） |

环境变量：`FEISHU_NOTIFY_CONFIG`（配置文件路径）。

行为细节：群机器人支持签名校验与关键词安全模式（keyword 自动织入，无需关心）；
应用机器人的 token 过期会自动刷新重试一次，发送本身不重试。

### targets.mjs — 查看与校验

```sh
node scripts/targets.mjs [--check]
```

- 无参数：每目标一行掩码摘要（名称、类型、掩码标识、secret/keyword 有无、default 标记）。
- `--check`：app 目标实际换取 token 验证凭证，webhook 目标校验 URL 形态；
  **不会发送任何消息**。

| 输出 | 含义 |
|---|---|
| stdout 掩码摘要（+ check 结果行），退出 0 | 成功 / 校验全过 |
| stderr 中文错误，退出 1 | 用法错误 |
| stderr 含「配置」+ configure 路径，退出 2 | 未配置 / 无目标 / 配置损坏 |
| check 行含「失败」，退出 4 | 校验有失败（错误行已含中文说明与修法） |

环境变量：`FEISHU_NOTIFY_CONFIG`（配置文件路径）。

### configure.mjs — 用户终端专用

```sh
node scripts/configure.mjs
```

- 无参数；不接受管道输入——stdin 不是 TTY 时直接退出 2 并提示「Agent 请勿代跑」，
  所以凭证无法经由脚本被代填。
- stdout：菜单与进度（secret 输入不回显）。
- 退出码：0 正常退出；2 配置读写失败或非 TTY 运行。
- 环境变量：`FEISHU_NOTIFY_CONFIG`（配置文件路径）。
- 交互式初始化/维护配置：添加/编辑目标（含手机号→open_id、列群选 chat_id 的
  ID 发现）、设置 default、发测试消息。**只能在用户的终端运行**；Agent 不代跑、
  不代填。你唯一要做的是把它的绝对路径打印给用户。

## 典型用法

- 用户说「飞书通知我部署完成了」→ `send.mjs 部署完成`（走 default 目标）。
- 用户说「发个飞书卡片到值班群，标题 XX」→
  `send.mjs --target 值班群 --card --title XX <正文>`。
- 其他技能的脚本要通知 → `node <skill>/scripts/send.mjs "消息"`，按退出码分支。
- 先看有什么目标 / 验证凭证 → `targets.mjs`、`targets.mjs --check`。

## 排错速查

- 退出 2 → 未配置：打印 configure 路径。
- 「签名校验失败」→ webhook secret 不对或关键词缺失（configure 里核对）。
- 「权限不足 / scope」→ 到飞书开放平台给应用开通对应权限。
- 「关键词不匹配」→ 机器人用了关键词安全模式，configure 里补 keyword。
