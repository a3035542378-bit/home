"""Optional fixed-host read-only providers. No chat or user identifiers leave the instance."""
import base64
import hashlib
import json
import math
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from .db import BJ, allowed, record_failure, transaction

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
DHL = "https://api-eu.dhl.com/track/shipments"
KDN = "https://api.kdniao.com/Ebusiness/EbusinessOrderHandle.aspx"
CARRIERS={"申通":"STO","圆通":"YTO","百世":"HTKY","极兔":"JTSD"}


def submit(db,e,kind,arg):
    from . import native_voice
    if e["adapter_version"] == native_voice.VERSION and not native_voice.event_authorized(db, e["seq"]):
        return None
    if kind=="百科":
        from .leisure import term
        arg=term(arg)
    if not arg or len(arg)>64:
        raise ValueError("请提供城市名" if kind=="天气" else "请输入 DHL 单号")
    if kind=="天气":
        if not re.fullmatch(r"[\w .·-]{1,64}",arg):
            raise ValueError("城市名格式无效")
        row=db.execute("SELECT * FROM weather_cache WHERE city=? AND at>?",(arg,e["arrived"]-600)).fetchone()
        if row:
            return row["reply"]+"（10 分钟内缓存）"
    elif kind=="快递":
        carrier,number=parcel_args(arg)
        required=("ERGOU_KDN_ID","ERGOU_KDN_KEY") if carrier!="DHL" else ("ERGOU_DHL_KEY",)
        if not all(os.getenv(key) for key in required):
            raise ValueError("CAPABILITY_UNSUPPORTED 快递查询凭据未配置")
    breaker=db.execute("SELECT reopen FROM breaker WHERE kind=?",(kind,)).fetchone()
    if breaker and breaker[0]>e["arrived"]:
        raise ValueError("外部服务暂时不可用，请稍后查询")
    day=datetime.fromtimestamp(e["arrived"],BJ).date().isoformat()
    limit=500 if kind=="天气" else 200
    if not allowed(db,"外部查询/"+kind+day,limit,86400,e["arrived"]):
        raise ValueError("RATE_LIMITED 今日查询预算已用尽")
    db.execute("INSERT INTO queries(id,kind,argument,state) VALUES(?,?,?,'PENDING')",(e["seq"],kind,arg))
    return None


class ProviderError(ValueError):
    def __init__(self,reason):
        # Only these operator-facing messages may be persisted or returned to a group.
        known={"DEPENDENCY_TIMEOUT 查询超时","DEPENDENCY_TIMEOUT 响应超限","DEPENDENCY_TIMEOUT 查询失败或超时",
               "供应商鉴权失败","供应商拒绝访问","查询无结果","供应商配额已用尽","供应商暂不可用",
               "城市查询无结果","快递鸟未受理，请核对账号权限及免费额度","快递查询无结果","供应商数据格式异常",
               "新闻源数据异常","新闻源格式异常","新闻源暂无可用标题","外部请求超时","服务超时",
               "外部内容服务连接超时或失败","供应商响应超限","天气服务地址无效"}
        super().__init__(reason if reason in known else "供应商暂不可用")


def parcel_args(arg):
    parts=arg.split()
    if len(parts)==1:parts=["DHL",parts[0]]
    if len(parts)!=2 or parts[0] not in (*CARRIERS,"DHL") or not re.fullmatch(r"[a-zA-Z0-9-]{6,40}",parts[1]):
        raise ValueError("用法：快递 申通/圆通/百世/极兔/DHL 单号")
    return parts


