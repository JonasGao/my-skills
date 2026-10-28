// 飞书事件长连接（WebSocket）最小客户端：私聊消息抓取 open_id 用。
// 零依赖：协议逆向自 @larksuiteoapi/node-sdk 1.74.0 的 pbbp2.Frame。
// 流程：POST /callback/ws/endpoint {AppID, AppSecret} → 预授权 wss URL
// （device_id/service_id 在 query 里，连接无需自定义 header）→ 按
// PingInterval 发 control/ping 帧 → data 帧 payload 是事件 JSON，
// 取 im.message.receive_v1 且 chat_type=p2p 的发送者 open_id。
// 前提（控制台一次性配置）：事件订阅方式=长连接；订阅 im.message.receive_v1；
// 权限 im:message.p2p_msg:readonly。需要 Node >= 22（内置 WebSocket）。

import { FeishuError, sendApp } from "./feishu.mjs";

const ENDPOINT_URL = "https://open.feishu.cn/callback/ws/endpoint";

// --- 极简 protobuf：pbbp2.Frame / Header 编解码 ---
class BW {
  constructor() { this.chunks = []; }
  varint(v) {
    v = Number(v);
    const b = [];
    do { let x = v & 0x7f; v = Math.floor(v / 128); if (v > 0) x |= 0x80; b.push(x); } while (v > 0);
    this.chunks.push(Uint8Array.from(b));
  }
  tag(id, wt) { this.varint((id << 3) | wt); }
  str(id, s) { this.tag(id, 2); const b = new TextEncoder().encode(s); this.varint(b.length); this.chunks.push(b); }
  bytes(id, b) { this.tag(id, 2); this.varint(b.length); this.chunks.push(b); }
  message(id, fn) { this.tag(id, 2); const w = new BW(); fn(w); const b = w.finish(); this.varint(b.length); this.chunks.push(b); }
  finish() { let n = 0; for (const c of this.chunks) n += c.length; const out = new Uint8Array(n); let i = 0; for (const c of this.chunks) { out.set(c, i); i += c.length; } return out; }
}

function encodeFrame(f) {
  const w = new BW();
  if (f.SeqID) { w.tag(1, 0); w.varint(f.SeqID); }
  if (f.LogID) { w.tag(2, 0); w.varint(f.LogID); }
  if (f.service != null) { w.tag(3, 0); w.varint(f.service); }
  if (f.method != null) { w.tag(4, 0); w.varint(f.method); }
  for (const h of f.headers ?? []) w.message(5, (hw) => { hw.str(1, h.key); hw.str(2, h.value); });
  if (f.payloadEncoding) w.str(6, f.payloadEncoding);
  if (f.payloadType) w.str(7, f.payloadType);
  if (f.payload) w.bytes(8, f.payload);
  if (f.LogIDNew) w.str(9, f.LogIDNew);
  return w.finish();
}

class BR {
  constructor(buf) { this.buf = buf; this.pos = 0; }
  get len() { return this.buf.length; }
  varint() { let v = 0, shift = 0, x; do { x = this.buf[this.pos++]; v += (x & 0x7f) * 2 ** shift; shift += 7; } while (x & 0x80); return v; }
  bytesVal() { const l = this.varint(); const b = this.buf.subarray(this.pos, this.pos + l); this.pos += l; return b; }
}

function decodeFrame(buf) {
  const r = new BR(buf);
  const f = { headers: [] };
  while (r.pos < r.len) {
    const tag = r.varint(); const id = tag >>> 3; const wt = tag & 7;
    if (wt === 0) {
      const v = r.varint();
      if (id === 1) f.SeqID = v; else if (id === 2) f.LogID = v; else if (id === 3) f.service = v; else if (id === 4) f.method = v;
    } else if (wt === 2) {
      const b = r.bytesVal();
      if (id === 5) {
        const hr = new BR(b); const h = {};
        while (hr.pos < hr.len) {
          const ht = hr.varint(); const hid = ht >>> 3;
          if ((ht & 7) === 2) { const s = new TextDecoder().decode(hr.bytesVal()); if (hid === 1) h.key = s; else if (hid === 2) h.value = s; }
        }
        f.headers.push(h);
      } else if (id === 6) f.payloadEncoding = new TextDecoder().decode(b);
      else if (id === 7) f.payloadType = new TextDecoder().decode(b);
      else if (id === 8) f.payload = b;
      else if (id === 9) f.LogIDNew = new TextDecoder().decode(b);
    } else if (wt === 5) r.pos += 4;
    else if (wt === 1) r.pos += 8;
    else throw new Error(`未知 wire type ${wt}`);
  }
  return f;
}

