"""Optional bounded original-text cache. Contents exist only in this service process."""
import threading
import time
from collections import OrderedDict

from .db import audit,transaction


class RecallCache:
    def __init__(self,capacity=2048,byte_limit=2*1024*1024):
        self.capacity=capacity
        self.byte_limit=byte_limit
        self.items=OrderedDict()
        self.size=0
        self.lock=threading.Lock()

    def remove(self,key):
        self.size-=self.items.pop(key)[2]

    def put(self,key,text,at):
        size=len(text.encode())
        with self.lock:
            if key in self.items:self.remove(key)
            if size>self.byte_limit:return
            self.items[key]=(at,text,size)
            self.size+=size
            while self.size>self.byte_limit or len(self.items)>self.capacity:
                self.remove(next(iter(self.items)))

    def get(self,key,now):
        with self.lock:
            if key not in self.items:return None
            at,text,_=self.items[key]
            if now>=at+86400:
                self.remove(key);return None
            self.items.move_to_end(key)
            return text

    def purge(self,now,group=None):
        with self.lock:
            for key,(at,_,_) in list(self.items.items()):
                if now>=at+86400 or key[0]==group:self.remove(key)


CACHE=RecallCache()


def configure(db,u,group,notice):
    if u["role"]!="系统管理员":raise PermissionError("FORBIDDEN 仅系统管理员")
    if not isinstance(notice,str) or len(notice)>200:raise ValueError("告知记录最多 200 字")
    with transaction(db):
        db.execute("DELETE FROM retention WHERE grp=?",(group,))
        CACHE.purge(time.time(),group)
        if notice.strip():
            db.execute("INSERT INTO retention VALUES(?,?,?)",(group,notice,time.time()))
        audit(db,u["name"],group,"撤回留存开关","启用，已记录群内告知" if notice.strip() else "关闭并清理")


def read(db,u,group,seq):
    if u["role"]!="系统管理员":raise PermissionError("FORBIDDEN 仅系统管理员可反查")
    with transaction(db):
        row=db.execute("""SELECT r.source,i.account FROM recalls r JOIN inbox i ON i.seq=r.seq
                       JOIN retention t ON t.grp=r.grp WHERE r.seq=? AND r.grp=? AND r.at>=t.since""",(seq,group)).fetchone()
        text=CACHE.get((group,row["account"],row["source"]),time.time()) if row else None
        audit(db,u["name"],group,"撤回反查","命中" if text is not None else "内容不可用")
        return {"available":text is not None,"text":text if text is not None else "内容不可用"}

