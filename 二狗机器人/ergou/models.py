"""Verified per-group chat models with credentials protected by the service account."""
import ctypes
import http.client
import json
import os
import re
import sys
import time
from ctypes import wintypes
from datetime import datetime
from typing import NamedTuple

from . import admin
from .db import BJ, allowed, audit, dump, record_failure, transaction


PROVIDERS = {
    "deepseek": ("DeepSeek", "api.deepseek.com", "/chat/completions", "/models"),
    "glm": ("智谱 GLM", "open.bigmodel.cn", "/api/paas/v4/chat/completions", "/openapi/openapi.json"),
    "qwen": ("通义千问（百炼北京）", "dashscope.aliyuncs.com", "/compatible-mode/v1/chat/completions", "/api/v1/models"),
    "openai": ("ChatGPT（OpenAI API）", "api.openai.com", "/v1/chat/completions", "/v1/models"),
}
MODEL_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,255}")
PLAY_HELP = "请发送 二狗菜单 或 二狗钓鱼玩法 查看哦。"
PLAY_INSTRUCTION = "用户询问二狗怎么玩、怎么钓鱼或有什么功能时，必须回复「"+PLAY_HELP+"」，不要自行编造玩法、指令、费用或奖励。"
PERSONA = "你是微信群里的柴犬机器人二狗。用简短自然的中文回答，可以幽默。如果不知道就直说。"


WEATHER_INSTRUCTION = (
    "按用户的问题自然回答，不必反复提柴犬身份。你可以查城市天气。用户问今天、明天、后天的气温、"
    "降雨或出门带伞时，先从本人的对话中确定城市；不清楚只问城市名，用户补充城市后继续查询。"
    "需要数据时整条回复只输出 WEATHER|城市名|天数，今天为0，明天1，后天2。例如 WEATHER|北京|0。"
    "只填城市，不含个人地址或其他信息。其他日期说明仅支持未来三天。不要编造天气或声称能任意联网。"
)


def weather_answer(db,reply):
    from . import queries
    from .bulletins import weather_request
    if not reply.startswith("WEATHER|"):
        return reply
    match=re.fullmatch(r"WEATHER\|([^\W\d_]+(?:[ ·-][^\W\d_]+)*)\|([012])",reply)
    if not match or len(match[1])>48:
        return "请告诉我城市名，以及想查今天、明天还是后天。"
    city,day=match.groups()
    now=time.time()
    key=f"forecast:{city}:{day}"
    with transaction(db):
        cached=db.execute("SELECT reply FROM weather_cache WHERE city=? AND at>?",(key,now-600)).fetchone()
        if cached:
            return cached[0]
        if not allowed(db,"外部查询/天气"+datetime.fromtimestamp(now,BJ).date().isoformat(),500,86400,now):
            return "今天的天气查询额度已用完。"
    try:
        result=queries.lookup("天气",city,weather_request,forecast_day=int(day))
    except queries.ProviderError as exc:
        return f"这次没查到{city}的天气（{exc}）。"
    db.execute("INSERT OR REPLACE INTO weather_cache VALUES(?,?,?)",(key,now,result))
    return result


class ModelError(ValueError):
    def __init__(self,category,detail=None):
        self.category=category
        super().__init__(detail or category)


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]


def protect(value, decrypt=False):
    if sys.platform.startswith("linux"):
        from . import linux_credentials
        try:
            return linux_credentials.protect(value, decrypt)
        except ValueError as exc:
            raise ModelError("密钥保护服务不可用", str(exc)) from None
    if os.name != "nt":
        raise ModelError("密钥保护服务不可用","当前系统支持 Windows 或 Linux 凭据存储")
    buf = ctypes.create_string_buffer(value)
    src = Blob(len(value), ctypes.cast(buf, ctypes.c_void_p))
    dest = Blob()
    library = ctypes.windll.crypt32
    method = library.CryptUnprotectData if decrypt else library.CryptProtectData
    if not method(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dest)):
        raise ModelError("密钥保护服务不可用","密钥保护服务不可用，请核对运行后台的 Windows 账号")
    try:
        return ctypes.string_at(dest.data, dest.size)
    finally:
        ctypes.memset(dest.data, 0, dest.size)
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(dest.data))


