"""鱼饵仅用于本次抛竿；积分与鱼获一起随入站事务结算。"""
from typing import NamedTuple


class Bait(NamedTuple):
    points: int
    rarity_factor: int
    weight_mode: float


BAITS = {
    "免费鱼饵": Bait(0, 1, 0.15),
    "高级鱼饵": Bait(5, 2, 0.50),
    "顶级鱼饵": Bait(15, 4, 0.85),
}


def balance(db, key):
    return db.execute("SELECT COALESCE(SUM(points),0) FROM ledger WHERE grp=? AND member=?",key).fetchone()[0]


def menu(db, key, prefix):
    lines = ["🪱 鱼饵", f"本群可用积分　{balance(db,key)}", ""]
    for name, bait in BAITS.items():
        lines.append(f"{name}　{bait.points} 积分 / 竿")
        if bait.points:
            lines.append(f"稀有和珍品权重 ×{bait.rarity_factor}，更容易钓到重鱼。")
        command = "抛竿 "+name if bait.points else "抛竿"
        lines.extend([prefix+command, ""])
    lines.extend(["只用一竿，下次默认免费。", "抛出后消耗鱼饵，跑鱼也会扣分。"])
    return "\n".join(lines)


def rarity_weights(rod_weights, bait):
    common = sum(rod_weights[:3])
    return common, rod_weights[3]*bait.rarity_factor, rod_weights[4]*bait.rarity_factor
