#!/usr/bin/env node
// configure.mjs — 在用户自己的终端里交互式初始化/维护 feishu-notify 配置。
// Agent 不要代跑本脚本；Agent 的职责只是把本文件的绝对路径打印给用户。
//
// Usage: configure.mjs
//
// 流程（菜单循环）：
//   1. 添加目标：群机器人（webhook url + 可选 secret/keyword）或
//      应用机器人（appId/appSecret + receiveIdType + receiveId，支持
//      open_id 四种获取：私聊发消息自动抓取（机器人即时回复 open_id，需长连接）/
//      群发消息抓取 / 手机号·邮箱查询 / 手动粘贴；chat_id：列群选择 / 手动）
//   2. 编辑已有目标
//   3. 设置 default 目标
//   4. 向某目标发测试消息
//   保存时文件权限 0600，且不覆盖未知字段
//
// Environment:
//   FEISHU_NOTIFY_CONFIG  配置文件路径（缺省 ~/.config/feishu-notify/config.json）
//
// stdout: 菜单与进度（secret 输入不回显）
// Exit codes: 0 正常退出; 2 配置读写失败，或 stdin 不是 TTY（拒绝管道/代跑）
//
// 信任契约：secret/appSecret 均掩码输入与显示；除保存到配置文件外不落任何地方。

import readline from "node:readline";
import { fileURLToPath } from "node:url";
import { buildCard, getBotInfo, listChatMessages, listChats, lookupUserId, sendToTarget } from "./lib/feishu.mjs";
import { listenDirectMessage } from "./lib/longconn.mjs";
import { ConfigError, configPath, describeTarget, loadConfig, mask, resolveTarget, saveConfig } from "./lib/shared.mjs";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// 秘钥掩码（ADR 0004）：terminal:true 下 readline 处于 raw mode、回显由本进程控制，
// 覆盖 _writeToOutput 在 muted 时吞掉全部输出。提示语必须经 rl.question 输出——
// 手动预写再调空提示的 question 会被 readline 的整行重绘擦掉（真实 TTY 下复现过）。
let rl = null;
let muted = false;

function startInteractive() {
  rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
  rl._writeToOutput = (s) => {
    if (!muted) rl.output.write(s);
  };
}

// 问题独立成行，输入在下一行以 "> " 开头；选项逐行排列。
async function ask(question, { secret = false, optional = false } = {}) {
  while (true) {
    muted = false;
    const pending = new Promise((resolve) => rl.question(`${question}\n> `, resolve));
    muted = secret; // question() 已同步输出提示行；此后只吞按键回显
    const answer = (await pending).trim();
    muted = false;
    if (secret) process.stdout.write("\n"); // 回车换行也被吞了，补一行
    if (answer || optional) return answer;
    console.log("  不能为空，请重新输入。");
  }
}

async function askChoice(question, options) {
  const menu = options.map((o, i) => `  ${i + 1}) ${o.label}`).join("\n");
  while (true) {
    const answer = await ask(`${question}\n${menu}`);
    const n = Number(answer);
    if (Number.isInteger(n) && n >= 1 && n <= options.length) return options[n - 1].value;
    console.log(`  请输入选项编号（1-${options.length}）。`);
  }
}

function printTargets(config) {
  const names = Object.keys(config.targets ?? {});
  if (!names.length) {
    console.log("（还没有任何目标）");
    return;
  }
  for (const name of names) {
    console.log(`  - ${describeTarget(name, config.targets[name], config.default === name)}`);
  }
}

async function askWebhookTarget(existing) {
  console.log("群机器人：在飞书群里「设置 → 群机器人 → 添加机器人 → 自定义机器人」获取 webhook。");
  const url = await ask("webhook URL");
  console.log("安全设置二选一：签名校验（secret）或自定义关键词（keyword），也可留空（不推荐）。");
  const secret = await ask("签名 secret（输入不回显，可留空）", { secret: true, optional: true });
  const keyword = await ask("关键词 keyword（可留空）", { optional: true });
  // 保留未知字段：只覆盖本脚本管理的键
  return { ...existing, type: "webhook", url, ...(secret ? { secret } : {}), ...(keyword ? { keyword } : {}) };
}

/** 手机号归一化：本地 11 位补 +86；+国际格式直通；其余返回 null。 */
function normalizePhone(input) {
  const p = input.replace(/[\s-]/g, "");
  if (p.startsWith("+")) return /^\+\d{7,15}$/.test(p) ? p : null;
  if (/^1\d{10}$/.test(p)) return `+86${p}`;
  return null;
}

