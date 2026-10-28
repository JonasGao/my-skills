# Spec: feishu-notify — Feishu notifications for agents

Status: ready-for-agent

Skill for sending notifications to the user's Feishu (飞书) through both bot
mechanisms, usable in-conversation by any coding Agent and one-shot from
other skills' scripts. Vocabulary per CONTEXT.md "Feishu notification"
(Webhook bot, App bot, Notify target, Default target, Markdown card); secret
handling per ADR 0004.

## Problem Statement

The user wants agents and automation to reach them on Feishu: quick text
pings and richer Markdown cards, to a group via a group custom bot and to
themselves privately via a self-built app bot. The only working Feishu-send
code lives inside the ai-subscriptions app and is not reusable from agents.
There is no skill for this, and nothing today guards Feishu credentials
against leaking into Agent transcripts.

## Solution

A new skill `feishu-notify` in this repo: three pure-Node zero-dependency
scripts — send, configure (interactive, user-terminal-only), and targets —
operating on named Notify targets stored in a user-level config file. A
tool-agnostic SKILL.md carries Chinese and English trigger phrases, a
Do-NOT-use boundary, a complete script interface spec, and a trust contract
that keeps secrets out of Agent reach. Evals cover sending behavior and
trigger accuracy. Release to the skills home is manual (out of scope).

## User Stories

