"""解析本地融灵配置证据；不生成结果、不扣费、不修改游戏存档。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path


TABLES = ("pet", "pet_skill", "beast_mix_rule", "true_spirit_main_config",
          "true_spirit_auxiliary_config", "true_spirit_blood_config", "item", "rule")


def integer(value: object, context: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"Invalid integer: {context}")
    return value


def pairs(values: object, context: str) -> list[dict]:
    if not isinstance(values, list) or len(values) % 2:
        raise ValueError(f"Invalid pair array: {context}")
    return [{"key": integer(values[i], context), "value": integer(values[i + 1], context)}
            for i in range(0, len(values), 2)]


def parallel_arrays(row: dict, fields: tuple[str, ...], context: str) -> list[dict]:
    arrays = [row[field] for field in fields]
    if any(not isinstance(array, list) for array in arrays) or len({len(a) for a in arrays}) != 1:
        raise ValueError(f"Mismatched parallel arrays: {context}")
    return [{field: integer(value, f"{context}.{field}") for field, value in zip(fields, values)}
            for values in zip(*arrays)]


def build_evidence(config: Path) -> dict:
    tables, sources = {}, {}
    for name in TABLES:
        path = config / f"{name}.json"
        raw = path.read_bytes()
        table = json.loads(raw)
        if not isinstance(table, dict):
            raise ValueError(f"Expected keyed table: {name}")
        for key, row in table.items():
            if not isinstance(row, dict) or str(integer(row.get("id"), name)) != key:
                raise ValueError(f"Invalid table identity: {name}/{key}")
        tables[name] = table
        sources[name] = {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                         "rows": len(table)}

    pets = tables["pet"]
    auxiliary = {}
    quality_members = {}
    for row in tables["true_spirit_auxiliary_config"].values():
        pet_id = integer(row["pet_id"], "auxiliary.pet_id", minimum=1)
        quality = integer(row["quality"], "auxiliary.quality")
        if str(pet_id) not in pets or pets[str(pet_id)]["quality"] != quality or pet_id in auxiliary:
            raise ValueError("Inconsistent auxiliary pet identity or quality")
        for field in ("upgrade_id", "double_upgrade_id"):
            target = integer(row[field], field)
            if target and str(target) not in pets:
                raise ValueError("Missing auxiliary upgrade target")
        auxiliary[pet_id] = row
        quality_members.setdefault(quality, []).append({"id": pet_id, "name": pets[str(pet_id)]["name"],
                                                        "source": f"true_spirit_auxiliary_config/{row['id']}"})

    def material_pairs(row: dict, context: str) -> list[dict]:
        result = pairs(row["other_materials"], context)
        for pair in result:
            item = tables["item"].get(str(pair["key"]))
            if item is None or pair["value"] <= 0:
                raise ValueError(f"Missing material or invalid count: {context}")
            pair.update(name=item["name"], introduction=item["introduction"])
        return result

    rules = []
    for row in tables["beast_mix_rule"].values():
        context = f"beast_mix_rule/{row['id']}"
        main, aux = row["main_pet"], row["auxiliary_pet"]
        if main not in auxiliary or aux not in auxiliary:
            raise ValueError(f"Missing fusion input: {context}")
        targets = pairs(row["target"], context + ".target")
        for target in targets:
            if str(target["key"]) not in pets:
                raise ValueError(f"Missing target pet: {context}")
            target.update(name=pets[str(target["key"])]["name"],
                          quality=pets[str(target["key"])]["quality"])
        rules.append({"id": row["id"], "main_pet": main, "auxiliary_pet": aux,
                      "main_quality": auxiliary[main]["quality"],
                      "auxiliary_quality": auxiliary[aux]["quality"],
                      "target_pairs": targets, "configured_weight_sum": sum(t["value"] for t in targets),
                      "material_pairs": material_pairs(row, context),
                      "talent_pairs": pairs(row["talent"], context + ".talent"),
                      "talent_number_pairs": pairs(row["talent_number"], context + ".talent_number"),
                      "blood_parallel": parallel_arrays(row, ("blood_source", "blood_pr", "blood_id"), context),
                      "raw": row})

    main_rows = []
    for row in tables["true_spirit_main_config"].values():
        context = f"true_spirit_main_config/{row['id']}"
        entry = {"id": row["id"], "raw": row, "material_pairs": material_pairs(row, context)}
        for field in ("out_same", "out_different", "talent_num_same", "talent_num_different", "random_talent_weight"):
            entry[field + "_pairs"] = pairs(row[field], context + "." + field)
        entry["blood_parallel"] = parallel_arrays(row, ("blood_source", "blood_pr", "blood_id"), context)
        main_rows.append(entry)

    blood_rows = [{"id": row["id"], "raw": row,
                   "target_probability_parallel": parallel_arrays(row, ("target", "probability_of_composition"),
                                                                     f"true_spirit_blood_config/{row['id']}")}
                  for row in tables["true_spirit_blood_config"].values()]
    candidates = [r for r in rules if any(t["key"] == 9045 for t in r["target_pairs"])]
    return {"status": "STATIC_EVIDENCE_ONLY", "sources": sources,
            "interpretation_limits": {"pair_values_are_final_probabilities": False,
                                      "material_pairs_are_verified_costs": False,
                                      "main_out_keys_are_pet_ids": False,
                                      "blood_quality_equals_main_quality": False,
                                      "authoritative_inheritance_algorithm_restored": False},
            "quality_members": quality_members,
            "main_config": sorted(main_rows, key=lambda r: r["id"]),
            "fusion_rules": sorted(rules, key=lambda r: r["id"]),
            "blood_config": sorted(blood_rows, key=lambda r: r["id"]),
            "priority_9045": {"candidate_count": len(candidates),
                              "ordinary_pet_only_recipe_ids": [r["id"] for r in candidates
                                  if not pets[str(r["main_pet"])]["is_beast"]
                                  and not pets[str(r["auxiliary_pet"])]["is_beast"]],
                              "all_candidates_require_existing_9045": bool(candidates) and all(
                                  9045 in (r["main_pet"], r["auxiliary_pet"]) for r in candidates),
                              "recipe_ids": [r["id"] for r in candidates]}}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = await asyncio.to_thread(build_evidence, args.config)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    asyncio.run(main())
