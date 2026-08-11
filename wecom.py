"""
企业微信消息推送模块

新版：基于企业微信「智能机器人长连接」模式，通过 WebSocket 主动推送日报。
- WebSocket 地址：wss://openws.work.weixin.qq.com
- 订阅帧：aibot_subscribe（bot_id + secret）
- 主动推送帧：aibot_send_msg（chatid + markdown）
- 心跳帧：ping / pong

保留旧的群机器人 Webhook 与企业微信应用 appchat 逻辑作为兼容降级。
"""

import json
import time
import uuid
import hmac
import hashlib
import base64
import threading
import logging
from pathlib import Path
from typing import Dict, Optional, Callable

import requests

# 优先导入 websocket-client；若未安装，给出友好提示
try:
    import websocket
except ImportError as _e:  # pragma: no cover
    raise ImportError(
        "企业微信长连接需要 websocket-client 包，请执行：pip install websocket-client"
    ) from _e


DATA_DIR = Path("data")
WECOM_CONFIG_FILE = DATA_DIR / "wecom_config.json"
WS_URL = "wss://openws.work.weixin.qq.com"
HEARTBEAT_INTERVAL = 30  # 秒，与官方建议一致

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------

def _ensure_dir():
    DATA_DIR.mkdir(exist_ok=True)