def fetch(url,params,deadline,headers=None):
    remaining=deadline-time.monotonic()
    if remaining<=0:
        raise ProviderError("DEPENDENCY_TIMEOUT 查询超时")
    encoded=urllib.parse.urlencode(params)
    request=(urllib.request.Request(url,data=encoded.encode(),headers=headers or {}) if url==KDN else
             urllib.request.Request(url+"?"+encoded,headers=headers or {}))
    try:
        with urllib.request.urlopen(request,timeout=min(3,remaining)) as response:
            raw=response.read(131073)
        if len(raw)>131072 or time.monotonic()>deadline:
            raise ProviderError("DEPENDENCY_TIMEOUT 响应超限")
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        msg={401:"供应商鉴权失败",403:"供应商拒绝访问",404:"查询无结果",429:"供应商配额已用尽"}.get(exc.code,"供应商暂不可用")
        raise ProviderError(msg) from None
    except (OSError,UnicodeError,ValueError) as exc:
        if isinstance(exc,ProviderError):
            raise
        raise ProviderError("DEPENDENCY_TIMEOUT 查询失败或超时") from None


def weather_locations(arg,request,deadline):
    province=re.fullmatch(r"(河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾)省?([一-龥]{2,12})",arg)
    city=province[2] if province else arg
    names=[city]
    if re.fullmatch(r"[一-龥]{2,10}",city) and not city.endswith(("市","区","县")):
        names.append(city+"市")
    for name in names:
        params=dict(name=name,count=10 if province else 1,language="zh",format="json")
        places=request(GEO,params,deadline).get("results",[])
        if province:
            places=[p for p in places if p.get("admin1","").removesuffix("省")==province[1]]
        if places:
            return places
    return []


def lookup(kind,arg,request=fetch,*,check=None,forecast_day=None):
    deadline=time.monotonic()+8
    try:
        if kind=="百科":
            from .leisure import encyclopedia
            return encyclopedia(arg,deadline,check=check)
        if kind=="天气":
            locations=weather_locations(arg,request,deadline)
            if not locations:
                raise ProviderError("城市查询无结果")
            place=locations[0]
            if check:
                check()
            params=dict(latitude=float(place["latitude"]),longitude=float(place["longitude"]),
                        timezone="Asia/Shanghai",current="temperature_2m")
            if forecast_day is not None:
                params.update(timezone="auto",forecast_days=forecast_day+1,
                              daily="temperature_2m_min,temperature_2m_max,precipitation_probability_max")
            data=request(FORECAST,params,deadline)
            current=data["current"]
            temp=float(current["temperature_2m"])
            if not math.isfinite(temp) or not -100<=temp<=70:
                raise ValueError()
            stamp=datetime.fromisoformat(current["time"])
            if forecast_day is not None:
                daily=data["daily"]
                date=datetime.fromisoformat(daily["time"][forecast_day])
                low=float(daily["temperature_2m_min"][forecast_day])
                high=float(daily["temperature_2m_max"][forecast_day])
                rain=float(daily["precipitation_probability_max"][forecast_day])
                if not (-100 <= low <= high <= 70 and 0 <= rain <= 100):
                    raise ValueError()
                label=" ".join(str(place[k]) for k in ("name","admin1","country") if place.get(k))
                advice="，出门建议带伞" if rain>=50 else ""
                return (f"🌤 {label}\n当地 {date:%m月%d日}预计 {low:g}～{high:g}°C\n"
                        f"☔ 最高降水概率 {rain:g}%{advice}\n\n"
                        f"当地 {stamp:%m-%d %H:%M} 气温估计 {temp:g}°C\n来源：Open-Meteo / GeoNames")
            return f"🌡️ {str(place['name'])[:60]}　{temp:g} °C\n北京时间 {stamp:%m-%d %H:%M}\n来源：Open-Meteo / GeoNames"
        carrier,number=parcel_args(arg)
        if carrier!="DHL":
            body=json.dumps({"ShipperCode":CARRIERS[carrier],"LogisticCode":number},separators=(",",":"))
            signature=hashlib.md5((body+os.environ["ERGOU_KDN_KEY"]).encode(),usedforsecurity=False).hexdigest().encode()
            fields=dict(EBusinessID=os.environ["ERGOU_KDN_ID"],RequestType="1002",RequestData=body,DataType=2,DataSign=base64.b64encode(signature).decode())
            data=request(KDN,fields,deadline)
            if data.get("Success") is not True:
                raise ProviderError("快递鸟未受理，请核对账号权限及免费额度")
            status={"0":"暂无轨迹","1":"已揽收","2":"运输中","3":"已签收","4":"问题件"}.get(str(data.get("State")),"暂无明确状态")
            return f"📦 {carrier}　{status}\n来源：快递鸟"
        data=request(DHL,dict(trackingNumber=number),deadline,{"DHL-API-Key":os.environ["ERGOU_DHL_KEY"]})
        if not data.get("shipments"):
            raise ProviderError("快递查询无结果")
        code=data["shipments"][0]["status"]["statusCode"]
        status={"pre-transit":"待揽收","transit":"运输中","delivered":"已送达","failure":"投递异常","unknown":"暂无明确状态"}.get(code,"暂无明确状态")
        return "DHL · "+status
    except ProviderError:
        raise
    except (KeyError,TypeError,ValueError,IndexError,AttributeError):
        raise ProviderError("供应商数据格式异常") from None


