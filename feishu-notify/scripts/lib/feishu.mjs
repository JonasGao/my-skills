// 飞书开放平台客户端：webhook 签名、tenant token 缓存、消息发送、ID 发现、错误翻译。
// 纯 Node >= 18，零依赖。移植自 /home/god/ai-subscriptions 的通知模块
// （feishu-app.ts / payload.ts / signing.ts / feishu-helpers.ts / feishu-errors.ts）。
// token 与签名只存在于本进程内存（见 docs/adr/0004）。

import { createHmac } from "node:crypto";

const OPEN = "https://open.feishu.cn/open-apis";
const TOKEN_URL = `${OPEN}/auth/v3/tenant_access_token/internal`;
const SEND_URL = `${OPEN}/im/v1/messages`;
const CHATS_URL = `${OPEN}/im/v1/chats`;
const LOOKUP_URL = `${OPEN}/contact/v3/users/batch_get_id`;

export class FeishuError extends Error {
  constructor(code, msg) {
    super(translate(code, msg));
    this.code = code;
  }
}

const CODES = {
  99991400: "应用凭证或权限问题，请在开放平台检查应用凭证与权限",
  99991663: "tenant_access_token 无效（重试后仍失败），请检查应用凭证",
  99991664: "token 无效或已过期，请重试或检查凭证",
  99991665: "token 无效或已过期，请重试或检查凭证",
  99991668: "token 无效或已过期，请重试或检查凭证",
  99991672: "机器人缺少所需权限，请在飞书开放平台为应用开通对应 scope",
  230001: "token 无效，请检查凭证",
  230002: "应用权限不足，请检查应用 scope",
  19001: "webhook 地址无效或已被删除，请到群机器人设置重新获取",
  19021: "签名校验失败：secret 不对，或消息缺少关键词",
  10003: "参数错误，请检查 appId / receiveId 等字段是否正确",
  10014: "app_id 不存在，请检查 appId",
};

function translate(code, msg) {
  const m = String(msg ?? "");
  if (/receive.?id/i.test(m)) return `飞书错误 ${code ?? "?"}：接收方 ID 无效，请检查 receiveId`;
  if (/key ?word/i.test(m)) return `飞书错误：关键词不匹配（${m}）`;
  if (/sign/i.test(m)) return `飞书错误：签名不匹配（${m}）`;
  if (code in CODES) return `飞书错误 ${code}：${CODES[code]}`;
  return `飞书错误 ${code ?? "?"}：${m || "未知错误"}`;
}

/** 统一 fetch + JSON；网络层异常不回带 URL 等原文（防泄露，见 ADR 0004）。 */
async function feishuJson(url, init) {
  let res;
  try {
    res = await fetch(url, init);
  } catch {
    throw new FeishuError(null, "网络请求失败（无法连接接口，请检查网络）");
  }
  let data;
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  return { res, data };
}

/** 群机器人签名：HMAC-SHA256，key = `${timestamp}\n${secret}`，空串为被签数据。 */
export function webhookSign(secret, timestampSec) {
  return createHmac("sha256", `${timestampSec}\n${secret}`).update("").digest("base64");
}

// tenant token 缓存：按 appId 键控，提前 5 分钟视为过期
const tokenCache = new Map();

export async function getTenantToken(appId, appSecret, { force = false } = {}) {
  const hit = tokenCache.get(appId);
  if (!force && hit && hit.expireAt - 5 * 60_000 > Date.now()) return hit.token;
  const { res, data } = await feishuJson(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
  });
  if (data.code !== 0 || !data.tenant_access_token) {
    throw new FeishuError(data.code ?? res.status, data.msg || "获取 tenant_access_token 失败");
  }
  tokenCache.set(appId, {
    token: data.tenant_access_token,
    expireAt: Date.now() + (data.expire ?? 7200) * 1000,
  });
  return data.tenant_access_token;
}

/** Markdown 卡片：plain_text 头 + 单个 markdown 元素（ai-subscriptions 同款结构）。 */
export function buildCard(title, markdown) {
  return {
    config: { wide_screen_mode: true },
    header: { title: { tag: "plain_text", content: title } },
    elements: [{ tag: "markdown", content: markdown }],
  };
}

