// feishu-notify 共享模块：配置读写、目标解析、掩码摘要与统一失败出口。
// 纯 Node >= 18，零依赖。本模块的任何输出不得出现秘钥明文（见 docs/adr/0004）。

import { homedir } from "node:os";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const CONFIG_ENV = "FEISHU_NOTIFY_CONFIG";

export class UsageError extends Error {}
export class ConfigError extends Error {}
export class TargetError extends Error {}

/** configure.mjs 的绝对路径（未配置时原样打印给用户，由用户在自己终端运行）。 */
export function configureScriptPath() {
  return join(dirname(fileURLToPath(import.meta.url)), "..", "configure.mjs");
}

/** 统一失败出口：中文错误 + 退出码（1 用法 / 2 配置 / 3 目标 / 4 其他失败）。 */
export function fail(err) {
  if (err instanceof ConfigError) {
    console.error(`${err.message}\n请在自己的终端运行: node ${configureScriptPath()}`);
    process.exitCode = 2;
    return;
  }
  console.error(err instanceof Error ? err.message : String(err));
  process.exitCode =
    err instanceof UsageError ? 1 : err instanceof TargetError ? 3 : 4;
}

/** 掩码：最多露出尾 4 位；空值显示「无」。 */
export function mask(value) {
  if (typeof value !== "string" || value.length === 0) return "无";
  if (value.length <= 8) return "****";
  return "****" + value.slice(-4);
}

/** 单目标的一行掩码摘要（keyword 按 ADR 0004 视为凭证，只显示有无）。 */
export function describeTarget(name, target, isDefault = false) {
  const tag = isDefault ? " (default)" : "";
  if (target.type === "webhook") {
    return [
      `${name}${tag}`, "webhook",
      `url=${mask(target.url)}`,
      `secret=${target.secret ? "有" : "无"}`,
      `keyword=${target.keyword ? "有" : "无"}`,
    ].join("  ");
  }
  if (target.type === "app") {
    return [
      `${name}${tag}`, "app",
      `appId=${mask(target.appId)}`,
      `appSecret=${target.appSecret ? "有" : "无"}`,
      `receiveIdType=${target.receiveIdType ?? "?"}`,
      `receiveId=${target.receiveId ? mask(target.receiveId) : "无"}`,
    ].join("  ");
  }
  return `${name}${tag}  未知类型：${target.type}`;
}

export function configPath() {
  return process.env[CONFIG_ENV] || join(homedir(), ".config", "feishu-notify", "config.json");
}

/** 读取并做结构校验；文件缺失且非必需时返回 null。 */
export function loadConfig({ required = true } = {}) {
  const path = configPath();
  if (!existsSync(path)) {
    if (required) {
      throw new ConfigError(
        `配置文件不存在（${path}）。请由用户在自己的终端运行 configure.mjs 初始化；` +
          "Agent 不要代跑、不要读取或填写任何凭证。"
      );
    }
    return null;
  }
  let raw;
  try {
    raw = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    // 不带 err.message：解析错误信息可能引用配置文件原文
    throw new ConfigError(`配置文件不是合法 JSON（${path}），请重新运行 configure.mjs。`);
  }
  const { targets } = raw ?? {};
  if (!targets || typeof targets !== "object" || Array.isArray(targets)) {
    throw new ConfigError(`配置文件缺少 targets 对象（${path}），请重新运行 configure.mjs。`);
  }
  return raw;
}

/** 保存配置：自动建父目录，权限 0600；调用方负责只覆盖自己管理的键。 */
export function saveConfig(config) {
  const path = configPath();
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(config, null, 2) + "\n", { mode: 0o600 });
  try {
    chmodSync(path, 0o600); // 部分平台忽略 writeFileSync 的 mode
  } catch {
    // best effort；文件已写入
  }
}

/** 解析单个目标并校验其字段。 */
export function resolveTarget(config, name) {
  const target = config.targets?.[name];
  if (!target) {
    throw new TargetError(
      `目标不存在：${name}。已配置的目标：${Object.keys(config.targets ?? {}).join(", ") || "（无）"}`
    );
  }
  if (target.type === "webhook") {
    if (!target.url || !/^https?:\/\//.test(target.url)) {
      throw new TargetError(`目标 ${name} 的 url 缺失或不是 http(s) 地址。`);
    }
    try {
      new URL(target.url);
    } catch {
      throw new TargetError(`目标 ${name} 的 url 不是合法地址。`);
    }
  } else if (target.type === "app") {
    for (const field of ["appId", "appSecret", "receiveIdType", "receiveId"]) {
      if (!target[field]) throw new TargetError(`目标 ${name}（app）缺少字段：${field}`);
    }
    if (!["open_id", "chat_id"].includes(target.receiveIdType)) {
      throw new TargetError(`目标 ${name} 的 receiveIdType 必须是 open_id 或 chat_id。`);
    }
  } else {
    throw new TargetError(`目标 ${name} 的 type 必须是 webhook 或 app。`);
  }
  return target;
}

/** default 目标名；必须显式配置，不隐式回退到唯一目标。 */
export function defaultTargetName(config) {
  if (config.default && config.targets[config.default]) return config.default;
  throw new ConfigError(
    `配置里没有可用的 default 目标（现有目标：${Object.keys(config.targets ?? {}).join(", ") || "无"}）。` +
      "请用 --target 指定，或运行 configure.mjs 设置 default。"
  );
}