/** 快照机器人所有可见会话（群）的最新消息 id，作为"新消息"的判定基线。 */
async function chatBaseline(appId, appSecret) {
  const baseline = new Map();
  for (const c of await listChats(appId, appSecret)) {
    const newest = (await listChatMessages(appId, appSecret, c.chatId))[0];
    baseline.set(c.chatId, newest ? newest.messageId : null);
  }
  return baseline;
}

/**
 * 临时接收会话（最长 90 秒）：等用户把机器人拉进群并在群里发一条消息，抓发送者
 * open_id。零依赖实现：基线轮询"新群出现 / 已有群来了新消息"（REST），不用 WS。
 * 注意：机器人的单聊会话对 REST 不可见，所以只能在群里抓。
 */
async function captureOpenIdByGroupMessage(appId, appSecret) {
  let bot;
  try {
    bot = await getBotInfo(appId, appSecret);
  } catch (err) {
    console.log(`  无法获取机器人信息（${err.message}）。`);
    return null;
  }
  let baseline;
  try {
    baseline = await chatBaseline(appId, appSecret);
  } catch (err) {
    console.log(`  无法读取机器人现有会话（${err.message}）。请检查 im:chat 与 im:message.group_msg 权限。`);
    return null;
  }
  console.log(`机器人「${bot.appName}」已就绪。请把它拉进一个群（建议只有你和机器人），然后在群里发一条任意消息。`);
  process.stdout.write("  等待接收");
  const deadline = Date.now() + 90_000;
  try {
    while (Date.now() < deadline) {
      await sleep(3_000);
      process.stdout.write(".");
      for (const c of await listChats(appId, appSecret)) {
        const isNewChat = !baseline.has(c.chatId);
        const newest = (await listChatMessages(appId, appSecret, c.chatId))[0];
        const fromUser = newest?.senderOpenId && newest.senderOpenId !== bot.openId;
        const hasNew = fromUser && (isNewChat || newest.messageId !== baseline.get(c.chatId));
        if (hasNew) {
          process.stdout.write("\n");
          return { openId: newest.senderOpenId, from: c.name };
        }
      }
    }
  } catch (err) {
    process.stdout.write("\n");
    console.log(`  接收出错（${err.message}）。`);
    return null;
  }
  process.stdout.write("\n");
  console.log("  90 秒内没等到消息。换一种方式继续。");
  return null;
}

async function askAppTarget(existing) {
  console.log("应用机器人：在 open.feishu.cn 创建企业自建应用，开启机器人能力，");
  console.log("并开通权限：im:message:send_as_bot（发消息）、im:chat（列群）、im:message.group_msg（读群消息）、");
  console.log("im:message.p2p_msg:readonly（私聊抓取）+ 事件订阅方式选「长连接」并订阅 im.message.receive_v1、");
  console.log("contact:user.id:readonly（手机号/邮箱查 ID）。");
  const appId = await ask("appId（cli_ 开头）");
  const appSecret = await ask("appSecret（输入不回显）", { secret: true });

  const kind = await askChoice("接收方式：", [
    { label: "私聊某个人（open_id）", value: "open_id" },
    { label: "发到某个群（chat_id）", value: "chat_id" },
  ]);

  let receiveId = "";
  if (kind === "open_id") {
    while (!receiveId) {
        const method = await askChoice("open_id 获取方式：", [
          { label: "给机器人发一条私聊消息，自动抓取（推荐，需事件订阅=长连接）", value: "dm" },
          { label: "拉机器人进群发一条消息，自动抓取", value: "capture" },
          { label: "手机号或邮箱查询", value: "lookup" },
          { label: "手动粘贴 open_id", value: "manual" },
        ]);
        if (method === "dm") {
          const hit = await listenDirectMessage(appId, appSecret).catch((err) => {
            console.log(`  私聊抓取不可用（${err.message}）。`);
            return null;
          });
          if (hit) receiveId = hit.openId;
        } else if (method === "capture") {
          const hit = await captureOpenIdByGroupMessage(appId, appSecret);
          if (hit) {
            console.log(`  收到 ${hit.from ?? "私聊"} 的消息，open_id：${hit.openId}`);
            receiveId = hit.openId;
          }
        } else if (method === "lookup") {
          const raw = await ask("该用户的手机号（如 13800138000）或邮箱");
          const email = raw.includes("@") ? raw : null;
          const phone = email ? null : normalizePhone(raw);
          if (!email && !phone) {
            console.log("  格式不对：手机号支持 13800138000 / +8613800138000，或直接输入邮箱。");
            continue;
          }
          try {
            const openId = await lookupUserId(appId, appSecret, email ? { email } : { phone });
            if (openId) {
              console.log(`  发现 open_id：${openId}`);
              receiveId = openId;
            } else {
              console.log("  未找到（需企业内成员，且应用有 contact:user.id:readonly 权限）。");
            }
          } catch (err) {
            console.log(`  查询失败（${err.message}）。`);
          }
        } else {
          receiveId = await ask("open_id（ou_ 开头）");
        }
      }
    } else {
      let picked = false;
      try {
        const chats = await listChats(appId, appSecret);
        if (chats.length) {
          chats.forEach((c, i) => console.log(`  ${i + 1}) ${c.name}`));
          const pick = await ask("选择群（输入编号；直接回车跳过）", { optional: true });
          const n = Number(pick);
          if (Number.isInteger(n) && n >= 1 && n <= chats.length) {
            console.log(`  选择 chat_id：${chats[n - 1].chatId}`);
            receiveId = chats[n - 1].chatId;
            picked = true;
          }
        } else {
          console.log("  机器人还不在任何群里（先把机器人拉进群，或手动粘贴 chat_id）。");
        }
      } catch (err) {
        console.log(`  列群失败（${err.message}）。`);
      }
      if (!picked) receiveId = await ask("chat_id（oc_ 开头）");
    }
  return { ...existing, type: "app", appId, appSecret, receiveIdType: kind, receiveId };
}

