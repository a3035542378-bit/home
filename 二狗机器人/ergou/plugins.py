"""Versioned, declarative game plugins. Only the finite-state interpreter executes."""
import json
import re
import subprocess
import sys
from pathlib import Path
from .db import audit,dump,transaction

RUNNER=Path(__file__).with_name("plugin_runner.py")


def install(db,path,actor="local-cli"):
    if Path(path).stat().st_size>32768:raise ValueError("插件清单超过 32 KiB")
    m=json.loads(Path(path).read_text(encoding="utf-8"))
    from .games import GAMES
    if not isinstance(m,dict) or m.get("core")!="1" or m.get("state_version")!=1:
        raise ValueError("插件不兼容")
    for k in ("id","version"):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,40}",str(m.get(k,""))):raise ValueError("插件标识不合法")
    if not re.fullmatch(r"[\w·-]{1,24}",m.get("name","")) or m["name"] in GAMES or m["name"] in ("帮助","状态","开始","积分","结束","加入"):
        raise ValueError("插件名称冲突或不合法")
    states=m["states"]
    if not isinstance(states,dict) or not 1<=len(states)<=100 or m.get("start") not in states:
        raise ValueError("状态图不合法")
    if not isinstance(m.get("goal"),list) or not m["goal"] or not set(m["goal"])<=set(states):
        raise ValueError("胜利状态无效")
    if not isinstance(m.get("prompt"),str) or not 1<=len(m["prompt"])<=500:
        raise ValueError("须提供游戏说明")
    for key,edges in states.items():
        if not isinstance(edges,dict) or len(edges)>32 or any(not isinstance(k,str) or not 1<=len(k)<=32 or v not in states for k,v in edges.items()):
            raise ValueError("动作或后继状态无效")
    seen=set();todo=[m["start"]]
    while todo:
        node=todo.pop()
        if node not in seen:
            seen.add(node);todo.extend(states[node].values())
    if not seen.intersection(m["goal"]):raise ValueError("目标不可达")
    with transaction(db):
        for row in db.execute("SELECT id,manifest FROM plugin_registry WHERE active=1"):
            if row["id"]!=m["id"] and json.loads(row["manifest"])["name"]==m["name"]:raise ValueError("其他插件已占用名称")
        prev=db.execute("SELECT manifest FROM plugin_registry WHERE id=? AND version=?",(m["id"],m["version"])).fetchone()
        if prev and prev[0]!=dump(m):raise ValueError("已有版本不可覆盖，请增加版本号")
        db.execute("UPDATE plugin_registry SET active=0 WHERE id=?",(m["id"],))
        db.execute("INSERT OR REPLACE INTO plugin_registry VALUES(?,?,1,?)",(m["id"],m["version"],dump(m)))
        audit(db,actor,None,"激活插件",m["id"]+"@"+m["version"])


def active(db):
    return {m["name"]:m for m in (json.loads(r[0]) for r in db.execute("SELECT manifest FROM plugin_registry WHERE active=1"))}


def move(m,board,text,timeout=1):
    try:
        result=subprocess.run([sys.executable,"-I","-X","utf8",str(RUNNER)],input=dump([m,board["node"],text]),
                              encoding="utf-8",capture_output=True,timeout=timeout,check=True)
        node=json.loads(result.stdout)
    except (OSError,subprocess.SubprocessError,ValueError):
        raise ValueError("插件执行失败或超时，原局面已保留") from None
    if node is None:raise ValueError("可行动作："+"、".join(m["states"][board["node"]]))
    board["node"]=node
    return node in m["goal"],node+" "+"、".join(m["states"][node])

