#!/usr/bin/env node
// targets.mjs — 列出（并可选校验）配置里的 Notify targets。输出永远掩码，不出现秘钥。
//
// Usage: targets.mjs [--check]
//   --check   逐个校验：app 目标实际换取 tenant_access_token；webhook 目标校验
//             URL 形态（http(s) 且可解析）。校验不发送任何消息。
//
// Environment:
//   FEISHU_NOTIFY_CONFIG  配置文件路径（缺省 ~/.config/feishu-notify/config.json）
//
// stdout: 每目标一行掩码摘要；--check 追加一行 "  check: 结果"
// stderr: 中文错误说明
// Exit codes: 0 成功（含校验全过）; 1 用法错误; 2 未配置/无目标/配置损坏; 4 校验有失败
//
// 信任契约：本脚本不回显任何秘钥（url/appId/receiveId 只显示尾 4 位，
// secret/keyword 只显示有无）；接口以此为准，不需要阅读脚本源码。

import { getTenantToken } from "./lib/feishu.mjs";
import { ConfigError, UsageError, describeTarget, fail, loadConfig } from "./lib/shared.mjs";

const USAGE = `Usage: targets.mjs [--check]
  --check   逐个校验目标（app 换 token / webhook 校验 URL 形态），不发送消息
环境变量：FEISHU_NOTIFY_CONFIG 指定配置文件路径
退出码：0 成功 | 1 用法错误 | 2 配置问题 | 4 校验有失败`;

/** URL 形态校验：只看协议与可解析性，不猜测域名。 */
function checkWebhookUrl(target) {
  try {
    const url = new URL(target.url);
    return /^https?:$/.test(url.protocol)
      ? { ok: true, note: "通过" }
      : { ok: false, note: "失败：URL 协议不是 http(s)" };
  } catch {
    return { ok: false, note: "失败：URL 格式不合法" };
  }
}

async function checkTarget(target) {
  if (target.type === "webhook") return checkWebhookUrl(target);
  if (target.type === "app") {
    await getTenantToken(target.appId, target.appSecret);
    return { ok: true, note: "通过（token 换取成功）" };
  }
  return { ok: false, note: `失败：未知类型 ${target.type}` };
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("--help") || argv.includes("-h")) {
    console.log(USAGE);
    return;
  }
  const check = argv.includes("--check");
  const bad = argv.filter((a) => a !== "--check");
  if (bad.length) throw new UsageError(`未知参数：${bad[0]}\n${USAGE}`);

  const config = loadConfig(); // 无配置文件/缺 targets → 退出 2（fail 附 configure 路径）
  const names = Object.keys(config.targets ?? {});
  if (!names.length) {
    // 有配置文件但零目标：同样是"未完成配置"
    throw new ConfigError("配置里没有任何目标，请运行 configure.mjs 添加目标。");
  }
  let failed = false;
  for (const name of names) {
    const target = config.targets[name];
    console.log(describeTarget(name, target, config.default === name));
    if (check) {
      const result = await checkTarget(target).catch((err) => ({ ok: false, note: `失败：${err.message}` }));
      if (!result.ok) failed = true;
      console.log(`  check: ${result.note}`);
    }
  }
  if (failed) process.exitCode = 4;
}

main().catch(fail);