def work(db,request=fetch):
    from .engine import queue
    from . import native_voice
    now=time.time()
    with transaction(db):
        row=db.execute("""SELECT q.*,i.grp,i.binding,i.account,i.event_id,i.arrived,i.adapter_version FROM queries q JOIN inbox i ON i.seq=q.id
                        WHERE q.state='PENDING' OR (q.state='RUNNING' AND q.lease<?) ORDER BY q.id LIMIT 1""",(now,)).fetchone()
        if not row:
            return False
        if now-row["arrived"]>=120:
            db.execute("UPDATE queries SET state='EXPIRED',argument=NULL WHERE id=?",(row["id"],))
            return True
        lease=now+15
        db.execute("UPDATE queries SET state='RUNNING',lease=? WHERE id=?",(lease,row["id"]))

    def check():
        if row["adapter_version"] == native_voice.VERSION and not native_voice.event_authorized(db, row["id"]):
            raise native_voice.Cancelled()

    try:
        if row["kind"]=="天气" and request is fetch:
            from .bulletins import weather_request
            request=weather_request
        check()
        reply=lookup(row["kind"],row["argument"],request,check=check)
        state="DONE"
    except native_voice.Cancelled:
        state="CANCELLED"
    except ProviderError as exc:
        reply,state=str(exc),"FAILED"
    with transaction(db):
        if state=="CANCELLED" or (row["adapter_version"] == native_voice.VERSION
                                  and not native_voice.event_authorized(db, row["id"])):
            db.execute("""UPDATE queries SET state='CANCELLED',argument=NULL,result=NULL WHERE id=?
                        AND lease=? AND state='RUNNING'""",(row["id"],lease))
            return True
        if not db.execute("UPDATE queries SET state=?,result=?,argument=NULL WHERE id=? AND lease=? AND state='RUNNING'",
                          (state,state,row["id"],lease)).rowcount:
            return True
        if state=="DONE":
            db.execute("DELETE FROM breaker WHERE kind=?",(row["kind"],))
            if row["kind"]=="天气":
                db.execute("INSERT OR REPLACE INTO weather_cache VALUES(?,?,?)",(row["argument"],now,reply))
        else:
            record_failure(db,row["grp"],row["id"],row["kind"],reply)
            db.execute("""INSERT INTO breaker VALUES(?,1,0) ON CONFLICT(kind) DO UPDATE SET failures=failures+1,
                       reopen=CASE WHEN failures>=2 THEN ? ELSE 0 END""",(row["kind"],now+30))
        g=db.execute("SELECT * FROM groups WHERE id=?",(row["grp"],)).fetchone()
        if g["account"]==row["account"] and g["binding"]==row["binding"] and not g["paused"]:
            if row["kind"]=="百科" and state=="FAILED":
                from .leisure import search_link
                reply+="\n可手动检索："+search_link(row["argument"])
            queue(db,g,row["event_id"],reply,row["arrived"])
    return True