def _config_chat_id(config: Dict) -> str:
    """读取企微会话 ID，兼容历史 chatid 与前端使用的 chat_id。"""
    for key in ("chat_id", "chatid"):
        value = str(config.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalize_wecom_config(config: Dict) -> Dict:
    """统一保存两种字段名，避免旧配置覆盖用户刚填写的新 ID。"""
    normalized = dict(config or {})
    chat_id = _config_chat_id(normalized)
    if chat_id:
        normalized["chat_id"] = chat_id
        normalized["chatid"] = chat_id
    return normalized


def load_wecom_config() -> Dict:
    """加载企业微信配置"""
    _ensure_dir()
    if not WECOM_CONFIG_FILE.exists():
        return {}
    try:
        return _normalize_wecom_config(json.loads(WECOM_CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:
        return {}


def save_wecom_config(config: Dict):
    """保存企业微信配置"""
    _ensure_dir()
    WECOM_CONFIG_FILE.write_text(
        json.dumps(_normalize_wecom_config(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# WebSocket 长连接客户端（同步 API）
# ---------------------------------------------------------------------------

class WeComAIBotClient:
    """
    企业微信智能机器人 WebSocket 长连接客户端。

    使用方式（一次性连接）：
        client = WeComAIBotClient(bot_id="...", secret="...")
        client.connect(timeout=10)
        client.send_markdown("# 你好", chatid="...")
        client.close()

    使用方式（监听群聊 ID）：
        def on_chatid(chatid):
            print("收到 chatid", chatid)

        client = WeComAIBotClient(bot_id="...", secret="...", on_chat_id=on_chatid)
        client.connect(timeout=10)
        time.sleep(60)
        client.close()
    """

    def __init__(
        self,
        bot_id: str,
        secret: str,
        chat_id: Optional[str] = None,
        chat_type: int = 2,
        on_chat_id: Optional[Callable[[str], None]] = None,
    ):
        self.bot_id = bot_id
        self.secret = secret
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.on_chat_id = on_chat_id

        self.ws_app: Optional[websocket.WebSocketApp] = None
        self.ws: Optional[websocket.WebSocket] = None
        self._thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

        self._connected = threading.Event()
        self._authenticated = threading.Event()
        self._shutdown = threading.Event()
        self._pending: Dict[str, Dict] = {}  # req_id -> {"event": Event, "response": dict}
        self._lock = threading.Lock()
        self._reconnect_delay = 1

    # ---------- 内部工具 ----------

    def _build_frame(self, cmd: str, body: dict) -> dict:
        return {
            "cmd": cmd,
            "headers": {"req_id": str(uuid.uuid4())},
            "body": body,
        }

    def _send_frame(self, frame: dict) -> bool:
        if self.ws is None or self.ws.sock is None or not self.ws.sock.connected:
            return False
        try:
            self.ws.send(json.dumps(frame, ensure_ascii=False))
            return True
        except Exception as exc:
            logger.warning("WebSocket 发送失败: %s", exc)
            return False

    def _send_and_wait(self, frame: dict, timeout: float) -> dict:
        """发送帧并等待响应（按 req_id 匹配）"""
        req_id = frame["headers"]["req_id"]
        event = threading.Event()
        with self._lock:
            self._pending[req_id] = {"event": event, "response": {}}

        try:
            if not self._connected.wait(timeout=timeout):
                raise TimeoutError("等待 WebSocket 连接超时")

            if not self._send_frame(frame):
                raise RuntimeError("WebSocket 发送失败，连接已断开")

            if not event.wait(timeout=timeout):
                raise TimeoutError("等待企业微信响应超时")

            with self._lock:
                entry = self._pending.pop(req_id, None)
            return entry["response"] if entry else {}
        except Exception:
            with self._lock:
                self._pending.pop(req_id, None)
            raise

    def _start_heartbeat(self):
        """启动心跳线程"""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        def heartbeat():
            while not self._shutdown.is_set():
                time.sleep(HEARTBEAT_INTERVAL)
                if self._shutdown.is_set():
                    break
                if not self._authenticated.is_set():
                    continue
                ping_frame = self._build_frame("ping", {})
                if not self._send_frame(ping_frame):
                    logger.warning("心跳发送失败，连接可能已断开")

        self._heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        self._heartbeat_thread.start()

    # ---------- WebSocket 回调 ----------

    def _on_open(self, ws):
        self.ws = ws
        self._connected.set()
        self._reconnect_delay = 1
        logger.info("WeCom WebSocket 已连接")

    def _on_message(self, _ws, message: str):
        logger.debug("收到消息: %s", message)
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("收到非 JSON 消息: %s", message)
            return

        headers = data.get("headers", {})
        req_id = headers.get("req_id")

        # 1. 按 req_id 匹配 pending 响应（订阅响应、发送响应等）
        if req_id:
            with self._lock:
                entry = self._pending.get(req_id)
            if entry is not None:
                entry["response"] = data
                entry["event"].set()
                return

        # 2. 处理服务端主动推送：消息回调 / 事件回调
        body = data.get("body", {})
        cmd = data.get("cmd")

        if cmd == "aibot_msg_callback":
            # 群聊返回 chatid，单聊通常不返回 chatid，使用 from.userid
            chatid = body.get("chatid") or body.get("from", {}).get("userid")
            if chatid and self.on_chat_id:
                try:
                    self.on_chat_id(chatid)
                except Exception:
                    logger.exception("on_chat_id 回调异常")

        elif cmd == "aibot_event_callback":
            event_body = body.get("event", {})
            event_type = event_body.get("eventtype")
            if event_type == "disconnected_event":
                logger.warning("当前连接被新连接踢掉（disconnected_event）")
                self._authenticated.clear()
            # enter_chat 等事件也可在此扩展

    def _on_error(self, _ws, error):
        logger.error("WeCom WebSocket 错误: %s", error)

    def _on_close(self, _ws, close_status_code, close_msg):
        self._connected.clear()
        self._authenticated.clear()
        self.ws = None
        logger.info("WeCom WebSocket 已关闭: %s %s", close_status_code, close_msg)

    def _run_forever(self):
        while not self._shutdown.is_set():
            try:
                self.ws_app.run_forever()
            except Exception as exc:
                logger.error("WebSocket run_forever 异常: %s", exc)

            if self._shutdown.is_set():
                break

            # 自动重连（指数退避）
            delay = self._reconnect_delay
            self._reconnect_delay = min(self._reconnect_delay * 2, 30)
            logger.info("%s 秒后尝试重连", delay)
            time.sleep(delay)

    # ---------- 公共 API ----------

    def connect(self, timeout: float = 10) -> dict:
        """建立 WebSocket 连接并完成订阅认证"""
        if self._thread and self._thread.is_alive():
            # 已存在连接线程，只需等待认证
            if self._authenticated.wait(timeout=timeout):
                return {"errcode": 0, "errmsg": "ok"}

        self.ws_app = websocket.WebSocketApp(
            WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

        subscribe_frame = self._build_frame(
            "aibot_subscribe",
            {"bot_id": self.bot_id, "secret": self.secret},
        )
        resp = self._send_and_wait(subscribe_frame, timeout=timeout)

        errcode = resp.get("errcode")
        if errcode != 0:
            raise RuntimeError(
                f"WeCom 订阅失败: {resp.get('errmsg')} (errcode={errcode})"
            )

        self._authenticated.set()
        self._start_heartbeat()
        return resp

    def send_markdown(
        self,
        markdown: str,
        chat_id: Optional[str] = None,
        chat_type: Optional[int] = None,
        timeout: float = 30,
    ) -> dict:
        """主动向指定会话发送 Markdown 消息"""
        chat_id = chat_id or self.chat_id
        chat_type = chat_type if chat_type is not None else self.chat_type
        if not chat_id:
            raise ValueError("缺少 chatid，无法推送消息。请先获取群聊/用户 ID")

        if not self._authenticated.is_set():
            self.connect(timeout=min(timeout, 10))

        frame = {
            "cmd": "aibot_send_msg",
            "headers": {"req_id": str(uuid.uuid4())},
            "body": {
                "chatid": chat_id,
                "chat_type": chat_type,
                "msgtype": "markdown",
                "markdown": {"content": markdown},
            },
        }
        resp = self._send_and_wait(frame, timeout=timeout)

        errcode = resp.get("errcode")
        if errcode != 0:
            raise RuntimeError(
                f"企业微信返回错误: {resp.get('errmsg')} (errcode={errcode})"
            )
        return resp

    def close(self):
        """关闭连接并清理资源"""
        self._shutdown.set()
        if self.ws_app:
            try:
                self.ws_app.close()
            except Exception:
                pass
        self._connected.clear()
        self._authenticated.clear()


# ---------------------------------------------------------------------------
# 长连接便捷函数
# ---------------------------------------------------------------------------

def _aibot_enabled(config: Dict) -> bool:
    """判断当前配置是否使用智能机器人长连接"""
    if config.get("send_type") == "aibot":
        return True
    # 如果填了 bot_id + secret，优先走长连接
    if config.get("bot_id") and config.get("secret"):
        return True
    return False


def send_aibot_markdown(
    bot_id: str,
    secret: str,
    chatid: str,
    chat_type: int,
    content: str,
    timeout: int = 30,
) -> Dict:
    """一次性连接并发送 Markdown 消息"""
    client = WeComAIBotClient(
        bot_id=bot_id,
        secret=secret,
        chat_id=chatid,
        chat_type=chat_type,
    )
    try:
        client.connect(timeout=10)
        return client.send_markdown(content, timeout=timeout)
    finally:
        client.close()


def listen_wecom_chatid(
    bot_id: str,
    secret: str,
    timeout: int = 60,
) -> Optional[str]:
    """
    监听智能机器人消息回调，捕获群聊/用户 ID。
    使用方式：在群里 @机器人或向机器人发单聊消息，即可在 timeout 内拿到 chatid。
    """
    captured = {"chatid": None}
    done = threading.Event()

    def on_chatid(chatid: str):
        captured["chatid"] = chatid
        done.set()

    client = WeComAIBotClient(
        bot_id=bot_id,
        secret=secret,
        on_chat_id=on_chatid,
    )
    try:
        client.connect(timeout=10)
        done.wait(timeout=timeout)
        return captured["chatid"]
    finally:
        client.close()


def test_aibot_connection(config: Dict) -> Dict:
    """测试智能机器人连接。无 chatid 时只做订阅认证；有 chatid 时发送测试消息。"""
    bot_id = config.get("bot_id", "")
    secret = config.get("secret", "")
    chatid = _config_chat_id(config)
    chat_type = int(config.get("chat_type", 2))

    if not bot_id or not secret:
        return {"ok": False, "error": "BotID 和 Secret 不能为空"}

    client = WeComAIBotClient(bot_id=bot_id, secret=secret)
    try:
        client.connect(timeout=10)
        if not chatid:
            return {
                "ok": True,
                "message": "连接并认证成功，请获取群聊/用户 ID 后再发送测试消息",
            }
        resp = client.send_markdown(
            "⏱️ 测试消息：拼多多 BI 看板企业微信推送已配置成功。",
            chat_id=chatid,
            chat_type=chat_type,
            timeout=config.get("timeout", 30),
        )
        return {"ok": True, "message": "测试消息发送成功", "response": resp}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        client.close()


# ---------------------------------------------------------------------------
# 兼容：群机器人 Webhook
# ---------------------------------------------------------------------------

def _build_robot_sign(secret: str) -> tuple:
    """构建企业微信群机器人签名"""
    timestamp = int(time.time())
    string_to_sign = f"{timestamp}\n{secret}"
    sign = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    return timestamp, sign


def send_robot_message(key: str, secret: str, content: str, timeout: int = 30) -> Dict:
    """通过企业微信群机器人发送 markdown 消息"""
    if not key:
        raise ValueError("机器人 Key 不能为空")

    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }
    if secret:
        timestamp, sign = _build_robot_sign(secret)
        payload["timestamp"] = timestamp
        payload["sign"] = sign

    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"群机器人发送失败: {data.get('errmsg')} (errcode={data.get('errcode')})")
    return data


# ---------------------------------------------------------------------------
# 兼容：企业微信应用 appchat
# ---------------------------------------------------------------------------

def get_wecom_access_token(corp_id: str, corp_secret: str, timeout: int = 30) -> str:
    """获取企业微信 access_token"""
    if not corp_id or not corp_secret:
        raise ValueError("corp_id 和 corp_secret 不能为空")

    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={corp_secret}"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"获取 access_token 失败: {data.get('errmsg')}")
    return data["access_token"]


def send_appchat_markdown(
    corp_id: str,
    corp_secret: str,
    chatid: str,
    content: str,
    timeout: int = 30,
) -> Dict:
    """通过企业微信应用发送群聊 markdown 消息"""
    access_token = get_wecom_access_token(corp_id, corp_secret, timeout=timeout)
    url = f"https://qyapi.weixin.qq.com/cgi-bin/appchat/send?access_token={access_token}"
    payload = {
        "chatid": chatid,
        "msgtype": "markdown",
        "markdown": {"content": content},
        "safe": 0,
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"企业微信发送失败: {data.get('errmsg')} (errcode={data.get('errcode')})")
    return data


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def send_wecom_report(content: str, config: Dict) -> Dict:
    """根据配置自动选择发送方式，优先使用智能机器人长连接"""
    chatid = _config_chat_id(config)
    if _aibot_enabled(config):
        return send_aibot_markdown(
            bot_id=config.get("bot_id", ""),
            secret=config.get("secret", ""),
            chatid=chatid,
            chat_type=int(config.get("chat_type", 2)),
            content=content,
            timeout=config.get("timeout", 30),
        )

    send_type = config.get("send_type", "robot")
    if send_type == "appchat":
        return send_appchat_markdown(
            corp_id=config.get("corp_id", ""),
            corp_secret=config.get("corp_secret", ""),
            chatid=chatid,
            content=content,
            timeout=config.get("timeout", 30),
        )
    else:
        return send_robot_message(
            key=config.get("robot_key", ""),
            secret=config.get("robot_secret", ""),
            content=content,
            timeout=config.get("timeout", 30),
        )


def test_wecom_connection(config: Dict) -> Dict:
    """测试企业微信连接"""
    if _aibot_enabled(config):
        return test_aibot_connection(config)

    try:
        send_wecom_report("⏱️ 测试消息：拼多多 BI 看板企业微信推送已配置成功。", config)
        return {"ok": True, "message": "测试消息发送成功"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
