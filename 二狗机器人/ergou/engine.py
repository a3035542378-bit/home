import json
import re
import sqlite3
import time
import uuid
from contextlib import nullcontext
from datetime import datetime

from . import community, plugins, retention
from .db import BJ, allowed, audit, closing_db, dump, transaction, window
from .games import GAMES, RULE_VERSION, start_board, visible_board

ACTIVE = "('RUNNING','PAUSED','WAITING_PLAYERS')"
KINDS = {"message","join","baseline","leave","revoke","bot_leave"}
LIMIT = 50000


def addressed_command(text, prefix, mentioned):
    if mentioned:
        # WeChat terminates a selected display name (including its spaces) with U+2005.
        # Keep ordinary body text on either side of the selected name.
        text=re.sub(r"^(开启智能对话|关闭智能对话)(?=[@＠])",r"\1 ",text)
        text,count=re.subn(r"(?<!\S)[@＠][^@＠\u2005\r\n]{1,100}\u2005"," ",text)
        text=text.strip()
        if not count:
            text=re.sub(r"^[@＠][^\s@＠]+(?:\s+|$)","",text,count=1).strip()
            text=re.sub(r"\s+[@＠][^\s@＠]+$","",text,count=1).strip()
    if text.startswith(prefix):
        return text[len(prefix):].lstrip(" +，,:：")
    return text if mentioned else None


