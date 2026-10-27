#!/usr/bin/env node
// send.mjs — 发送一条飞书通知到某个 Notify target。
//
// Usage: send.mjs [--target <名称>] [--card] [--title <标题>] [消息文本]
//   --target   目标名；缺省用配置里的 default
//   --card     发 Markdown 卡片（plain_text 头 + markdown 元素）；缺省发纯文本
//   --title    卡片标题，仅配合 --card；缺省为「通知」
//   消息文本   其余参数按空格拼接；无参数且 stdin 有管道输入时读入 stdin
//
// Environment:
//   FEISHU_NOTIFY_CONFIG  配置文件路径（缺省 ~/.config/feishu-notify/config.json）
//
// stdout: 成功时一行 "sent to <目标> (<类型>)"
// stderr: 中文错误说明
// Exit codes: 0 成功; 1 用法错误; 2 配置缺失/损坏/无 default; 3 目标不存在或字段缺失; 4 发送失败
//
// 信任契约：凭证只从配置文件读取，绝不回显；本脚本的接口以此为准，
// 不需要阅读脚本源码。

import { buildCard, sendToTarget } from "./lib/feishu.mjs";
import { ConfigError, TargetError, UsageError, defaultTargetName, fail, loadConfig, resolveTarget } from "./lib/shared.mjs";

const USAGE = `Usage: send.mjs [--target <名称>] [--card] [--title <标题>] [消息文本]
  --target <名称>   目标名；缺省用配置里的 default
  --card            发 Markdown 卡片；缺省发纯文本
  --title <标题>    卡片标题，仅配合 --card；缺省为「通知」
  消息文本          其余参数拼接；无参数时读管道 stdin
环境变量：FEISHU_NOTIFY_CONFIG 指定配置文件路径
退出码：0 成功 | 1 用法错误 | 2 配置问题 | 3 目标问题 | 4 发送失败`;

function parseArgs(argv) {
  const opts = { target: null, card: false, title: null, message: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--help" || a === "-h") return { help: true, opts };
    if (a === "--card") opts.card = true;
    else if (a === "--target") opts.target = argv[++i];
    else if (a === "--title") opts.title = argv[++i];
    else if (a.startsWith("--")) throw new UsageError(`未知参数：${a}\n${USAGE}`);
    else opts.message.push(a);
  }
  if (opts.target === "") throw new UsageError(`--target 不能为空。\n${USAGE}`);
  if (opts.title === "") throw new UsageError(`--title 不能为空。\n${USAGE}`);
  if (opts.title && !opts.card) throw new UsageError(`--title 仅配合 --card 使用。\n${USAGE}`);
  return { help: false, opts };
}

async function readStdin() {
  let data = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) data += chunk;
  return data;
}

/** 群机器人关键词安全模式：卡片标题须含关键词。 */
function weaveCardTitle(target, title) {
  const kw = target.keyword;
  if (target.type !== "webhook" || !kw || target.secret) return title;
  return title.includes(kw) ? title : `${kw}：${title}`;
}

/** 群机器人关键词安全模式：文本消息须含关键词。 */
function weaveText(target, text) {
  const kw = target.keyword;
  if (target.type !== "webhook" || !kw || target.secret) return text;
  return text.includes(kw) ? text : `${kw} ${text}`;
}

async function main() {
  const { help, opts } = parseArgs(process.argv.slice(2));
  if (help) {
    console.log(USAGE);
    return;
  }

  let message = opts.message.join(" ");
  if (!message) {
    if (process.stdin.isTTY) throw new UsageError(`缺少消息内容。\n${USAGE}`);
    message = (await readStdin()).trim();
  }
  if (!message) throw new UsageError("消息内容为空。");

  const config = loadConfig();
  const name = opts.target ?? defaultTargetName(config);
  const target = resolveTarget(config, name);

  if (opts.card) {
    const card = buildCard(weaveCardTitle(target, opts.title ?? "通知"), message);
    await sendToTarget(target, { card });
  } else {
    await sendToTarget(target, { text: weaveText(target, message) });
  }
  console.log(`sent to ${name} (${target.type})`);
}

main().catch(fail);
