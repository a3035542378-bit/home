"""鱼饵仅用于本次抛竿；积分与鱼获一起随入站事务结算。"""
from typing import NamedTuple

from .fishing_waters import TROPHY_PERCENT


class Bait(NamedTuple):
    points: int
    rarity_factor: int
    weight_mode: float
    trophy_factor: float


BAITS = {
    "免费鱼饵": Bait(0, 1, 0.15, 1),
    "高级鱼饵": Bait(5, 2, 0.50, 1.5),
    "顶级鱼饵": Bait(15, 4, 0.85, 2),
}


def balance(db, key):
    return db.execute("SELECT COALESCE(SUM(points),0) FROM ledger WHERE grp=? AND member=?",key).fetchone()[0]


def menu(db, key, prefix):
    points=balance(db,key)
    lines = ["🪱 每竿可单独选饵", f"本群可用积分　{points}", ""]
    for name, bait in BAITS.items():
        lines.append(f"{name}　{bait.points} 积分 / 竿")
        if bait.points:
            lines.append(f"稀有和珍品权重 ×{bait.rarity_factor}，更容易钓到重鱼。")
            lines.append(f"史诗和传说咬钩率 ×{bait.trophy_factor:g}。")
        command = "抛竿 "+name if bait.points else "抛竿"
        if points>=bait.points:
            lines.extend([f"【{command}】"+(f"立即下竿，扣 {bait.points} 分" if bait.points else "免费下竿"),""])
        else:
            lines.extend([f"还差 {bait.points-points} 分。",""])
    lines.extend(["只用一竿，下次默认免费。", "抛出后消耗鱼饵，跑鱼也会扣分。"])
    from .fishing_cards import JournalReply
    return JournalReply("\n".join(lines),heading="饵料商店",title="选一份鱼饵",subtitle=f"本群余额  {points} 积分",
                        entries=[(name,f"{bait.points} 积分 / 竿  ·  "+
                                  (f"稀有和珍品权重 ×{bait.rarity_factor:g}，史诗和传说咬钩率 ×{bait.trophy_factor:g}" if bait.points else "常规咬钩率"))
                                 for name,bait in BAITS.items()],
                        notes=["发送即下竿并扣除相应积分。跑鱼也会消耗，本次之后恢复免费饵。"],
                        commands=[prefix+("抛竿 "+name if bait.points else "抛竿") for name,bait in BAITS.items() if points>=bait.points])


def rarity_weights(rod_weights, bait):
    common = sum(rod_weights[:3])
    return common, rod_weights[3]*bait.rarity_factor, rod_weights[4]*bait.rarity_factor

def distribution(school, rod_weights, bait, trophy_bonus):
    stocked = {fish[-1] for fish in school}
    regular = {tier: w for tier,w in zip(("普通","稀有","珍品"),rarity_weights(rod_weights,bait))
               if tier in stocked}
    trophies = {tier: pct * bait.trophy_factor * trophy_bonus
                for tier,pct in TROPHY_PERCENT.items() if tier in stocked}
    scale = (100 - sum(trophies.values())) / sum(regular.values())
    return {**{tier: w*scale for tier,w in regular.items()}, **trophies}


def choose_rarity(rng, school, rod_weights, bait, trophy_bonus):
    chances = distribution(school, rod_weights, bait, trophy_bonus)
    return rng.choices(list(chances), weights=list(chances.values()), k=1)[0]
