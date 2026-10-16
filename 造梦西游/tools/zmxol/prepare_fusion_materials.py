"""生成独立融灵测试宠物存档；材料由DEBUG_ONLY原生入包准备。"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path


def prepare_materials(profile: dict, tables: dict) -> dict:
    rule = tables["beast_mix_rule"]["6820016"]
    if (rule["main_pet"], rule["auxiliary_pet"]) != (221, 229):
        raise ValueError("Original recipe changed")
    bag, pets = profile["bag"], profile["pet"]
    existing = pets["petinfo"]
    ids = [p["petid"] for p in existing]
    if not existing or len(set(ids)) != len(ids) or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError("Invalid existing pet identities")
    counter = pets["maxglobalpetid"]
    if type(counter) is not int or counter < max(ids) or counter > 0x7FFFFFFC:
        raise ValueError("Invalid pet identity counter")
    if len(existing) + 2 > pets["bagsize"]:
        raise ValueError("Insufficient pet capacity")
    owner = {p["master_unique_rid"] for p in existing}
    if len(owner) != 1:
        raise ValueError("Mixed pet ownership")
    materials = {503344: 100, 503345: 100, 503346: 100, 503347: 100}
    for item_id in materials:
        if tables["item"][str(item_id)]["id"] != item_id:
            raise ValueError("Invalid material configuration")
    if any(item["A2"] in materials for item in bag["item"]):
        raise ValueError("Test materials already present; avoid ambiguous stacking")
    if len(bag["item"]) + len(materials) > bag["bagsize"]:
        raise ValueError("Insufficient item capacity")
    result = copy.deepcopy(profile)
    fields = {"basehp": "hp_min", "basemp": "mp_min", "basestr": "str_min",
              "basedef": "def_min", "hpimprove": "hp_improve_min",
              "mpimprove": "mp_improve_min", "strimprove": "str_improve_min",
              "defimprove": "def_improve_min", "comprehension": "comprehension_max",
              "bonelevel": "bone_level_min", "spiritpower": "spirit_power_min"}
    for number, (pet_id, level) in enumerate(((221, 75), (229, 60)), 1):
        config = tables["pet"][str(pet_id)]
        if config["is_beast"] != 0 or config["super_evolution_id"] != pet_id:
            raise ValueError("Expected original super evolved ordinary pet")
        pet = {"dataid": pet_id, "level": level, "petid": counter + number,
               "petexp": 0, "lifetime": 100, "tamestate": 2, "iselite": 0,
               "ferity": 1, "mixlevel": 0, "isspecialchange": 0,
               "skill": list(config["born_skill"]), "triones": [1, 1, 0, 0, 0, 0, 0, 0, 0],
               "petequips": [], "master_unique_rid": next(iter(owner))}
        pet.update({field: config[source] for field, source in fields.items()})
        if any(str(skill) not in tables["pet_skill"] for skill in pet["skill"]):
            raise ValueError("Unknown original pet skill")
        result["pet"]["petinfo"].append(pet)
    result["pet"]["maxglobalpetid"] = counter + 3
    # 原序列化可保留A4但原UI仍读0；材料必须经原生入包，不能把快照数量当实际可用量。
    return result


async def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    tables = {name: json.loads((args.config / f"{name}.json").read_text())
              for name in ("pet", "pet_skill", "item", "beast_mix_rule")}
    result = prepare_materials(json.loads(args.profile.read_text()), tables)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False)
    args.output.chmod(0o600)


if __name__ == "__main__":
    asyncio.run(run())