def _provider_json(host, path, key, payload=None, limit=262144):
    conn = http.client.HTTPSConnection(host, timeout=18)
    try:
        headers = {"Accept": "application/json"}
        if key is not None:
            headers["Authorization"] = "Bearer " + key
        if payload is None:
            conn.request("GET", path, headers=headers)
        else:
            headers["Content-Type"] = "application/json"
            conn.request("POST", path, body=dump(payload).encode(), headers=headers)
        response = conn.getresponse()
        if response.status != 200:
            reason = {400:"请求参数或模型不受支持", 401:"密钥验证失败", 402:"余额不足",
                      403:"模型访问权限不足", 404:"模型不可用", 429:"额度或频率受限"}.get(response.status,"服务暂不可用")
            raise ModelError(reason,f"供应商返回 HTTP {response.status}，{reason}")
        raw = response.read(limit+1)
        if len(raw) > limit:
            raise ModelError("供应商响应过大")
        try:
            return json.loads(raw)
        except ValueError:
            raise ModelError("模型响应格式异常","供应商未返回有效的 JSON") from None
    except (OSError, http.client.HTTPException):
        raise ModelError("无法连接供应商或请求超时") from None
    finally:
        conn.close()


def complete(provider, model, key, messages):
    _, host, path, _ = PROVIDERS[provider]
    payload = dict(model=model, messages=messages, stream=False)
    payload["max_completion_tokens" if provider=="openai" else "max_tokens"] = 1024
    result = _provider_json(host,path,key,payload)
    try:
        answer = result["choices"][0]["message"]["content"]
        if isinstance(answer,str) and answer.strip():
            return answer.strip()[:1800]
    except (KeyError, TypeError, IndexError):
        pass
    raise ModelError("模型响应格式异常","供应商未返回有效的文字回答，请检查所选模型")


def _catalog_ids(items, field):
    if not isinstance(items, list):
        raise ModelError("模型列表格式异常")
    ids = set()
    for item in items:
        model = item.get(field) if isinstance(item, dict) else None
        if not isinstance(model, str) or not MODEL_ID.fullmatch(model):
            raise ModelError("模型列表包含无效 ID")
        ids.add(model)
    return ids


def provider_model_ids(provider, key):
    _, host, _, path = PROVIDERS[provider]
    if provider == "glm":
        spec = _provider_json("docs.bigmodel.cn", path, None, limit=4*1024*1024)
        try:
            values = spec["components"]["schemas"]["ChatCompletionTextRequest"]["properties"]["model"]["enum"]
        except (KeyError, TypeError):
            raise ModelError("智谱官方文字模型列表格式异常") from None
        if not isinstance(values, list) or any(not isinstance(value, str) or not MODEL_ID.fullmatch(value)
                                               for value in values):
            raise ModelError("智谱官方文字模型列表格式异常")
        return sorted(set(values))
    if provider != "qwen":
        result = _provider_json(host, path, key, limit=1024*1024)
        return sorted(_catalog_ids(result.get("data") if isinstance(result, dict) else None, "id"))

    ids = set()
    received = 0
    deadline = time.monotonic() + 45
    for page in range(1, 101):
        if time.monotonic() > deadline:
            raise ModelError("获取完整模型列表超时，请稍后刷新")
        result = _provider_json(host, f"{path}?page_no={page}&page_size=100", key, limit=2*1024*1024)
        output = result.get("output") if isinstance(result, dict) and result.get("success", True) is True else None
        if not isinstance(output, dict) or output.get("page_no", page) != page:
            raise ModelError("模型列表格式异常")
        total = output.get("total")
        items = output.get("models")
        page_ids = _catalog_ids(items, "model")
        if type(total) is not int or total < 0:
            raise ModelError("模型列表格式异常")
        if (not items and received < total) or (items and not page_ids.difference(ids)):
            raise ModelError("供应商未返回完整模型列表，请刷新重试")
        ids.update(page_ids)
        received += len(items)
        if received >= total:
            return sorted(ids)
    raise ModelError("模型列表页数超出支持范围")