async function addTarget(config) {
  const name = await ask("目标名称（如 group / me）");
  if (config.targets[name]) {
    const overwrite = await askChoice(`目标 ${name} 已存在，`, [
      { label: "覆盖编辑", value: "edit" },
      { label: "取消", value: "cancel" },
    ]);
    if (overwrite === "cancel") return;
  }
  const type = await askChoice("目标类型：", [
    { label: "群机器人 webhook", value: "webhook" },
    { label: "应用机器人 app", value: "app" },
  ]);
  config.targets[name] =
    type === "webhook"
      ? await askWebhookTarget(config.targets[name] ?? {})
      : await askAppTarget(config.targets[name] ?? {});
  if (!config.default) config.default = name;
  saveConfig(config);
  console.log(`已保存目标 ${name}（${configPath()}，权限 0600）。`);
}

async function setDefault(config) {
  const names = Object.keys(config.targets ?? {});
  if (!names.length) return console.log("先添加至少一个目标。");
  const choice = await askChoice("default 目标：", names.map((n) => ({ label: n, value: n })));
  config.default = choice;
  saveConfig(config);
  console.log(`default 已设为 ${choice}。`);
}

async function testSend(config) {
  const names = Object.keys(config.targets ?? {});
  if (!names.length) return console.log("先添加至少一个目标。");
  const choice = await askChoice("测试发送到：", names.map((n) => ({ label: n, value: n })));
  try {
    const target = resolveTarget(config, choice);
    await sendToTarget(target, { card: buildCard("通知", "这是一条 feishu-notify 测试消息。") });
    console.log(`测试消息已发送到 ${choice}，请到飞书确认收到。`);
  } catch (err) {
    console.log(`测试发送失败：${err.message}`);
  }
}

async function main() {
  if (process.argv.slice(2).some((a) => a === "--help" || a === "-h")) {
    console.log("Usage: configure.mjs — 交互式初始化/维护 feishu-notify 配置（在用户终端运行）");
    return;
  }
  // 只允许用户终端交互运行：拒绝管道/非 TTY 喂入（防止 Agent 代填凭证，ADR 0004）
  if (!process.stdin.isTTY) {
    console.error("configure.mjs 需要在用户终端交互运行（当前 stdin 不是 TTY）。");
    console.error("Agent 请勿代跑，把下面这行交给用户在自己的终端执行：");
    console.error(`  node ${fileURLToPath(import.meta.url)}`);
    process.exitCode = 2;
    return;
  }
  startInteractive();
  const existing = loadConfig({ required: false });
  const config = existing ?? { targets: {} };
  console.log(`feishu-notify 配置（${configPath()}）`);
  printTargets(config);
  while (true) {
    const action = await askChoice("操作：", [
      { label: "添加/编辑目标", value: "add" },
      { label: "设置 default", value: "default" },
      { label: "发测试消息", value: "test" },
      { label: "退出", value: "quit" },
    ]);
    if (action === "quit") break;
    if (action === "add") await addTarget(config);
    if (action === "default") await setDefault(config);
    if (action === "test") await testSend(config);
  }
  rl.close();
}

main().catch((err) => {
  console.error(err instanceof ConfigError ? err.message : `配置失败：${err.message}`);
  process.exitCode = 2;
  rl?.close();
});
