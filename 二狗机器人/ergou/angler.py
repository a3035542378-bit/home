"""按有效抛竿计算钓手等级。概率按抛竿前的等级结算。"""

CASTS_PER_LEVEL = 10
PROTECTED_CASTS = 3

LIGHT_CATCH = (
    "浮漂轻轻一点。你提起竿，鱼尾拍了拍水面。",
    "你抛出一竿，屏住呼吸。漂尖一沉，收线！",
    "鱼线往旁一走，你顺势把鱼带了上来。",
)
HEAVY_CATCH = (
    "鱼竿弯成了弓。遛了好一会儿，终于收线！",
    "你稳住竿尖，等鱼游累了才慢慢收线。",
    "它露出背鳍又往下钻。两个来回，终于入网！",
)
SLIPPED = (
    "浮漂猛地一沉，你刚提竿，钩尖就滑了出来。",
    "线收到一半，鱼打了个挺，甩开了钩。",
    "竿尖抖了两下，手上忽然一轻。只收回一只空钩。",
)


def level(casts):
    return 1 + casts // CASTS_PER_LEVEL


def slip_percent(previous_casts, starter):
    if previous_casts < PROTECTED_CASTS:
        return 0
    base, minimum = (5, 2) if starter else (12, 5)
    return max(minimum, base - (level(previous_casts) - 1))


def advance(db, key, historical_catches):
    # 老玩家第一次使用新版时，从可核实的历史成功尾数起算。
    return db.execute("""INSERT INTO fishing_experience(grp,member,casts) VALUES(?,?,?)
                         ON CONFLICT(grp,member) DO UPDATE SET casts=casts+1 RETURNING casts""",
                      (*key, historical_catches+1)).fetchone()[0]


def progress(casts):
    remaining = CASTS_PER_LEVEL - casts % CASTS_PER_LEVEL
    if remaining == CASTS_PER_LEVEL and casts:
        return f"🎉 升到钓手 {level(casts)} 级！累计 {casts} 竿"
    return f"🎣 钓手 {level(casts)} 级　再抛 {remaining} 竿升级"


def profile(db, key, historical_catches, area):
    row = db.execute("SELECT casts FROM fishing_experience WHERE grp=? AND member=?", key).fetchone()
    casts = row[0] if row else historical_catches
    remaining = CASTS_PER_LEVEL - casts % CASTS_PER_LEVEL
    chance = slip_percent(casts, area == "新手池塘")
    return (f"🎣 钓手 {level(casts)} 级\n累计 {casts} 竿　再抛 {remaining} 竿升级\n"
            f"📍 {area}　下竿脱钩率 {chance}%\n"
            f"每 {CASTS_PER_LEVEL} 竿升一级，跑鱼也算一竿。")