def _request_key(old,provider,key):
    if key=="" and old and old["provider"]==provider and old["verified"] is not None and old["credential"]:
        return protect(old["credential"],True).decode("ascii")
    if isinstance(key,str) and re.fullmatch(r"[!-~]{1,1024}",key):
        return key
    raise ValueError("请输入所选供应商的官方 API Key")


def list_models(db,user,group,fields):
    permit(user,group)
    provider = fields.get("provider")
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ValueError("请选择有效的官方供应商")
    key = None
    if provider != "glm":
        old=db.execute("SELECT provider,credential,verified FROM chat_models WHERE grp=?",(group,)).fetchone()
        key=_request_key(old,provider,fields.get("key",""))
    with transaction(db):
        if not allowed(db,"model-list/"+provider+"/"+group,12,60,time.time()):
            raise ValueError("RATE_LIMITED 获取模型列表过于频繁，请稍后再试")
    return {"models":provider_model_ids(provider, key)}


def permit(user, group):
    admin.permitted(user, group, True)
    if user["role"] not in ("系统管理员", "运营管理员"):
        raise PermissionError("FORBIDDEN 仅运营管理员或系统管理员可配置模型")


def settings(db, user, group):
    permit(user, group)
    row = db.execute("SELECT version,provider,model,verified FROM chat_models WHERE grp=?", (group,)).fetchone()
    return dict(active=dict(row) if row else dict(version=0,provider="",model="",verified=None),
                providers=[dict(id=k,name=v[0],models=[]) for k,v in PROVIDERS.items()])


def control_settings(db, user, group):
    permit(user, group)
    row = db.execute("""SELECT COALESCE(c.version,0) version, COALESCE(c.admins,'[]') admins,
                    COALESCE(c.enabled,1) enabled, m.verified IS NOT NULL verified
                    FROM groups g LEFT JOIN smart_controls c ON c.grp=g.id
                    LEFT JOIN chat_models m ON m.grp=g.id WHERE g.id=?""",(group,)).fetchone()
    if not row:
        raise ValueError("群不存在")
    return dict(version=row["version"],admins=json.loads(row["admins"]),verified=bool(row["verified"]),
                enabled=bool(row["enabled"] and row["verified"]))


def configure_controls(db, user, group, fields):
    permit(user, group)
    members, version = fields.get("admins"), fields.get("version")
    if type(version) is not int or version < 0:
        raise ValueError("配置版本无效")
    if (not isinstance(members,list) or len(members)>100 or
            any(not isinstance(m,str) or not 1<=len(m)<=160 or not m.isprintable()
                or any(c.isspace() for c in m) for m in members)):
        raise ValueError("请填写有效的微信成员 ID，每群最多 100 名管理员")
    admins=list(dict.fromkeys(members))
    with transaction(db):
        db.execute("INSERT OR IGNORE INTO smart_controls(grp) VALUES(?)",(group,))
        if not db.execute("UPDATE smart_controls SET admins=?,version=version+1 WHERE grp=? AND version=?",
                          (dump(admins),group,version)).rowcount:
            raise ValueError("CONFLICT 本群设置已变化，请刷新后重试")
        audit(db,user["name"],group,"配置智能对话管理员",f"{len(admins)} 名")
    return control_settings(db,user,group)


def cancel_chat(db, group):
    db.execute("""UPDATE chat_requests SET state='CANCELLED',prompt=NULL WHERE seq IN
                  (SELECT i.seq FROM inbox i JOIN outbox o ON o.biz=i.event_id
                   WHERE i.grp=? AND o.state IN ('SENDING','PENDING','RETRY_WAIT'))""",(group,))
    db.execute("""UPDATE chat_requests SET state='CANCELLED',prompt=NULL WHERE state IN ('PENDING','RUNNING')
                  AND seq IN (SELECT seq FROM inbox WHERE grp=?)""",(group,))
    db.execute("""UPDATE outbox SET state='CANCELLED',body='',detail='智能对话配置已变化'
                  WHERE grp=? AND state IN ('PENDING','RETRY_WAIT') AND biz IN
                  (SELECT i.event_id FROM inbox i JOIN chat_requests q ON q.seq=i.seq WHERE i.grp=?)""",
               (group,group))


