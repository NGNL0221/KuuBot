import json
import time
import os
import base64
import io
import threading
import requests
import websocket

WS_URL = "wss://api.sgroup.qq.com/websocket"
API_BASE = "https://api.sgroup.qq.com"
HEARTBEAT_INTERVAL = 30


class QQBot:
    def __init__(self, app_id: str, app_secret: str, on_message):
        self._app_id = app_id
        self._secret = app_secret
        self._on_message = on_message
        self._ws = None
        self._token = None
        self._running = False
        self._seq = 0
        self._session_id = ""

    def _get_token(self):
        resp = requests.post(
            "https://bots.qq.com/app/getAppAccessToken",
            json={"appId": self._app_id, "clientSecret": self._secret},
        )
        data = resp.json()
        print(f"[QQBot] Token resp: {data}")
        self._token = data.get("access_token", "")

    def _api_headers(self):
        return {
            "Authorization": f"QQBot {self._token}",
            "Content-Type": "application/json",
        }

    def _send_ws(self, op: int, d: dict):
        payload = json.dumps({"op": op, "d": d}, ensure_ascii=False)
        if self._ws:
            print(f"[QQBot] Send op={op} d={d}")
            self._ws.send(payload)

    def _heartbeat(self):
        while self._running:
            time.sleep(HEARTBEAT_INTERVAL)
            if self._ws and self._running:
                try:
                    self._send_ws(1, self._seq)
                except:
                    pass

    def _on_ws_message(self, ws, raw):
        try:
            msg = json.loads(raw)
        except:
            return
        op = msg.get("op", 0)
        d = msg.get("d", {})
        s = msg.get("s")
        if s:
            self._seq = s

        print(f"[QQBot] Recv op={op} t={msg.get('t','')}")

        if op == 10:  # HELLO
            self._send_ws(2, {
                "token": f"QQBot {self._token}",
                "intents": 1 << 25,  # C2C messages
                "shard": [0, 1],
            })
        elif op == 0:  # DISPATCH
            t = msg.get("t", "")
            if t in ("C2C_MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE"):
                author = d.get("author", {})
                openid = author.get("id", "")
                content = d.get("content", "")
                msg_id = d.get("id", "")
                threading.Thread(
                    target=self._on_message,
                    args=(openid, content, msg_id),
                    daemon=True,
                ).start()

    def _on_ws_error(self, ws, error):
        print(f"[QQBot] WS error: {error}")

    def _on_ws_close(self, ws, code, msg):
        print(f"[QQBot] WS closed: {code} {msg}")
        if self._running:
            time.sleep(3)
            self._connect()

    def _connect(self):
        try:
            self._get_token()
            self._ws = websocket.WebSocketApp(
                WS_URL,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close,
            )
            self._ws.run_forever()
        except Exception as e:
            print(f"[QQBot] Connect error: {e}")
            if self._running:
                time.sleep(5)
                self._connect()

    def send_message(self, openid: str, content: str, msg_id: str = ""):
        try:
            resp = requests.post(
                f"{API_BASE}/v2/users/{openid}/messages",
                headers=self._api_headers(),
                json={
                    "msg_type": 2,
                    "markdown": {"content": content[:5000]},
                    "msg_id": msg_id,
                },
                timeout=20,
            )
            return resp.status_code == 200
        except Exception as e:
            print(f"[QQBot] Send error: {e}")
            return False

    def send_image(self, openid: str, file_path: str) -> tuple:
        try:
            from PIL import Image
            img = Image.open(file_path)
            img.thumbnail((160, 160))
            buf = io.BytesIO()
            img.save(buf, "PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            # Step 1: Upload to get file_info
            resp = requests.post(
                f"{API_BASE}/v2/users/{openid}/files",
                headers={"Authorization": f"QQBot {self._token}"},
                json={"file_type": 1, "file_data": b64},
                timeout=30,
            )
            if resp.status_code != 200:
                return False, f"上传失败 {resp.status_code}"
            file_info = resp.json().get("file_info", "")
            if not file_info:
                return False, "未获取到 file_info"
            # Step 2: Send media message
            resp2 = requests.post(
                f"{API_BASE}/v2/users/{openid}/messages",
                headers=self._api_headers(),
                json={"msg_type": 7, "media": {"file_info": file_info}},
                timeout=20,
            )
            if resp2.status_code == 200:
                return True, "ok"
            return False, f"发送失败 {resp2.status_code}"
        except Exception as e:
            return False, str(e)[:100]

    def start(self):
        self._running = True
        threading.Thread(target=self._heartbeat, daemon=True).start()
        threading.Thread(target=self._connect, daemon=True).start()

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.close()
