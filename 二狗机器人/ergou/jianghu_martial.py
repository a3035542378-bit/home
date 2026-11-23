"""进阶比试只在本次战报内使用气血、内力和控制状态。"""

from dataclasses import dataclass
from .jianghu_rules import Fighter


@dataclass
class Duelist:
    body: Fighter
    outer: str = ""
    inner: str = ""
    outer_level: int = 0
    inner_level: int = 0
    mana: int = 30


def resolve(left, right, rng):
    sides = (left, right)
    hp = [s.body.hp for s in sides]
    mana = [s.mana for s in sides]
    dazed = [False, False]
    immune = [False, False]
    speed = [max(1, s.body.agility) for s in sides]
    first = int(rng.randrange(sum(speed)) >= speed[0])
    lines = []
    for turn in range(1, 4):
        actions = []
        for i in (first, 1 - first):
            j = 1 - i
            a, b = sides[i], sides[j]
            if dazed[i]:
                dazed[i] = False
                immune[i] = True
                actions.append(f"{a.body.name}稳住身形")
                continue
            chance = max(0.30, min(0.95, (speed[i] + 30) / (speed[i] + speed[j] + 30)))
            if rng.random() >= chance:
                actions.append(f"{b.body.name}侧身躲过")
                immune[j] = False
                continue
            skill = (a.outer_level or a.inner_level) and mana[i] >= 6
            if skill:
                mana[i] -= 6
            power = a.body.attack
            if skill:
                power += a.outer_level * (6 if a.outer == "降龙掌" else 4)
                if a.inner == "太白经":
                    power += a.inner_level * 4
                if a.inner == "双手互搏" and a.outer == "降龙掌":
                    power += min(a.inner_level, a.outer_level) * 5
                if a.inner == "北冥秘术":
                    stolen = min(8, mana[j])
                    mana[j] -= stolen
                    mana[i] += stolen
            dmg = max(
                1,
                (power - b.body.defense - mana[j] // 10) // (2 if a.body.hungry else 1),
            )
            hp[j] = max(0, hp[j] - dmg)
            actions.append(
                f"{a.body.name}用{a.outer if skill and a.outer else '一记直拳'}打出{dmg}点伤害"
            )
            if hp[j] and b.inner == "九阳功" and b.inner_level:
                hp[i] = max(0, hp[i] - min(dmg // 4, 2 * b.inner_level))
                mana[j] = min(b.mana, mana[j] + 2)
                actions.append("九阳护体反震回气")
            if min(hp) == 0:
                break
            if (
                skill
                and not immune[j]
                and (a.outer == "太极剑" or a.inner == "北冥秘术")
                and rng.random() < 0.2
            ):
                dazed[j] = True
                actions.append("对手招式受制")
            else:
                immune[j] = False
        lines.append(f"第{turn}回合　" + "，".join(actions))
        if min(hp) == 0:
            break
    diff = hp[0] * right.body.hp - hp[1] * left.body.hp
    return (diff > 0) - (diff < 0), "\n".join(lines)