def switch(db, event, enabled, mentioned):
    group = event["grp"]
    if not mentioned:
        raise ValueError("请使用微信的 @ 功能点名二狗，再发送智能对话开关指令")
    live = db.execute("SELECT mode FROM account WHERE id=?",(event["account"],)).fetchone()[0]!="simulation"
    if live and (event["adapter_version"]!="agent-wechat-events/2.7.1" or not db.execute(
            "SELECT 1 FROM directed_events WHERE biz=? AND source_time>?",
            (event["event_id"],time.time()-120)).fetchone()):
        raise ValueError("需要当前已授权群内的新点名消息")
    row=db.execute("SELECT admins,enabled,generation FROM smart_controls WHERE grp=?",(group,)).fetchone()
    from . import roles
    if roles.owner(db,event["account"]):
        roles.require(db,event["account"],group,event["member"],4)
        if row is None:
            db.execute("INSERT INTO smart_controls(grp,enabled) VALUES(?,0)",(group,))
            row=db.execute("SELECT * FROM smart_controls WHERE grp=?",(group,)).fetchone()
    elif not row or event["member"] not in json.loads(row["admins"]):
        raise ValueError("仅本群后台指定的智能对话管理员可以切换")
    if enabled and not db.execute("SELECT 1 FROM chat_models WHERE grp=? AND verified IS NOT NULL AND credential IS NOT NULL",(group,)).fetchone():
        raise ValueError("请运营人员先在本群后台测试并保存模型和密钥")
    if bool(row["enabled"]) != enabled or (enabled and row["generation"] == 0):
        db.execute("UPDATE smart_controls SET enabled=?,version=version+1,generation=generation+1 WHERE grp=?",(enabled,group))
        cancel_chat(db,group)
        db.execute("DELETE FROM local_turns WHERE grp=?",(group,))
        audit(db,event["member"],group,"群内切换智能对话","开启" if enabled else "关闭")
    return "本群已开启智能对话。请在微信里 @二狗 聊天。" if enabled else "本群已关闭智能对话。二狗仍可接关键词、查天气、玩游戏和讲笑话。"


def configure(db, user, group, fields):
    permit(user, group)
    version = fields.get("version")
    if type(version) is not int or version < 0:
        raise ValueError("配置版本无效")
    disable = fields.get("action") == "disable"
    if not disable and fields.get("action") != "verify":
        raise ValueError("配置操作无效")
    old = db.execute("SELECT * FROM chat_models WHERE grp=?", (group,)).fetchone()
    if (old["version"] if old else 0) != version:
        raise ValueError("CONFLICT 配置已更新，请刷新后重试")
    provider, model, sealed, verified = "", "", None, None
    if not disable:
        provider, model, key = (fields.get(k) for k in ("provider","model","key"))
        if (not isinstance(provider,str) or provider not in PROVIDERS or not isinstance(model,str)
                or not MODEL_ID.fullmatch(model)):
            raise ValueError("请选择官方供应商并填写有效的模型 ID")
        key=_request_key(old,provider,key)
        sealed=old["credential"] if fields.get("key")=="" else protect(key.encode("ascii"))
        with transaction(db):
            if not allowed(db, "model-test/"+group, 6, 60, time.time()):
                raise ValueError("RATE_LIMITED 测试频率过高，请稍后再试")
        try:
            complete(provider, model, key, [{"role":"user","content":"连接测试，请回复 OK。"}])
        except ValueError as exc:
            record_failure(db,group,None,"模型配置验证",exc.category if isinstance(exc,ModelError) else "供应商调用失败")
            raise
        verified = time.time()
    with transaction(db):
        current = db.execute("SELECT version FROM chat_models WHERE grp=?", (group,)).fetchone()
        if (current[0] if current else 0) != version:
            raise ValueError("CONFLICT 另一位运营人员已修改配置，请刷新")
        db.execute("INSERT OR REPLACE INTO chat_models VALUES(?,?,?,?,?,?)",
                   (group,version+1,provider,model,sealed,verified))
        cancel_chat(db,group)
        db.execute("DELETE FROM local_turns WHERE grp=?",(group,))
        audit(db,user["name"],group,"停用群聊模型" if disable else "验证并启用群聊模型",provider+" "+model)
    return settings(db,user,group)


