"""按鱼获编号保存终身进度。调用方在入站写事务内结算。"""
import re
from random import Random

from . import breeding, fish_grades
from .display_names import labels
from .fishing_waters import SPECIES, giant_max, size_grade

SECONDS = 180
ROUNDS = 10
SLOTS = (1, 1, 2, 2, 3)
FEED_ROUNDS = 3
# 原价下界、三轮饲料价。尾档按原价比例向上取整。
FEED_PRICE_DIVISOR = 16
FEED_PRICES = ((0, 1), (12, 2), (35, 3), (80, 5))
NATURAL_GAIN, FED_GAIN = .46, .82
NATURAL_INCREMENT, FED_INCREMENT = (1, 4), (2, 6)  # 原重百分比
LOOK_CHANCE = (.05, .22)
LOOK_MAX = 15
PROMOTION = (.001, .003)  # 一级塘，无投喂 / 全投喂
ACTION = re.compile(r"(投喂|换入成长位|设为招牌鱼)\s*[#＃]([1-9][0-9]{0,17})")


def mark(db, key, now, action):
    db.execute("""INSERT OR IGNORE INTO pond_activity VALUES(date(?,'unixepoch','+8 hours'),?,?,?)""",
               (now, *key, action))


def cap(fish, original):
    species = SPECIES.get(fish)
    if not species:
        return original
    giant = size_grade(fish, original) == "巨物"
    limit = giant_max(species) if giant else species[2]
    return max(original, min(limit, original * (110 if giant else 130) // 100))


def feed_cost(original_price, rounds):
    price = max(cost for floor, cost in FEED_PRICES if original_price >= floor)
    price = max(price, (original_price + FEED_PRICE_DIVISOR - 1) // FEED_PRICE_DIVISOR)
    return (price * min(FEED_ROUNDS, ROUNDS - rounds) + FEED_ROUNDS - 1) // FEED_ROUNDS


def advance(fish, state, grams, grade, level, rng):
    """推进一轮；模拟与实际结算使用同一组规则。"""
    original = state["original_grams"]
    fed = state["food"] > 0
    if state["first_fed"] or rng.random() < (FED_GAIN if fed else NATURAL_GAIN):
        pct = rng.randint(*(FED_INCREMENT if fed else NATURAL_INCREMENT))
        grams = min(cap(fish, original), grams + max(1, original * pct // 100))
    if rng.random() < LOOK_CHANCE[int(fed)]:
        state["appearance"] = max(state["appearance"], rng.randint(1, LOOK_MAX))
    state["first_fed"] = 0
    state["food"] -= int(fed)
    state["fed_segment"] += int(fed)
    state["rounds"] += 1
    if state["rounds"] % 3 == 0:
        chance = (PROMOTION[0] + (PROMOTION[1] - PROMOTION[0]) * state["fed_segment"] / 3)
        if grade < 4 and not state["promoted"] and rng.random() < chance * (1 + (level-1)/4):
            grade += 1
            state["promoted"] = 1
        state["fed_segment"] = 0
    return grams, grade


def valuation(fish, state, grams, grade):
    original = fish_grades.price(fish, state["original_grams"], state["original_grade"])
    updated = fish_grades.price(fish, grams, grade, state["appearance"])
    return state["original_price"] + max(0, updated - original)


SELECT = """SELECT g.*,p.grp,p.member,p.fish,p.grams,p.price,p.grade,
 coalesce(l.level,1) level FROM fishing_pond p JOIN pond_growth g ON g.item=p.id
 LEFT JOIN fishing_storage_levels l ON l.grp=p.grp AND l.member=p.member AND l.storage='pond'
 WHERE p.storage='pond' AND p.grp=?"""


def round_rng(item,round_no):
    return Random(f"pond/v1:{item}:{round_no}")


def settle(db, group, now, member=None):
    params = [group, now]
    query = SELECT + " AND g.next_at<=?"
    if member is not None:
        query += " AND p.member=?"
        params.append(member)
    changes = {}
    for row in db.execute(query, params).fetchall():
        child = breeding.fry(db,row["item"])
        if child:
            changes[row["item"]] = breeding.settle_fry(db,row,child,now)
            continue
        state = dict(row)
        fish, grams, grade, due = (row[k] for k in ("fish","grams","grade","next_at"))
        while due <= now and state["rounds"] < ROUNDS and grams < cap(fish, state["original_grams"]):
            rng = round_rng(row["item"],state["rounds"])
            grams, grade = advance(fish, state, grams, grade, row["level"], rng)
            due += SECONDS
        if state["rounds"] >= ROUNDS or grams >= cap(fish, state["original_grams"]):
            due = None
            state["food"] = 0
        db.execute("""UPDATE pond_growth SET rounds=?,appearance=?,promoted=?,food=?,first_fed=?,
                      fed_segment=?,next_at=? WHERE item=?""",
                   (*(state[k] for k in ("rounds","appearance","promoted","food","first_fed","fed_segment")),due,row["item"]))
        price = valuation(fish, state, grams, grade)
        db.execute("UPDATE fishing_pond SET grams=?,grade=?,price=? WHERE id=? AND grp=? AND member=?",
                   (grams,grade,price,row["item"],group,row["member"]))
        changes[row["item"]] = (grams-row["grams"],state["appearance"]-row["appearance"],grade-row["grade"])
    return changes


def register(db, item, catcher=None):
    db.execute("""INSERT OR IGNORE INTO pond_growth(item,original_grams,original_price,original_grade,catcher)
                  SELECT id,grams,price,grade,? FROM fishing_pond WHERE id=?""",(catcher,item))


def pause(db, item, now):
    db.execute("""UPDATE pond_growth SET remaining_seconds=max(0,next_at-?),next_at=NULL
                  WHERE item=? AND next_at IS NOT NULL""",(now,item))


def leave(db, item, now):
    pause(db,item,now)
    db.execute("UPDATE pond_growth SET flagship=0 WHERE item=?",(item,))


def install(db, key, item, now, replace=False):
    register(db,item)
    row = db.execute(SELECT + " AND p.member=? AND p.id=?",(*key,item)).fetchone()
    if not row:
        return "请从自己的鱼塘选鱼。"
    if row["next_at"] is not None:
        return "这条鱼已经在成长位。"
    child = breeding.fry(db,item)
    limit = child["adult"] if child else cap(row["fish"],row["original_grams"])
    if row["grade"] is None or row["rounds"] == ROUNDS or row["grams"] >= limit:
        return "🏁 这条鱼已定型。"
    slots = db.execute(SELECT+" AND p.member=? AND g.next_at IS NOT NULL ORDER BY p.id",key).fetchall()
    if len(slots) >= SLOTS[row["level"]-1]:
        if not replace:
            return "成长位已满，换入时会暂停编号最小的在养鱼。"
        pause(db,slots[0]["item"],now)
    db.execute("UPDATE pond_growth SET next_at=?+coalesce(remaining_seconds,?),remaining_seconds=NULL WHERE item=?",
               (now,SECONDS,item))
    return "🌱 已进入成长位，3 分钟一轮。"


def migrate(db, now):
    if not db.execute("INSERT OR IGNORE INTO pond_migrations VALUES(1)").rowcount:
        return
    for table, ident in (("fishing_pond","id"),("fishing_exhibits","item_id")):
        db.execute(f"""INSERT INTO pond_growth(item,original_grams,original_price,original_grade)
                       SELECT {ident},grams,price,grade FROM {table}""")
    for row in db.execute("SELECT grp,member,id FROM fishing_pond WHERE storage='pond' ORDER BY grp,member,id").fetchall():
        install(db,tuple(row[:2]),row[2],now)


def act(db, key, action, item, now, prefix):
    row = db.execute(SELECT+" AND p.member=? AND p.id=?",(*key,item)).fetchone()
    if not row:
        return "你的鱼塘里没有这条鱼。"
    if action == "设为招牌鱼":
        db.execute("""UPDATE pond_growth SET flagship=0 WHERE flagship=1 AND item IN
                      (SELECT id FROM fishing_pond WHERE grp=? AND member=? AND storage='pond')""",key)
        db.execute("UPDATE pond_growth SET flagship=1 WHERE item=?",(item,))
        return f"🌟 {labels(db,key[0])(key[1],'你')}的招牌鱼　#{item} {row['fish']}\n免于被偷。"
    if action == "换入成长位":
        result = install(db,key,item,now,True)
        if result.startswith("🌱"):
            mark(db,key,now,"tend")
        return result
    if breeding.fry(db,item):
        return "繁育鱼使用独立成长曲线，无需投喂。"
    if row["rounds"] == ROUNDS or row["grams"] >= cap(row["fish"],row["original_grams"]):
        return "🏁 已定型，饲料留给其他鱼吧。"
    if row["next_at"] is None:
        return f"先让它进入成长位　{prefix}换入成长位#{item}"
    if row["food"]:
        return f"🍤 还有 {row['food']} 轮饲料。"
    cost = feed_cost(row["original_price"],row["rounds"])
    if not db.execute("UPDATE fishing_wallets SET coins=coins-? WHERE grp=? AND member=? AND coins>=?",
                      (cost,*key,cost)).rowcount:
        return f"鱼币不足，这份饲料需要 {cost} 鱼币。"
    count = min(FEED_ROUNDS,ROUNDS-row["rounds"])
    db.execute("UPDATE pond_growth SET food=?,first_fed=1 WHERE item=?",(count,item))
    mark(db,key,now,"tend")
    return f"🍤 已投喂 #{item} {row['fish']}　−{cost} 鱼币\n覆盖接下来 {count} 轮，下一轮保证增重。"