/** 经群机器人 webhook 发送；关键词模式的织入由调用方完成。 */
export async function sendWebhook(target, { text, card }) {
  const payload = card
    ? { msg_type: "interactive", card }
    : { msg_type: "text", content: { text } };
  if (target.secret) {
    const timestamp = Math.floor(Date.now() / 1000).toString();
    payload.timestamp = timestamp;
    payload.sign = webhookSign(target.secret, timestamp);
  }
  const { res, data } = await feishuJson(target.url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok || (data.code !== undefined && data.code !== 0)) {
    throw new FeishuError(data.code ?? res.status, data.msg || `HTTP ${res.status}`);
  }
  return data;
}

/** 经自建应用机器人发送；token 失效（401 / 99991663）强刷后重试一次。 */
export async function sendApp(target, { text, card }) {
  const content = card
    ? { msg_type: "interactive", content: JSON.stringify(card) }
    : { msg_type: "text", content: JSON.stringify({ text }) };
  const body = { receive_id: target.receiveId, ...content };
  for (let attempt = 0; ; attempt++) {
    const token = await getTenantToken(target.appId, target.appSecret, { force: attempt > 0 });
    const { res, data } = await feishuJson(`${SEND_URL}?receive_id_type=${target.receiveIdType}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    });
    if (res.ok && data.code === 0) return data;
    const staleToken = res.status === 401 || data.code === 99991663;
    if (staleToken && attempt === 0) continue;
    throw new FeishuError(data.code ?? res.status, data.msg || `HTTP ${res.status}`);
  }
}

/** 按目标类型分派发送。 */
export function sendToTarget(target, message) {
  return target.type === "webhook"
    ? sendWebhook(target, message)
    : sendApp(target, message);
}

/** 列出应用机器人所在的群（chat_id 发现用）。 */
export async function listChats(appId, appSecret) {
  const token = await getTenantToken(appId, appSecret);
  const chats = [];
  let pageToken = "";
  do {
    const url = new URL(CHATS_URL);
    url.searchParams.set("page_size", "20");
    if (pageToken) url.searchParams.set("page_token", pageToken);
    const { res, data } = await feishuJson(url, { headers: { Authorization: `Bearer ${token}` } });
    if (data.code !== 0) throw new FeishuError(data.code, data.msg || `HTTP ${res.status}`);
    chats.push(...(data.data?.items ?? []));
    pageToken = data.data?.page_token ?? "";
  } while (pageToken);
  return chats.map((c) => ({ chatId: c.chat_id, chatType: c.chat_type, name: c.name ?? "(未命名)" }));
}

/** 列出会话内消息（新→旧），只取 message_id 与发送者（open_id 发现用）。 */
export async function listChatMessages(appId, appSecret, chatId) {
  const token = await getTenantToken(appId, appSecret);
  const url = new URL(SEND_URL); // /im/v1/messages 同时也是消息列表端点
  url.searchParams.set("container_id_type", "chat");
  url.searchParams.set("container_id", chatId);
  url.searchParams.set("sort_type", "ByCreateTimeDesc");
  url.searchParams.set("page_size", "20");
  const { res, data } = await feishuJson(url, { headers: { Authorization: `Bearer ${token}` } });
  if (data.code !== 0) throw new FeishuError(data.code, data.msg || `HTTP ${res.status}`);
  return (data.data?.items ?? []).map((m) => ({
    messageId: m.message_id,
    senderOpenId: m.sender?.id_type && m.sender.id_type !== "open_id" ? undefined : m.sender?.id,
  }));
}

/** 手机号或邮箱 → 用户 ID（open_id）；查不到返回 null。 */
export async function lookupUserId(appId, appSecret, { phone, email } = {}) {
  const token = await getTenantToken(appId, appSecret);
  const body = {};
  if (phone) body.mobiles = [phone];
  if (email) body.emails = [email];
  const { res, data } = await feishuJson(`${LOOKUP_URL}?user_id_type=open_id`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (data.code !== 0) throw new FeishuError(data.code, data.msg || `HTTP ${res.status}`);
  return data.data?.user_list?.find((u) => u.user_id)?.user_id ?? null;
}