def api_first(db, group):
    return db.execute("""SELECT 1 FROM chat_models m LEFT JOIN smart_controls c ON c.grp=m.grp
                         WHERE m.grp=? AND COALESCE(c.enabled,1)=1
                         AND m.verified IS NOT NULL AND m.credential IS NOT NULL""",(group,)).fetchone() is not None


def submit(db, event, text):
    from . import native_voice
    if event["adapter_version"] == native_voice.VERSION:
        if not native_voice.event_authorized(db, event["seq"]):
            return None
    elif db.execute("SELECT 1 FROM listener_nodes WHERE account=?",(event["account"],)).fetchone():
        if not db.execute("SELECT 1 FROM directed_events WHERE biz=?",(event["event_id"],)).fetchone():
            return None
    config = db.execute("""SELECT m.version FROM chat_models m LEFT JOIN smart_controls c ON c.grp=m.grp
                         WHERE m.grp=? AND m.verified IS NOT NULL AND COALESCE(c.enabled,1)""",(event["grp"],)).fetchone()
    if not config:
        from .local_chat import respond
        return respond(db,event,text)
    db.execute("INSERT INTO chat_requests(seq,version,prompt) VALUES(?,?,?)",(event["seq"],config[0],text[:2400]))


class ChatTurn(NamedTuple):
    user: str
    assistant: str
    voice_generation: int | None


def reply_authorized(db, biz):
    from . import voice_policy
    row = db.execute("""SELECT q.state,i.grp,i.account,i.binding,v.generation
                     FROM inbox i JOIN chat_requests q ON q.seq=i.seq
                     LEFT JOIN chat_voice_context v ON v.seq=q.seq WHERE i.event_id=?""",(biz,)).fetchone()
    if not row:
        return True
    return (row["state"] != "CANCELLED" and (row["generation"] is None or
            row["generation"] == voice_policy.active(db, row["grp"], row["account"], row["binding"])))