1. As a User, I want to tell my Agent "飞书通知我：构建完成", so that the message lands on my Feishu without me copying anything by hand.
2. As a User, I want the same to work when I say "notify me on Feishu" in English, so that trigger language doesn't depend on which language I'm thinking in.
3. As a User, I want a plain text message by default and a Markdown card when asked for, so that quick pings stay light and summaries read well.
4. As a User, I want cards to carry a title I can override and a sensible default ("通知"), so that notifications are recognizable at a glance in the chat list.
5. As a User, I want to send to a specific named target ("发到值班群") and to the Default target when I don't care, so that routing never needs repeating.
6. As a User, I want several configured targets (a webhook group, my private app-bot chat), so that one skill serves group and personal use.
7. As a User, I want multiple App-bot targets sharing one app, so that I don't provision an app per target.
8. As a User, I want long or multi-line content accepted via stdin, so that piping output into a notification works.
9. As a User, I want my webhook's keyword security mode supported (keyword woven into the message), so that I don't have to switch the bot to signature mode.
10. As a User, I want my webhook's signature mode supported (HMAC timestamp+sign), so that security-enabled bots keep working.
11. As a User, I want app-bot delivery to my private chat (open_id), so that personal notifications don't spam a group.
12. As a User, I want app-bot delivery to a group (chat_id), so that the same mechanism covers both directions.
13. As a User, I want to run an interactive configure script in my own terminal, so that I can set up targets without an Agent in the loop.
14. As a User, I want configure to discover IDs for me (phone → open_id; list the bot's chats to pick a chat_id), so that I never hunt for opaque IDs in Feishu admin pages.
15. As a User, I want configure to send an optional test message at the end, so that I know the whole chain works before I rely on it.
16. As a User, I want my config written with owner-only permissions and unknown fields preserved on edit, so that manual tweaks survive and stay private.
17. As a User, I want a masked target listing (names, types, masked identifiers only), so that I can audit what's configured without exposing secrets.
18. As a User, I want a check mode that really exercises app credentials (token exchange) and validates webhook URLs, so that misconfiguration surfaces before a real send matters.
19. As a User, I want Feishu error codes translated to Chinese hints, so that failures tell me what to fix (permissions, token, bad ID) instead of raw codes.
20. As a User, I want token expiry handled transparently (cache, early refresh, one forced retry), so that long-gapped usage never fails on a stale token.
21. As an Agent, I want a one-line CLI I can call from a shell for any target, so that notifying is one tool call, not a research project.
22. As an Agent, I want machine-friendly results (one stdout line on success, Chinese stderr + non-zero exit on failure), so that scripted callers can branch on the outcome.
23. As an Agent, I want every script to answer --help with its usage, so that I never need to open script source.
24. As an Agent, I want SKILL.md to tell me the full interface (args, env, stdout/stderr, exit codes) and grant me permission not to read the scripts, so that I don't burn tokens on source-reading.
25. As an Agent, when the user isn't configured, I want my entire job to be printing the configure script's absolute path, so that I never touch credentials.
26. As an Agent, I want the trust contract to forbid reading the config file or putting secrets on command lines, so that I can't leak them even by trying to be helpful.
27. As an Agent from any tool (Codex, OpenCode, pi, Claude), I want SKILL.md phrased tool-agnostically ("run in a shell"), so that the same skill works everywhere.
28. As a Maintainer, I want zero npm dependencies on Node ≥ 18 ESM, so that the skill installs by copying a directory, on any OS with Node.
29. As a Maintainer, I want behavior and trigger evals beside the skill, so that regressions in phrasing or routing are caught before release.
30. As a Maintainer, I want the domain terms recorded in CONTEXT.md, so that future specs speak the same language (target, not channel).

## Implementation Decisions

- Three scripts, one per operation: `send`, `configure`, `targets`. No
  subcommand multiplexer.
- `send` interface: optional target name, `--card` for the Markdown card
  form, optional `--title` (default 通知), message from argv or stdin; exit 0
  with one stdout line on success, non-zero with Chinese stderr on failure.
- `targets` masks all secret-bearing values (last 4 characters or has-flags);
  `--check` performs a real token exchange for App-bot targets and URL-shape
  validation for Webhook-bot targets, never a real send.
- `configure` is interactive (readline, masked secret input), in the user's
  terminal only: add/edit targets, ID discovery (phone → open_id via the
  contact batch-get-id API; chat list via the bot chats API), owner-only
  file write preserving unknown fields, Default-target selection, optional
  closing test send. No WS-based ID capture (would need the vendor SDK).
- Message forms: plain `text` and Markdown card (plain_text header + single
  markdown element — the ai-subscriptions card shape). No raw card JSON
  passthrough, no `post` rich text.
- Config: single user-level file under the platform config home
  (`feishu-notify/config.json`), owner-only permissions, never committed.
  Shape (decision-rich, settled in grilling):

  ```json
  {
    "default": "me",
    "targets": {
      "group": { "type": "webhook", "url": "…", "secret": "可选", "keyword": "可选" },
      "me": { "type": "app", "appId": "…", "appSecret": "…",
              "receiveIdType": "open_id", "receiveId": "…" }
    }
  }
  ```

- Exactly one environment variable: the config-file path override. No
  field-level credential env vars, no env-reference syntax inside the file
  (ADR 0004).
- Webhook bot: optional HMAC-SHA256 signature (key `timestamp\nsecret`,
  empty-string payload, second-granularity timestamp, top-level
  `timestamp`/`sign` fields) and optional keyword woven into the
  title/text when no secret is set.
- App bot: app credentials → tenant access token → im/v1 messages; token
  cached per appId in-process with early-expiry buffer; one forced
  token-refresh retry on 401 / code 99991663; no send-level retries.
- Error translation: port the common ai-subscriptions error-code → Chinese
  table (token invalid, permission scopes, bad receive id).
- Runtime: Node ≥ 18 ESM modules, zero npm dependencies (built-in fetch,
  node:crypto, readline). Cross-platform by construction.
- SKILL.md: tool-agnostic wording (no product-specific tool names), Chinese
  and English triggers, Do-NOT-use boundary (non-Feishu notifications;
  two-way bots that receive replies), trust contract + complete script
  interface spec + `--help` on every script (repo convention).
- Secret hygiene is a first-class contract (ADR 0004): masked outputs
  everywhere, tokens/signatures never leave script memory, Agent never
  reads config or handles credentials, unconfigured state → print
  configure script's absolute path only.

## Testing Decisions

- Good tests exercise external behavior only: script argv →
  stdout/stderr/exit-code, and SKILL.md phrasing → correct skill selection.
  No assertions on internals (token cache, signing functions).
- Test seam (highest available): the script CLI boundary plus the SKILL.md
  trigger surface — settled as such in grilling (Round 2). No lower seams
  are introduced; the Feishu HTTP boundary is deliberately not stubbed in
  this iteration.
- `evals/evals.json` beside the skill: behavioral prompts (send to default
  target; pick named target; card vs text; unconfigured → print configure
  path, never read config) and trigger-accuracy entries with
  `should_trigger` true/false (Feishu notification phrasings in both
  languages vs. non-Feishu notification requests, e.g. DingTalk — which
  must NOT trigger).
- Prior art: the skills-home evals.json format (behavior prompts with
  expected output descriptions) and this repo's trigger-eval / benchmark
  pattern, including the "did the agent read script source?" metric.

## Out of Scope

- Receiving messages or replies (two-way bots, websocket listeners of any
  kind, event callbacks, card action callbacks).
- Raw interactive-card JSON passthrough (agent-authored card schemas).
- Removing/disabling targets via configure (hand-edit the JSON for now).
- Field-level or per-secret environment variable overrides; env-reference
  syntax inside the config file.
- Stub-HTTP unit tests of the Feishu boundary; send-level retries/backoff.
- Release automation (copying to the skills home) and per-tool adapter
  files (agents/*.yaml) — manual, per user decision.
- Non-Feishu platforms (DingTalk, WeCom, Slack).

## Further Notes

- Port these proven assets from ai-subscriptions rather than rediscovering
  them: the signing orientation gotcha (key `timestamp\nsecret`, empty
  payload — opposite of DingTalk), the card builder shape, per-appId token
  cache with early expiry, and the error-code translation table.
- Security requirement came from the user verbatim: "技能要注意不要泄露
  秘钥等私密内容，避免让 Agent 接触" — treat any PR weakening masking or
  the trust contract as violating ADR 0004.
- Decisions were settled over three grilling rounds (answer-board) on
  2026-10-27; terms recorded in CONTEXT.md under "Feishu notification".

## Comments

- 2026-10-27: Spec synthesized from grilling rounds 1–3 (consensus confirmed
  by user; ADR 0004 written alongside). Triage: ready-for-agent.

- 2026-10-27 (implementation): 双轴评审后修正——keyword 按 ADR 0004 掩码显示；
  网络层错误不再回带 URL 原文；saveConfig 自动建父目录；configure 加 stdin TTY
  守卫（拒绝管道代填）；零目标时 targets 退出 2；移除「唯一目标自动充当 default」
  与 webhook 域名猜测（回归 spec 字面）。保留偏差：`--title` 不带 `--card` 视为
  用法错误（守卫已文档化，静默忽略更糟）。逐块 issue 文件折回本 spec。

- 2026-10-28 (UX + discovery): 配置交互改为问题独立成行、输入行以 "> " 开头、选项逐行排列；
  open_id 获取扩为三种：给机器人发消息自动抓取（本地临时接收会话，最长 90 秒——
  零依赖实现：以私聊基线轮询 REST「新私聊/新消息」，非 WS，不引 SDK）、
  手机号（本地 11 位自动补 +86）或邮箱查询、手动粘贴。新增权限要求
  im:message.p2p_msg:readonly。参考工程的 lookupOpenIdByPhone 相应泛化为 lookupUserId。

- 2026-10-28 (live test correction): 真机实测（机器人「糯糯」）：机器人的单聊会话
  对 im/v1/chats REST 不可见（发多条私聊后列表仍为 0），im/v1/chats 也不返回
  chat_type 字段；群聊可见、群消息发送者经 im/v1/messages 列表可取（需
  im:message.group_msg scope，缺失时报 230027）。据此把「发消息抓取」从单聊
  改为群聊版：拉机器人进群（建议只有你和机器人）发消息，排除机器人自身
  open_id（bot/v3/info）后抓发送者。230027 翻译带 scope 名。

- 2026-10-28 (live test passed): 应用机器人私聊发送端到端实测通过——真实凭证
  （tmp/env，已 600 且不入库）+ 群聊捕获的 open_id，卡片与纯文本两条均送达
  用户飞书；发送、抓取、权限链路全部真机验证。私聊发送模式无 bug，
  无需修复；此前失败项仅"单聊消息抓取"（已改群聊版）。
