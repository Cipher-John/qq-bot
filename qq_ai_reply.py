#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NapCat QQ 私聊 AI 自动回复脚本（HTTP 反向推送模式）
- 启动 HTTP 服务器，NapCat 有新消息时 POST 过来
- 调用 DeepSeek API 生成回复
- 通过 NapCat HTTP API 发回消息
"""

import json
import http.server
import urllib.request
import threading
import time
from datetime import datetime

# ============ 配置区 ============
# NapCat HTTP API
NAPCAT_API = "http://127.0.0.1:3000"
NAPCAT_TOKEN = "RNrhOEIo20Da.V12"  # HTTP 服务器 token

# DeepSeek API
AI_API_URL = "https://api.deepseek.com/v1/chat/completions"
AI_API_KEY = ""
AI_MODEL = "deepseek-chat"

# 私聊白名单（留空 = 回复所有人）
AUTO_REPLY_USERS = []

# 群聊白名单（留空 = 不回复任何群）
AUTO_REPLY_GROUPS = []

# 黑名单
BLOCKED_USERS = []

# 自己的 QQ 号
MY_QQ = "1065922680"

# ---- 私聊 Prompt ----
PRIVATE_SYSTEM_PROMPT = (
    "你现在要伪装成用户自身，用自然的中文回复，像真人朋友一样。"
    "现在你需要回复的用户是该用户的女朋友，请用亲密但不冒犯的发言回复。"
    "简洁，如果一句话超过10个字，分成两段话逐段发送。"
    "不需要有标点符号，遇到标点符号直接分段。"
    "不透露你是 AI。"
)

# ---- 群聊 Prompt ----
GROUP_SYSTEM_PROMPT = (
    "你是一个活跃的群聊成员，用自然的中文参与群聊讨论。"
    "回复风格轻松有趣，像真人水群一样，可以适当用梗。"
    "简洁，如果一句话超过10个字，分成两段话逐段发送。"
    "不需要有标点符号，遇到标点符号直接分段。"
    "不透露你是 AI。"
    "如果群友在闲聊，可以附和或接梗；如果是在提问，认真回答但保持轻松语气。"
)

# 回复最大字数
MAX_REPLY_LENGTH = 200

# HTTP 服务端口（需在 NapCat WebUI -> HTTP客户端 中配置此地址）
LISTEN_PORT = 8080
# ===================================


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def call_ai(user_msg: str, chat_type: str = "private") -> str:
    """调用 DeepSeek API
    chat_type: "private" 或 "group"
    """
    if not AI_API_KEY:
        return f"[自动回复] 收到：{user_msg[:40]}... 稍后详聊~"

    system_prompt = PRIVATE_SYSTEM_PROMPT if chat_type == "private" else GROUP_SYSTEM_PROMPT

    payload = json.dumps({
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        "max_tokens": 300,
        "temperature": 0.8,
    }).encode("utf-8")

    req = urllib.request.Request(
        AI_API_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AI_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()[:MAX_REPLY_LENGTH]
    except Exception as e:
        log(f"[AI] {e}")
        return "抱歉，api余额不足"


def send_qq(target_qq: str, message: str):
    """发送 QQ 私聊消息"""
    url = f"{NAPCAT_API}/send_private_msg"
    body = json.dumps({"user_id": int(target_qq), "message": message}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": f"Bearer {NAPCAT_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            ok = "成功" if result.get("status") == "ok" else f"失败({result.get('message','?')})"
            log(f"[发送{ok}] -> {target_qq}: {message[:30]}...")
    except Exception as e:
        log(f"[发送异常] {e}")


def send_group(group_id: str, message: str):
    """发送 QQ 群消息"""
    url = f"{NAPCAT_API}/send_group_msg"
    body = json.dumps({"group_id": int(group_id), "message": message}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": f"Bearer {NAPCAT_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            ok = "成功" if result.get("status") == "ok" else f"失败({result.get('message','?')})"
            log(f"[群发{ok}] -> 群{group_id}: {message[:30]}...")
    except Exception as e:
        log(f"[群发异常] {e}")


def process_message(data: dict):
    """处理消息（私聊 + 群聊）"""
    post_type = data.get("post_type", "")
    msg_type = data.get("message_type", "")

    if post_type != "message":
        return

    # ---- 私聊 ----
    if msg_type == "private":
        user_id = str(data.get("user_id", data.get("sender", {}).get("user_id", "")))
        raw = data.get("raw_message", data.get("message", ""))
        if not user_id or not raw:
            return
        if user_id == MY_QQ:
            return
        if user_id in [str(u) for u in BLOCKED_USERS]:
            return
        if AUTO_REPLY_USERS and user_id not in [str(u) for u in AUTO_REPLY_USERS]:
            return
        log(f"[私聊] {user_id}: {raw[:50]}")
        reply = call_ai(raw, chat_type="private")
        time.sleep(1.5)
        send_qq(user_id, reply)
        return

    # ---- 群聊 ----
    if msg_type == "group":
        group_id = str(data.get("group_id", ""))
        user_id = str(data.get("user_id", data.get("sender", {}).get("user_id", "")))
        raw = data.get("raw_message", data.get("message", ""))
        if not group_id or not raw:
            return
        if user_id == MY_QQ:
            return
        if user_id in [str(u) for u in BLOCKED_USERS]:
            return
        if group_id not in [str(g) for g in AUTO_REPLY_GROUPS]:
            return  # 不在群白名单，忽略
        log(f"[群聊] 群{group_id} {user_id}: {raw[:50]}")
        reply = call_ai(raw, chat_type="group")
        time.sleep(1.5)
        send_group(group_id, reply)
        return


class Handler(http.server.BaseHTTPRequestHandler):
    def _read_body(self):
        """读取 POST body，支持 Content-Length 和 chunked"""
        if self.headers.get("Transfer-Encoding") == "chunked":
            # 手动解析 chunked body
            chunks = []
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                size_hex = line.strip()
                if size_hex == b"":
                    continue
                chunk_size = int(size_hex, 16)
                if chunk_size == 0:
                    self.rfile.readline()  # skip trailing \r\n
                    break
                chunk = self.rfile.read(chunk_size)
                self.rfile.readline()  # skip trailing \r\n
                chunks.append(chunk)
            return b"".join(chunks)

        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            return self.rfile.read(length)
        return b""

    def do_POST(self):
        for k, v in self.headers.items():
            log(f"  [Header] {k}: {v}")

        body = self._read_body()
        log(f"  [Body] len={len(body)}")

        if len(body) == 0:
            self._reply(200)
            return

        # 解压 gzip
        if self.headers.get("Content-Encoding") == "gzip":
            import gzip
            body = gzip.decompress(body)

        try:
            raw_text = body.decode("utf-8")
            data = json.loads(raw_text)
            log(f"[推送] type={data.get('post_type','?')} msg={data.get('message_type','?')} preview={raw_text[:80]}")
            threading.Thread(target=process_message, args=(data,), daemon=True).start()
            self._reply(200)
        except Exception as e:
            import traceback
            log(f"[异常] {e}")
            log(f"[RAW] {body[:300]}")
            self._reply(200)

    def _reply(self, code):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args):
        pass


def main():
    log("=" * 50)
    log("  NapCat QQ AI 自动回复 (DeepSeek)")
    log("=" * 50)
    log(f"  HTTP API  : {NAPCAT_API}")
    log(f"  监听端口  : {LISTEN_PORT}")
    log(f"  AI       : {'DeepSeek' if AI_API_KEY else '固定回复（填 Key 后重启）'}")
    log(f"  QQ       : {MY_QQ}")
    log("=" * 50)
    log("")
    log("[重要] NapCat WebUI -> 网络配置 -> HTTP客户端 -> 新建:")
    log(f"       URL: http://127.0.0.1:{LISTEN_PORT}")
    log("")

    server = http.server.HTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    log(f"[启动] 等待 NapCat 推送消息...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("[关闭] 已停止。")


if __name__ == "__main__":
    main()