class ChatWorker:
    def __init__(self):
        self.sessions = {}
        self.cleaned = 0

    def work(self, db):
        from .engine import queue
        from . import native_voice, voice_policy
        now = time.time()
        if now-self.cleaned >= 60:
            self.sessions = {k:v for k,v in self.sessions.items() if v[0]+1800>now}
            self.cleaned = now
        with transaction(db):
            db.execute("UPDATE chat_requests SET state='EXPIRED',prompt=NULL WHERE state='RUNNING' AND lease<=?",(now,))
            row = db.execute("""SELECT q.*,i.grp,i.member,i.event_id,i.account,i.binding,i.arrived,i.adapter_version,
                     m.provider,m.model,m.credential,m.version AS active_version,g.paused,g.config,
                     COALESCE(c.generation,0) generation,COALESCE(c.enabled,1) enabled,
                     g.account AS active_account,g.binding AS active_binding FROM chat_requests q
                     JOIN inbox i ON i.seq=q.seq JOIN groups g ON g.id=i.grp LEFT JOIN chat_models m ON m.grp=i.grp
                     LEFT JOIN smart_controls c ON c.grp=i.grp
                     WHERE q.state='PENDING' AND NOT EXISTS (SELECT 1 FROM chat_requests prev JOIN inbox p ON p.seq=prev.seq
                     WHERE prev.state='RUNNING' AND p.grp=i.grp AND p.member=i.member) ORDER BY q.seq LIMIT 1""").fetchone()
            if not row:
                return False
            voice = row["adapter_version"] == native_voice.VERSION
            if voice and not native_voice.event_authorized(db, row["seq"]):
                db.execute("UPDATE chat_requests SET state='CANCELLED',prompt=NULL WHERE seq=?",(row["seq"],))
                return True
            if (row["arrived"]+120<=now or row["version"]!=row["active_version"] or not row["credential"] or not row["enabled"] or row["paused"]
                    or row["account"]!=row["active_account"] or row["binding"]!=row["active_binding"] or not json.loads(row["config"])["enabled"]):
                db.execute("UPDATE chat_requests SET state='EXPIRED',prompt=NULL WHERE seq=?",(row["seq"],))
                return True
            db.execute("UPDATE chat_requests SET state='RUNNING',lease=? WHERE seq=?",(now+45,row["seq"]))
            required_generation = (voice_policy.active(db,row["grp"],row["account"],row["binding"]) if voice else None)
        session = (row["grp"],row["member"],row["binding"],row["version"],row["generation"])
        last, turns = self.sessions.get(session,(0,[]))
        if row["arrived"]-last >= 1800:
            turns = []
        prompt = {"role":"user","content":row["prompt"]}

        def current():
            return (db.execute("""SELECT 1 FROM chat_requests q JOIN inbox i ON i.seq=q.seq
                       JOIN groups g ON g.id=i.grp AND g.account=i.account AND g.binding=i.binding
                       JOIN chat_models m ON m.grp=g.id AND m.version=q.version
                       LEFT JOIN smart_controls c ON c.grp=g.id
                       WHERE q.seq=? AND q.state='RUNNING' AND q.lease>? AND i.arrived>?
                       AND m.verified IS NOT NULL AND m.credential IS NOT NULL AND COALESCE(c.enabled,1)
                       AND COALESCE(c.generation,0)=?
                       AND g.paused=0 AND json_extract(g.config,'$.enabled')=1""",
                       (row["seq"],time.time(),time.time()-120,row["generation"])).fetchone() is not None
                    and (not voice or (required_generation is not None and native_voice.event_authorized(db, row["seq"])))
                    and (required_generation is None or
                         required_generation == voice_policy.active(db, row["grp"], row["account"], row["binding"])))

        try:
            key = protect(row["credential"],True).decode("ascii")
            if any(turn.voice_generation is not None for turn in turns):
                active_generation = voice_policy.active(db, row["grp"], row["account"], row["binding"])
                turns = [turn for turn in turns if turn.voice_generation is None or turn.voice_generation == active_generation]
                if not voice and any(turn.voice_generation is not None for turn in turns):
                    required_generation = active_generation
            if not current():
                db.execute("UPDATE chat_requests SET state='CANCELLED',prompt=NULL WHERE seq=? AND state='RUNNING'",(row["seq"],))
                return True
            messages = [{"role":"system","content":f"{PERSONA} 北京时间 {datetime.fromtimestamp(now,BJ):%Y-%m-%d}。{WEATHER_INSTRUCTION} {PLAY_INSTRUCTION}"}]
            for turn in turns:
                messages.extend(({"role":"user","content":turn.user},{"role":"assistant","content":turn.assistant}))
            reply = complete(row["provider"],row["model"],key,[*messages,prompt])
            if current():
                reply = weather_answer(db,reply)
            state = "DONE"
        except ValueError as exc:
            state,reply = "FAILED","汪，聊天服务暂时没接通，稍后再叫我试试。"
            reason=exc.category if isinstance(exc,ModelError) else "供应商调用失败"
        with transaction(db):
            if not current():
                db.execute("UPDATE chat_requests SET state='CANCELLED',prompt=NULL WHERE seq=? AND state='RUNNING'",(row["seq"],))
                return True
            db.execute("UPDATE chat_requests SET state=?,prompt=NULL WHERE seq=?",(state,row["seq"]))
            group = db.execute("SELECT * FROM groups WHERE id=?",(row["grp"],)).fetchone()
            if state=="FAILED":
                record_failure(db,row["grp"],row["seq"],"模型请求",reason)
            if state=="DONE" and required_generation is not None:
                db.execute("INSERT INTO chat_voice_context VALUES(?,?)",(row["seq"],required_generation))
            queue(db,group,row["event_id"],reply,row["arrived"])
            if state=="DONE":
                self.sessions[session]=(row["arrived"],[*turns,ChatTurn(row["prompt"],reply,required_generation)][-16:])
        return True
