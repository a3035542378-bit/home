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
    return "\n".join(lines)


def rarity_weights(rod_weights, bait):
    common = sum(rod_weights[:3])
    return common, rod_weights[3]*bait.rarity_factor, rod_weights[4]*bait.rarity_factor

def choose_rarity(rng, school, rod_weights, bait):
    tiers = ["普通", "稀有", "珍品"]
    weights = rarity_weights(rod_weights, bait)
    stocked = {fish[-1] for fish in school}
    extras = {tier: pct * bait.trophy_factor for tier, pct in TROPHY_PERCENT.items() if tier in stocked}
    if extras:
        # 给高阶鱼留出固定百分比，余下按原鱼竿、强化、鱼饵的相对权重分配。
        scale = (100 - sum(extras.values())) / sum(weights)
        weights = [w * scale for w in weights] + list(extras.values())
        tiers.extend(extras)
    return rng.choices(tiers, weights=weights, k=1)[0]
