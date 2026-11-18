"""Operator-facing login for the one configured Agent WeChat account slot."""
import hashlib
import http.client
import json
import os
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote


TIMEOUT = 180
LOCK = threading.Lock()
ID = re.compile(r"[A-Za-z0-9_-]{1,160}")
PNG = b"\x89PNG\r\n\x1a\n"
TERMINAL = {"succeeded", "failed", "cancelled", "expired", "rejected", "needs_login",
            "approval_required", "challenge_required"}
ACTIVE = {"starting", "queued", "running", "resuming", "awaiting_scan", "awaiting_approval", "authenticating"}


class PluginError(ValueError):
    def __init__(self, status):
        self.status = status
        message = {
            401: "微信插件登录令牌无效，请检查服务配置",
            403: "微信插件令牌需要当前槽位的 read 和 login 权限",
            404: "微信插件中未找到已配置的账号槽或扫码请求",
            409: "CONFLICT 微信插件状态已变更，请刷新",
            429: "RATE_LIMITED 微信插件请求过于频繁，请稍后重试",
        }
        super().__init__(message.get(status, "微信插件暂时不可用，请稍后刷新"))


class LoginPlugin:
    def __init__(self):
        default = (Path(os.getenv("LOCALAPPDATA", ".")) / "Ergou/WechatListener"
                   if os.name == "nt" else Path("/var/lib/ergou/wechat"))
        self.profile = Path(os.getenv("ERGOU_WECHAT_PRIVATE_DIR", default))
        self.slot = os.getenv("ERGOU_WECHAT_SLOT", "ergou-listener")
        self.port = int(os.getenv("ERGOU_WECHAT_PORT", "6174"))
        if not ID.fullmatch(self.slot) or not 1 <= self.port <= 65535:
            raise ValueError("微信插件账号槽或端口配置无效")
        try:
            self.token = (self.profile / "ergou-login-token").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            raise ValueError("尚未配置微信插件登录令牌，请检查服务器配置") from None
        if not re.fullmatch(r"[!-~]{1,4096}", self.token):
            raise ValueError("微信插件登录令牌配置无效")
        self.base = "/v1/accounts/" + quote(self.slot, safe="")
        tag = hashlib.sha256(f"{self.port}/{self.slot}".encode()).hexdigest()[:16]
        self.receipt = self.profile / f"ergou-web-login-{tag}.json"

    def request(self, method, suffix="", body=None, key=None, png=False):
        mime = "image/png" if png else "application/json"
        headers = {"Authorization": "Bearer " + self.token, "Accept": mime}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        try:
            conn.request(method, self.base + suffix, json.dumps(body) if body is not None else None, headers)
            response = conn.getresponse()
            if response.status not in (200, 202):
                raise PluginError(response.status)
            raw = response.read(512 * 1024 + 1)
            if len(raw) > 512 * 1024 or response.getheader("Content-Type", "").split(";")[0] != mime:
                raise ValueError("微信插件返回了无效的响应")
            if png:
                if not raw.startswith(PNG):
                    raise ValueError("微信插件二维码图片无效")
                return raw
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("微信插件响应格式错误")
            return result
        except (OSError, http.client.HTTPException):
            raise ValueError("无法连接本机微信插件，请检查服务并刷新") from None
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("微信插件响应格式错误") from None
        finally:
            conn.close()

    def load(self):
        try:
            data = json.loads(self.receipt.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or not ID.fullmatch(data["key"])
                    or type(data["created"]) not in (int, float) or not isinstance(data["attempt"], str)
                    or (data["attempt"] and not ID.fullmatch(data["attempt"]))):
                raise ValueError()
            return data
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("微信扫码请求记录不可读，请检查服务目录") from None

    def save(self, record):
        # Save the admission key before contacting the plugin. A dropped response
        # or a web restart then resumes the same operation. Never store its QR.
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                             dir=self.profile, prefix=".ergou-login-") as handle:
                tmp = Path(handle.name)
                json.dump(record, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.receipt)
        except OSError:
            raise ValueError("无法保存扫码请求编号，请检查服务目录写权限") from None
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)


