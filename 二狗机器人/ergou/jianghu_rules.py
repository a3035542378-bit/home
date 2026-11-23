"""江湖 P1 隔离原型数值。"""

from dataclasses import dataclass
import re


ATTRIBUTES = ("臂力", "身法", "根骨", "悟性")
FIELD = re.compile(r"(臂力|身法|根骨|悟性)\s*([0-9]{1,3})")
MEDITATION_HOURS = 12
POTENTIAL_CAP = 60


def allocation(text):
    fields = FIELD.findall(text)
    if FIELD.sub("", text).strip() or sorted(name for name, _ in fields) != sorted(ATTRIBUTES):
        raise ValueError("请把臂力、身法、根骨、悟性各写一次")
    values = {name: int(n) for name, n in fields}
    if max(values.values()) > 40:
        raise ValueError("每项最多 40 点，请调整后再发")
    total = sum(values.values())
    if total != 80:
        raise ValueError(
            f"你分了 {total} 点，{'多' if total > 80 else '少'}了 {abs(total - 80)} 点"
        )
    return [values[name] for name in ATTRIBUTES]


def title(s, a, c, i):
    if s - max(a, c, i) >= 20:
        return "莽撞武夫"
    if a - max(s, c, i) >= 20:
        return "飞檐走壁"
    if i >= 20 and min(s, a) <= 15:
        return "文弱书生"
    return "踏实练家子"


@dataclass(frozen=True)
class Fighter:
    name: str
    hp: int
    attack: int
    defense: int
    agility: int
    hungry: bool = False


def fighter(player, name):
    return Fighter(
        name,
        100 + 10 * player["strength"],
        10 + 5 * player["strength"] + 3 * player["level"] + (5 if player["route"] == "剑" else 0),
        2 * player["constitution"],
        player["agility"],
        player["hunger"] < 20,
    )


ENEMIES = {
    "假镖师": Fighter("假镖师", 80, 15, 5, 12),
    "野狗": Fighter("野狗", 50, 10, 2, 15),
    "蒙面人": Fighter("蒙面人", 150, 25, 10, 18),
}


def damage(attacker, defender):
    raw = attacker.attack - defender.defense
    return max(1, raw // (2 if attacker.hungry else 1))


def fight(left, right, rng, assisted=False):
    players = (left, right)
    remaining = [left.hp, right.hp]
    first = 0 if assisted or left.agility > right.agility else 1
    if not assisted and left.agility == right.agility:
        first = rng.randrange(2)
    lines = []
    for turn in range(1, 4):
        actions = []
        for actor in (first, 1 - first):
            other = 1 - actor
            hit = damage(players[actor], players[other])
            if assisted and turn == 1 and actor == 0:
                hit *= 2
            remaining[other] = max(0, remaining[other] - hit)
            actions.append(f"{players[actor].name}打出 {hit} 点伤害")
            if remaining[other] == 0:
                break
        lines.append(f"第{turn}回合　" + "，".join(actions))
        if min(remaining) == 0:
            break
    diff = remaining[0] * right.hp - remaining[1] * left.hp
    return (diff > 0) - (diff < 0), "\n".join(lines)


def meditation(cursor, now, constitution):
    elapsed = max(0, int((now - cursor) // 3600))
    hours = min(MEDITATION_HOURS, elapsed)
    potential = min(POTENTIAL_CAP, hours * (2 + constitution // 5))
    return hours, potential, cursor + elapsed * 3600