/**
 * 临时长连接会话：等用户给机器人发一条私聊消息，返回 { openId, chatId }；
 * 超时返回 null。进度直接打到 stdout（configure 交互用）。
 */
export async function listenDirectMessage(appId, appSecret, { timeoutMs = 90_000 } = {}) {
  if (typeof WebSocket === "undefined") {
    throw new FeishuError(null, "当前 Node 不支持内置 WebSocket（需 Node >= 22），请改用群聊抓取或手机号查询");
  }
  const res = await fetch(ENDPOINT_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", locale: "zh" },
    body: JSON.stringify({ AppID: appId, AppSecret: appSecret }),
  });
  const cfg = await res.json().catch(() => ({}));
  if (cfg.code !== 0) {
    throw new FeishuError(cfg.code ?? res.status, cfg.msg || "获取长连接 endpoint 失败");
  }
  const pingSec = cfg.data.ClientConfig?.PingInterval ?? 30;
  const serviceId = Number(new URL(cfg.data.URL).searchParams.get("service_id") ?? 0);

  console.log("长连接就绪，连接飞书…");
  const hit = await new Promise((resolve, reject) => {
    let ws;
    let pingTimer;
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearInterval(pingTimer);
      clearTimeout(timer);
      try { ws?.close(); } catch { /* best effort */ }
      resolve(value);
    };
    const timer = setTimeout(() => {
      console.log("\n  超时没等到私聊事件。请确认控制台已配置：订阅方式=长连接、订阅 im.message.receive_v1、权限 im:message.p2p_msg:readonly。");
      finish(null);
    }, timeoutMs);
    try {
      ws = new WebSocket(cfg.data.URL);
    } catch (err) {
      clearTimeout(timer);
      reject(new FeishuError(null, `长连接建立失败：${err.message}`));
      return;
    }
    ws.binaryType = "arraybuffer";
    ws.addEventListener("open", () => {
      console.log("已连接。请现在给机器人发一条私聊消息（内容不限）。");
      const ping = () => { try { ws.send(encodeFrame({ service: serviceId, method: 0, headers: [{ key: "type", value: "ping" }] })); } catch { /* best effort */ } };
      ping();
      pingTimer = setInterval(ping, pingSec * 1000);
    });
    ws.addEventListener("message", (ev) => {
      let frame;
      try {
        frame = decodeFrame(new Uint8Array(ev.data));
      } catch {
        return;
      }
      if (frame.method !== 1) return;
      const headers = Object.fromEntries(frame.headers.map((h) => [h.key, h.value]));
      if (headers.type !== "event") return;
      try {
        // ack：让飞书知道事件已处理
        ws.send(encodeFrame({
          service: serviceId, method: 1,
          headers: [...frame.headers, { key: "biz_rt", value: "1" }],
          payload: new TextEncoder().encode(JSON.stringify({ code: 200 })),
        }));
      } catch { /* best effort */ }
      let body;
      try {
        body = JSON.parse(new TextDecoder().decode(frame.payload));
      } catch {
        return;
      }
      if (body?.header?.event_type !== "im.message.receive_v1") return;
      const msg = body.event?.message ?? {};
      const openId = body.event?.sender?.sender_id?.open_id;
      if (msg.chat_type === "p2p" && openId) {
        console.log(`  收到私聊消息，open_id：${openId}`);
        finish({ openId, chatId: msg.chat_id });
      }
    });
    ws.addEventListener("error", () => {
      if (!settled) {
        settled = true;
        clearInterval(pingTimer);
        clearTimeout(timer);
        reject(new FeishuError(null, "长连接出错（网络或 endpoint 无效）"));
      }
    });
    ws.addEventListener("close", () => {
      if (!settled) {
        settled = true;
        clearInterval(pingTimer);
        clearTimeout(timer);
        reject(new FeishuError(null, "长连接被关闭"));
      }
    });
  });
  if (!hit) return null;
  // 立刻在私聊里回复抓取结果，让用户不用回到终端确认
  try {
    await sendApp(
      { appId, appSecret, receiveIdType: "open_id", receiveId: hit.openId },
      { text: `✅ 抓取成功\n\nopen_id：${hit.openId}` }
    );
    console.log("  已在私聊里回复抓取结果。");
  } catch (err) {
    console.log(`  私聊回复失败（${err.message}），以终端结果为准。`);
  }
  return hit;
}