def receive(db, account, group, member, source, payload, *, kind="message", message_type="text", adapter_version="sim/1", now=None):
    if not all(isinstance(s,str) and 0 < len(s) <= 160 for s in (account,group,member,source,adapter_version)):
        raise ValueError("INVALID_ARGUMENT 缺少稳定标识或标识过长")
    body = dump(payload)
    if not isinstance(payload,dict) or len(body.encode())>8192 or kind not in KINDS:
        raise ValueError("INVALID_ARGUMENT 事件格式或大小无效")
    with nullcontext() if db.in_transaction else transaction(db):
        old = db.execute("SELECT seq FROM inbox WHERE account=? AND source=?",(account,source)).fetchone()
        if old:
            return old[0]
        binding = db.execute("SELECT * FROM groups WHERE id=?",(group,)).fetchone()
        if not binding or not db.execute("SELECT 1 FROM membership WHERE account=? AND grp=?",(account,group)).fetchone():
            raise ValueError("FORBIDDEN 未登记群或账号")
        capacity=db.execute("SELECT count,bytes FROM inbox_capacity WHERE singleton=1").fetchone()
        if capacity[0]>=LIMIT or capacity[1]+len(body.encode())>64*1024*1024:
            raise ValueError("RATE_LIMITED 入站队列已满，请稍后重试")
        event = uuid.uuid4().hex
        state = "PENDING" if binding["account"]==account and not binding["paused"] else "IGNORED"
        seq=db.execute("""INSERT INTO inbox(event_id,source,account,grp,member,kind,message_type,arrived,binding,
                       adapter_version,trace,payload,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (event,source,account,group,member,kind,message_type,time.time() if now is None else now,
                        binding["binding"],adapter_version,event,body if state=="PENDING" else None,state)).lastrowid
        return seq


def queue(db, group, key, body, now, ttl=120):
    if db.execute("SELECT 1 FROM listener_nodes WHERE account=?",(group["account"],)).fetchone():
        match=db.execute("""SELECT d.source_time FROM directed_events d JOIN inbox i ON i.event_id=d.biz
            JOIN directed_groups p ON p.grp=i.grp AND p.account=i.account AND p.binding=i.binding
            WHERE d.biz=? AND i.grp=? AND i.account=? AND i.binding=? AND d.source_time>=p.since""",
            (key,group["id"],group["account"],group["binding"])).fetchone()
        if not match:
            from .native_voice import event_authorized
            voice=db.execute("""SELECT i.seq,v.source_time FROM inbox i JOIN native_voice_events v ON v.seq=i.seq
                WHERE i.event_id=? AND i.grp=? AND i.account=? AND i.binding=? AND i.message_type='voice'""",
                (key,group["id"],group["account"],group["binding"])).fetchone()
            if voice:
                if not event_authorized(db,voice["seq"]):
                    return
                match=(voice["source_time"],)
        if match:
            if match[0]+120<=time.time():
                return
            ttl=min(ttl,match[0]+120-now)
        else:
            from .live_notice import matches
            if not matches(db,group["id"],key,body):
                return
    db.execute("""INSERT OR IGNORE INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
               VALUES(?,?,?,?,?,'PENDING',?,?,?)""",(key,group["account"],group["id"],group["binding"],body,now,now+ttl,now))


def expire(db, group, now):
    db.execute(f"""UPDATE games SET state='EXPIRED',ended=deadline,reason='到时结束'
                WHERE grp=? AND state IN {ACTIVE} AND deadline<=?""",(group,now))


def sessions(db, group):
    return db.execute(f"SELECT * FROM games WHERE grp=? AND state IN {ACTIVE} ORDER BY id",(group,)).fetchall()


def summary(rows):
    return "、".join(f"{r['code']} {r['game']}" for r in rows) or "暂无进行中的会话"


def start(db,g,e,name,cfg):
    rows=sessions(db,g["id"])
    if len(rows)>=cfg["max_games"]:
        raise ValueError("本群会话已满："+summary(rows))
    if any(r["game"]==name for r in rows):
        raise ValueError("本群已开同款："+summary(rows))
    game=GAMES.get(name)
    if name in cfg.get("disabled_games",[]):raise ValueError("本群未启用该游戏")
    plugin=None if game else plugins.active(db).get(name)
    if not game and not plugin:
        raise ValueError("未找到该游戏，可查看游戏列表")
    no=db.execute("SELECT COUNT(*)+1 FROM games WHERE grp=?",(g["id"],)).fetchone()[0]
    code=f"G{no:02}"
    board=start_board(game,e["event_id"]) if game else {"node":plugin["start"]}
    prompt=game.prompt if game else plugin["prompt"]+" 可行动作："+"、".join(plugin["states"][plugin["start"]])
    if game and game.id in ("song_quiz","idiom_quiz","emoji_quiz"):
        prompt+=" 题面："+board["clue"]
    snapshot=dict(version=RULE_VERSION,game_id=game.id if game else plugin["id"],reward=cfg["reward"],config_version=g["version"],initial=board,prompt=prompt,daily_rewards=cfg.get("daily_rewards",0))
    if plugin:snapshot["plugin"]=plugin
    cur=db.execute("""INSERT INTO games(grp,code,game,owner,state,rules,board,started,deadline)
                   VALUES(?,?,?,?,'RUNNING',?,?,?,?)""",(g["id"],code,name,e["member"],dump(snapshot),dump(board),e["arrived"],e["arrived"]+600))
    db.execute("INSERT INTO players VALUES(?,?,?)",(cur.lastrowid,e["member"],e["arrived"]))
    return f"{code} {name} · 10 分钟 · 完成者 +{cfg['reward']} 分。{prompt} 输入「{cfg['prefix']} {code} 动作」。"


def play(db,e,action,code,arg,manager):
    row=db.execute("SELECT * FROM games WHERE grp=? AND code=?",(e["grp"],code)).fetchone()
    if not row:
        raise ValueError("会话不存在")
    state=row["state"]
    if action=="状态":
        rules=json.loads(row["rules"])
        view=visible_board(rules["game_id"],json.loads(row["board"]))
        count=db.execute("SELECT COUNT(*) FROM players WHERE game=?",(row["id"],)).fetchone()[0]
        cutoff=datetime.fromtimestamp(row["deadline"],BJ).strftime("%H:%M:%S")
        return f"{code} {row['game']} · {state} · {count} 人 · {cutoff} 截止 · "+(row["reason"] or view)
    if state!="RUNNING":
        raise ValueError("当前会话状态 "+state)
    if action=="结束":
        if e["member"]!=row["owner"] and not manager:
            raise ValueError("FORBIDDEN 仅发起人或群管理员可结束")
        db.execute("UPDATE games SET state='CANCELLED',ended=?,reason='主动结束' WHERE id=?",(e["arrived"],row["id"]))
        return f"{code} 已取消"
    if action=="退出":
        if e["member"]==row["owner"]:raise ValueError("发起人可用结束指令取消本局")
        db.execute("DELETE FROM players WHERE game=? AND member=?",(row["id"],e["member"]))
        return f"已退出 {code}"
    if action=="加入":
        if db.execute("SELECT COUNT(*) FROM players WHERE game=?",(row["id"],)).fetchone()[0]>=32 and not db.execute("SELECT 1 FROM players WHERE game=? AND member=?",(row["id"],e["member"])).fetchone():
            raise ValueError("本局已满 32 人")
        db.execute("INSERT OR IGNORE INTO players VALUES(?,?,?)",(row["id"],e["member"],e["arrived"]))
        return f"已加入 {code}"
    if not db.execute("SELECT 1 FROM players WHERE game=? AND member=?",(row["id"],e["member"])).fetchone():
        raise ValueError(f"请先加入 {code}")
    rules=json.loads(row["rules"])
    if rules["version"]!=RULE_VERSION:
        raise ValueError("规则版本未加载")
    board=json.loads(row["board"])
    if arg=="重置":
        if e["member"]!=row["owner"] and not manager:
            raise ValueError("仅发起人或管理员可重置")
        board=rules["initial"]
        won,msg=False,"已恢复初始局面。"+rules["prompt"]
    elif "plugin" in rules:
        won,msg=plugins.move(rules["plugin"],board,arg)
    else:
        won,msg=GAMES[row["game"]].move(board,arg)
    db.execute("UPDATE games SET board=? WHERE id=?",(dump(board),row["id"]))
    if won:
        db.execute("UPDATE games SET state='FINISHED',ended=?,reason='完成目标' WHERE id=?",(e["arrived"],row["id"]))
        cap=rules.get("daily_rewards",0)
        midnight=datetime.fromtimestamp(e["arrived"],BJ).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        if cap and db.execute("SELECT COUNT(*) FROM ledger l JOIN games g ON g.id=l.game WHERE l.member=? AND l.grp=? AND g.game=? AND l.kind='胜利' AND l.at>=?",(e["member"],e["grp"],row["game"],midnight)).fetchone()[0]>=cap:
            return f"{code} {msg} · 已完成，今日奖励次数已满"
        db.execute("""INSERT INTO ledger(grp,member,game,round,kind,points,rule_version,event,at,reason)
                   VALUES(?,?,?,1,'胜利',?,?,?,?,?)""",(e["grp"],e["member"],row["id"],rules["reward"],rules["version"],e["event_id"],e["arrived"],"完成目标"))
        msg+=f" · 完成！+{rules['reward']} 分"
    return f"{code} {msg}"


def ranking_rows(db,group,period,now):
    return db.execute("""SELECT member,SUM(points) total,DENSE_RANK() OVER(ORDER BY SUM(points) DESC) place
                     FROM ledger WHERE grp=? AND at>=? AND at<=? GROUP BY member ORDER BY total DESC,member LIMIT 20""",
                    (group,window(period,now),now)).fetchall()


def ranking(db,group,period,now):
    from .display_names import labels
    name=labels(db,group)
    rows=ranking_rows(db,group,period,now)
    scores=[f"第{r['place']}名　{name(r['member'])}　{r['total']}分" for r in rows]
    return f"🏅 本群积分{period}\n\n"+("\n".join(scores) or "本周期暂无积分")


def command(db,g,e,cmd,cfg,mentioned=False,*,prefix=None):
    from . import feature_menu, fishing, intents, leisure, models, reply_rules
    cmd=cmd.strip()
    if cmd in ("开启智能对话","关闭智能对话"):
        return models.switch(db,e,cmd=="开启智能对话",mentioned)
    canonical=intents.command_alias(cmd)
    if canonical.rstrip("。！？!?").strip() in ("菜单","功能菜单","全部功能"):
        return feature_menu.render(db,g,e,cfg,prefix or cfg["prefix"])
    if cmd and models.api_first(db,e["grp"]):
        if canonical=="游戏列表" and cfg["games"] and "钓鱼" not in cfg.get("disabled_games",[]):
            return "智能对话中可直接玩：\n"+fishing.game_list_entry(prefix or cfg["prefix"])
        if fishing.matches(canonical):
            return fishing.play(db,e,canonical,prefix or cfg["prefix"],cfg)
        return models.submit(db,e,cmd)
    try:
        matched=reply_rules.match(db,e,cmd)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError):
        from .db import record_failure
        record_failure(db,e["grp"],e["seq"],"回复规则","规则格式异常")
        return "本群的自定义回复规则出现异常，请运营人员检查规则设置。"
    if matched is not None:
        return matched
    cmd=leisure.normalize(intents.interpret(canonical,cfg))
    first,_,args=cmd.strip().partition(" ")
    first=cfg.get("aliases",{}).get(first,first)
    args=args.strip()
    if first in ("帮助",""):
        return feature_menu.render(db,g,e,cfg,prefix or cfg["prefix"])
    manager=bool(db.execute("SELECT 1 FROM managers WHERE grp=? AND member=?",(e["grp"],e["member"])).fetchone())
    if fishing.matches(cmd):
        return fishing.play(db,e,cmd,prefix or cfg["prefix"],cfg)
    if first=="群规":
        return cfg["rules"]
    if first=="运势":
        return community.fortune(e["member"],e["arrived"])
    if first=="星座":
        return intents.horoscope(args,e["arrived"])
    if first in ("兑换","兑换列表"):
        from .group_tools import redeem
        return redeem(db,e,args if first=="兑换" else "")
    if first=="积分":
        score=db.execute("SELECT COALESCE(SUM(points),0) FROM ledger WHERE grp=? AND member=?",(e["grp"],e["member"])).fetchone()[0]
        return f"本群积分 {score}"
    if first in ("总榜","周榜","月榜"):
        return ranking(db,e["grp"],first,e["arrived"])
    if first in ("投票","抽签"):
        op,enabled=(community.poll,cfg["polls"]) if first=="投票" else (community.draw,cfg["draws"])
        if not enabled:
            raise ValueError("本群已关闭此功能")
        return op(db,e,args,manager)
    if first in ("点歌","菜谱"):
        reply=leisure.local(first,args)
        if first=="点歌" and args and e["adapter_version"]=="agent-wechat-events/2.7.1":
            queue(db,g,e["event_id"],reply,e["arrived"])
            db.execute("""INSERT OR IGNORE INTO music_search_cards SELECT id,?,? FROM outbox
                          WHERE biz=? AND body=?""",(args,reply.splitlines()[-1],e["event_id"],reply))
            return None
        return reply
    if first=="百科" and not args:
        return "想查什么词条？例如「二狗百科 大熊猫」。"
    if first in ("天气","快递","百科"):
        from .queries import submit
        return submit(db,e,first,args or (cfg["city"] if first=="天气" else ""))
    game_command=first in ("游戏列表","开始","加入","退出","状态","结束") or re.fullmatch(r"G[0-9]+",first.upper())
    if game_command and not cfg["games"]:
        raise ValueError("本群游戏已关闭")
    if first=="游戏列表":
        names="、".join(n for n in [*GAMES,*plugins.active(db)] if n not in cfg.get("disabled_games",[]))
        if "钓鱼" in cfg.get("disabled_games",[]):
            return names
        return "\n".join(filter(None,(fishing.game_list_entry(prefix or cfg["prefix"]),names)))
    if first=="开始":
        return start(db,g,e,args,cfg)
    if first in ("加入","退出","状态","结束"):
        return play(db,e,first,args.upper(),"",manager)
    if re.fullmatch(r"G[0-9]+",first.upper()):
        return play(db,e,"动作",first.upper(),args,manager)
    rows=sessions(db,g["id"])
    if len(rows)>1 and first.isdecimal():
        raise ValueError("请指定会话："+summary(rows))
    from .models import submit
    return submit(db,e,cmd.strip())


def process(db,g,e):
    cfg=json.loads(g["config"])
    p=json.loads(e["payload"])
    if not cfg["enabled"] or g["paused"] or g["account"]!=e["account"] or g["binding"]!=e["binding"]:
        return "IGNORED",None
    if e["member"] in [g["account"],*cfg["bots"]] or p.get("is_bot"):
        return "IGNORED",None
    from .moderation import excluded
    if excluded(db,e):
        return "IGNORED",None
    if e["kind"]=="baseline":
        for member in p.get("members",[]):
            db.execute("INSERT OR IGNORE INTO known_members VALUES(?,?)",(e["grp"],member))
        return "DONE",None
    if e["kind"] in ("join","leave"):
        from .display_names import labels
        label=labels(db,g["id"])(e["member"],p.get("name"))
    if e["kind"]=="join":
        if db.execute("INSERT OR IGNORE INTO known_members VALUES(?,?)",(e["grp"],e["member"])).rowcount:
            from .member_policy import active
            if "join" not in active(db,g["id"],g["account"],g["binding"]):
                return "DONE",None
            seconds=cfg.get("welcome_window",0)
            if seconds:
                prior=db.execute("SELECT MIN(due) FROM welcomes WHERE grp=? AND due>=?",(e["grp"],e["arrived"])).fetchone()[0]
                db.execute("INSERT OR REPLACE INTO welcomes VALUES(?,?,?,?,?,?)",(e["grp"],e["account"],e["binding"],e["member"],label,prior or e["arrived"]+seconds))
                return "DONE",None
            from .greetings import welcome
            return "DONE",welcome(cfg,label,g["id"],e["arrived"])
        return "IGNORED",None
    if e["kind"]=="bot_leave":
        db.execute("UPDATE groups SET paused=1 WHERE id=?",(e["grp"],))
        db.execute("UPDATE outbox SET state='CANCELLED' WHERE grp=? AND state IN ('PENDING','RETRY_WAIT')",(e["grp"],))
        return "DONE",None
    if e["kind"]=="leave":
        db.execute("DELETE FROM welcomes WHERE grp=? AND member=?",(e["grp"],e["member"]))
        present=db.execute("SELECT 1 FROM known_members WHERE grp=? AND member=?",(e["grp"],e["member"])).fetchone()
        for table in ("known_members","candidates","managers"):
            db.execute(f"DELETE FROM {table} WHERE grp=? AND member=?",(e["grp"],e["member"]))
        from .member_policy import active
        if present and "leave" in active(db,g["id"],g["account"],g["binding"]):
            from .member_notices import departure
            return "DONE",departure(label)
        return "DONE",None
    if e["kind"]=="revoke":
        db.execute("INSERT OR IGNORE INTO recalls VALUES(?,?,?,?)",(e["seq"],e["grp"],str(p.get("original_source",""))[:160],e["arrived"]))
        audit(db,"adapter",e["grp"],"撤回事件","仅元数据")
        return "DONE",None
    text=p.get("text","")
    from . import native_voice
    voice=(e["message_type"]=="voice" and e["adapter_version"]==native_voice.VERSION
           and native_voice.event_authorized(db,e["seq"]))
    if not isinstance(text,str) or (e["message_type"]!="text" and not voice):
        return "IGNORED",None
    live_listener=e["adapter_version"]=="agent-wechat-events/2.7.1"
    mentioned=not voice and p.get("mention_account")==g["account"]
    prefix="二狗" if live_listener or voice else cfg["prefix"]
    cmd=addressed_command(text,prefix,mentioned)
    if cmd is None and p.get("pond_target") and e["message_type"]=="text":
        from .pond_raids import TARGET
        if TARGET.fullmatch(text.strip()):
            cmd=text.strip()
    authorized_control=(mentioned and cmd in ("开启智能对话","关闭智能对话") and db.execute(
        """SELECT 1 FROM smart_controls c,json_each(c.admins) m WHERE c.grp=? AND m.value=?""",
        (e["grp"],e["member"])).fetchone())
    moderation=None
    if e["member"] not in cfg["allowlist"] and (text in cfg.get("exact_words",[]) or any(word in text for word in cfg["words"])):
        db.execute("INSERT INTO hits(grp,seq,version,result) VALUES(?,?,?,?)",(e["grp"],e["seq"],g["version"],cfg["moderation"]))
        if cfg["moderation"] in ("撤回","移出群聊") and not authorized_control:
            from .moderation import apply_action
            return "DONE",apply_action(db,g,e,cfg["moderation"])
        if cfg["moderation"]=="提醒" and not authorized_control:
            moderation="请留意本群群规："+cfg["rules"]
    if cmd is None:
        if moderation:
            return "DONE",moderation
        return "CHAT",None
    if not authorized_control and not allowed(db,dump(["cmd",e["grp"],e["member"]]),cfg.get("command_rate",30),10,e["arrived"]):
        return "RATE_LIMITED",None
    stamp=p.get("source_time")
    if live_listener and type(stamp) in (int,float) and e["arrived"]-120<stamp<=e["arrived"]+5:
        db.execute("""INSERT OR IGNORE INTO directed_events SELECT ?,? FROM directed_groups p
                      JOIN agent_wechat_links l ON l.account=p.account AND l.grp=p.grp
                      WHERE p.grp=? AND p.account=? AND p.binding=? AND p.since<=? AND ?='agent-wechat-events/2.7.1'""",
                   (e["event_id"],stamp,e["grp"],e["account"],e["binding"],stamp,e["adapter_version"]))
    # Preserve authorization for a directed command's validation reply while
    # undoing any partial game, ledger, or model work performed by the command.
    db.execute("SAVEPOINT addressed_command")
    try:
        if moderation:
            return "DONE",moderation
        return "DONE",command(db,g,e,cmd,cfg,mentioned,prefix=prefix)
    except ValueError as exc:
        db.execute("ROLLBACK TO addressed_command")
        notify=allowed(db,dump(["errors",e["grp"],e["member"]]),3,10,e["arrived"])
        return "REJECTED",str(exc) if notify else None
    finally:
        db.execute("RELEASE addressed_command")


def step(db):
    with transaction(db):
        e=db.execute("SELECT * FROM inbox WHERE state='PENDING' ORDER BY seq LIMIT 1").fetchone()
        if not e:
            return False
        g=db.execute("SELECT * FROM groups WHERE id=?",(e["grp"],)).fetchone()
        expire(db,e["grp"],e["arrived"])
        db.execute("SAVEPOINT business")
        try:
            state,msg=process(db,g,e)
            if msg:
                queue(db,g,e["event_id"],msg,e["arrived"])
        except ValueError as exc:
            db.execute("ROLLBACK TO business")
            state,msg="REJECTED",str(exc)
            if allowed(db,dump(["errors",e["grp"],e["member"]]),3,10,e["arrived"]):
                queue(db,g,e["event_id"],msg,e["arrived"])
        except (KeyError,TypeError,IndexError,RuntimeError):
            db.execute("ROLLBACK TO business")
            db.execute("UPDATE inbox SET retries=retries+1,result='BUSINESS_ERROR',state=CASE WHEN retries>=2 THEN 'FAILED' ELSE 'PENDING' END WHERE seq=?",(e["seq"],))
            return True
        db.execute("RELEASE business")
        if e["kind"]=="message" and e["message_type"]=="text" and state not in ("IGNORED","FAILED"):
            if db.execute("SELECT 1 FROM retention WHERE grp=? AND since<=?",(e["grp"],e["arrived"])).fetchone():
                original=json.loads(e["payload"]).get("text")
                if isinstance(original,str):
                    retention.CACHE.put((e["grp"],e["account"],e["source"]),original,e["arrived"])
        db.execute("UPDATE inbox SET state=?,payload=NULL,result=? WHERE seq=?",(state,state,e["seq"]))
        return True

