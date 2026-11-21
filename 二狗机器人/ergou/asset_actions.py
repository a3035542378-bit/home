"""资产操作从入队占用到结算提交；两个玩家共用一次偷鱼占用。"""
from contextlib import contextmanager
from threading import Lock

from . import breeding, exhibit_batch, fish_storage, fishing_bait, intents, pond_growth, pond_raids, rod, storage_batch


BUSY_REPLY = "操作太快啦，稍等一下哦"
BUSY_RESULT = "ASSET_BUSY"
MUTATIONS = {"升级鱼塘", "卖出鱼包", "一键卖鱼", "买鱼线", "购买鱼线", "修理鱼竿",
             "升级鱼线", "升级鱼竿", "强化鱼竿", "回退强化"}
_admitting = {}
_registry_lock = Lock()


def participants(cmd, member, target, cfg):
    batch = storage_batch.match(cmd)
    if batch and batch[2]:
        return (member,)
    if exhibit_batch.parse(cmd) is not None:
        return (member,)
    cmd = intents.interpret(intents.command_alias(cmd), cfg)
    first, _, args = cmd.partition(" ")
    if (cmd == "偷鱼" or pond_raids.TARGET.fullmatch(cmd)) and isinstance(target, str) and target:
        return tuple(sorted({member, target}))
    cast = first in ("抛竿", "钓鱼") and (not args or args.strip() in fishing_bait.BAITS)
    redeem = cfg.get("aliases", {}).get(first, first) == "兑换" and args.strip()
    if (cmd=="领取幼鱼" or breeding.PAIR.fullmatch(cmd) or cast or redeem or cmd in MUTATIONS or fish_storage.ITEM.fullmatch(cmd)
            or pond_growth.ACTION.fullmatch(cmd) or pond_raids.BUY.fullmatch(cmd) or rod.REFORGE.fullmatch(cmd)):
        return (member,)
    return ()


def pending(db, group, members):
    return any(db.execute("SELECT 1 FROM asset_action_holds WHERE grp=? AND member=?",
                          (group, member)).fetchone() for member in members)


def reserve(db, group, members, seq):
    db.executemany("INSERT INTO asset_action_holds(grp,member,seq) VALUES(?,?,?)",
                   [(group, uid, seq) for uid in members])


@contextmanager
def admission(db, group, members, event_key):
    if not members:
        yield False
        return
    path = db.execute("PRAGMA database_list").fetchone()[2] or id(db)
    keys = {(path, group, member) for member in members}
    with _registry_lock:
        owners = {_admitting[key] for key in keys if key in _admitting}
        acquired = not owners
        if acquired:
            _admitting.update(dict.fromkeys(keys, event_key))
    try:
        # 先读 WAL 快照。即使随后写入站回执需要等待，结算中的动作也不会被误放行。
        yield bool(owners - {event_key}) or pending(db, group, members)
    finally:
        if acquired:
            with _registry_lock:
                for key in keys:
                    del _admitting[key]