def _plugin(user):
    if not user or user["role"] != "系统管理员":
        raise PermissionError("FORBIDDEN 仅系统管理员可管理机器人微信登录")
    return LoginPlugin()


def _operation(plugin, op, expected=None):
    attempt = op.get("id")
    if (op.get("accountId") != plugin.slot or op.get("kind") != "login"
            or not isinstance(attempt, str) or not ID.fullmatch(attempt)
            or (expected and attempt != expected)):
        raise ValueError("微信插件扫码请求身份不匹配")
    state = op.get("state")
    if state not in TERMINAL | ACTIVE:
        raise ValueError("微信插件扫码状态无法识别，请刷新")
    result = op.get("result")
    generation = 0
    if state == "awaiting_scan" and isinstance(result, dict) and result.get("qrAvailable") is True:
        n = result.get("qrGeneration")
        if type(n) is int and 0 < n < 2**53:
            generation = n
    view = {"state": state, "attempt": attempt, "generation": generation}
    if isinstance(result, dict):
        if state in ACTIVE and result.get("lanChallenge") == "waiting_for_phone":
            view["hint"] = "微信要求手机与运行插件的设备在可互通的局域网内确认登录。"
        elif state == "failed" and result.get("code") == "login_lan_challenge_failed":
            view["hint"] = "微信的局域网验证失败。请核对手机能否访问运行插件的设备。"
    return view


def _view(plugin, record):
    account = plugin.request("GET")
    if account.get("id") != plugin.slot or type(account.get("authenticated")) is not bool:
        raise ValueError("微信插件账号身份或状态无效")
    if account["authenticated"] and account.get("connection") == "online":
        return {"state": "online", "account": account.get("ownUsername") or plugin.slot}
    if not record:
        return {"state": "idle"}
    if time.time() >= record["created"] + TIMEOUT + 30:
        return {"state": "expired"}
    if not record["attempt"]:
        return {"state": "retry_start"}
    try:
        op = plugin.request("GET", "/login-attempts/" + record["attempt"])
    except PluginError as exc:
        if exc.status == 404:
            return {"state": "expired"}
        raise
    return _operation(plugin, op, record["attempt"])


def status(user):
    plugin = _plugin(user)
    with LOCK:
        return _view(plugin, plugin.load())


def action(user, data):
    plugin = _plugin(user)
    command = data.get("action")
    if command not in ("start", "cancel"):
        raise ValueError("无效的扫码操作")
    with LOCK:
        record = plugin.load()
        current = _view(plugin, record)
        if current["state"] == "online":
            return current
        if command == "cancel":
            if not current.get("attempt") or data.get("attempt") != current["attempt"]:
                raise ValueError("CONFLICT 扫码请求已变更，请刷新")
            if current["state"] in TERMINAL:
                return current
            attempt = current["attempt"]
            op = plugin.request("POST", "/login-attempts/" + attempt + "/cancel", {})
            return _operation(plugin, op, attempt)
        if current["state"] not in TERMINAL | {"idle", "retry_start"}:
            return current
        if current["state"] != "retry_start":
            record = {"key": secrets.token_urlsafe(24), "attempt": "", "created": time.time()}
            plugin.save(record)
        op = plugin.request("POST", "/login-attempts",
                            {"strategy": "qr", "timeoutSeconds": TIMEOUT,
                             "qrRefresh": {"mode": "manual", "maxRefreshes": 0}}, key=record["key"])
        result = _operation(plugin, op)
        plugin.save(dict(record, attempt=result["attempt"]))
        return result


def qr(user, attempt, generation):
    plugin = _plugin(user)
    if not isinstance(attempt, str) or not ID.fullmatch(attempt) or not re.fullmatch(r"[1-9][0-9]{0,15}", str(generation)):
        raise ValueError("扫码请求或版本无效")
    with LOCK:
        current = _view(plugin, plugin.load())
        if (current.get("attempt"), current.get("generation")) != (attempt, int(generation)):
            raise ValueError("CONFLICT 此二维码已失效，请刷新")
        return plugin.request("GET", f"/login-attempts/{attempt}/qr?generation={int(generation)}", png=True)
