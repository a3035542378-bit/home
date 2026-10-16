"""只读真灵证据映射；资源存在不代表玩法、动画或存档契约已恢复。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

from legacy_resources import _atlas_pages


def fingerprint(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def model_resources(archive: zipfile.ZipFile, resource_id: int, *, legacy: bool = False) -> dict:
    prefix = f"assets/images/hd/skeleton/{'' if legacy else 'pet/'}{resource_id}"
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("Duplicate APK members")
    models = [prefix + suffix for suffix in (".json", ".skel") if prefix + suffix in names]
    atlas = prefix + ".atlas"
    result = {"models": models, "atlas": atlas if atlas in names else None,
              "pages": [], "missing_pages": [], "basic_model_complete": False,
              "animation_and_combat_verified": False}
    if atlas in names:
        parent = str(PurePosixPath(atlas).parent)
        pages = frozenset(PurePosixPath(name).name for name in names
                          if str(PurePosixPath(name).parent) == parent and name.endswith(".png"))
        raw = archive.read(atlas)
        lines = raw.decode("utf-8").splitlines()
        referenced = [line for i, line in enumerate(lines[:-1])
                      if line and (i == 0 or not lines[i - 1])
                      and lines[i + 1].startswith(("size:", "format:"))]
        # 复用原 atlas 校验，但仅核本 atlas 的页，目录中其他宠物页不属于该模型。
        if not referenced or any(PurePosixPath(page).name != page or "\\" in page or ":" in page
                                 or page in (".", "..") for page in referenced):
            raise ValueError("Unsafe or empty atlas pages")
        _atlas_pages(raw, frozenset(referenced))
        result["pages"] = [parent + "/" + page for page in referenced]
        result["missing_pages"] = [parent + "/" + page for page in referenced if page not in pages]
    checked = models + ([atlas] if result["atlas"] else []) + [
        page for page in result["pages"] if page not in result["missing_pages"]]
    result["members"] = [{"path": name, "sha256": hashlib.sha256(archive.read(name)).hexdigest(),
                           "bytes": archive.getinfo(name).file_size} for name in checked]
    result["basic_model_complete"] = bool(models and result["pages"] and not result["missing_pages"])
    return result


def build_inventory(config: Path, apks: dict[str, Path]) -> dict:
    table_names = ("pet", "pet_skill", "beast_mix_rule", "true_spirit_auxiliary_config", "item")
    tables = {name: json.loads((config / f"{name}.json").read_text()) for name in table_names}
    for table in tables.values():
        if not isinstance(table, dict):
            raise ValueError("Expected keyed configuration table")
    rows = []
    for key, pet in tables["pet"].items():
        if pet.get("is_beast") != 1:
            continue
        if pet.get("type") != 17 or str(pet["id"]) != key:
            raise ValueError("Invalid true spirit configuration identity")
        spirit_id = pet["id"]
        skills = [{"id": skill_id, "config": tables["pet_skill"].get(str(skill_id)),
                   "source": f"pet_skill.json/{skill_id}"} for skill_id in pet["born_skill"]]
        rules = []
        for rule in tables["beast_mix_rule"].values():
            target = rule["target"]
            material = rule["other_materials"]
            if len(target) % 2 or len(material) % 2:
                raise ValueError("Invalid fusion ID/value pairs")
            if spirit_id not in target[::2]:
                continue
            rules.append({"id": rule["id"], "config": rule, "materials": [
                {"id": material[i], "count": material[i + 1],
                 "name": tables["item"].get(str(material[i]), {}).get("name")}
                for i in range(0, len(material), 2)]})
        rows.append({"id": spirit_id, "name": pet["name"], "config": pet,
                     "config_source": f"pet.json/{key}", "skills": skills,
                     "fusion_rules": rules, "auxiliary_rows": [row for row in
                         tables["true_spirit_auxiliary_config"].values() if row["pet_id"] == spirit_id],
                     "resources": {}, "ai_config_exists": (config / (pet["ai_file"] + ".json")).is_file(),
                     "protocol": "UNKNOWN: per-candidate response and acquisition transaction",
                     "save": "UNKNOWN: complete instance, ID allocation, serializer, dirty flags",
                     "icon_animation_effect_audio": "UNKNOWN: native dynamic references not closed"})
    sources = {}
    for label, path in apks.items():
        sources[label] = {"path": str(path.resolve()), "sha256": fingerprint(path), "bytes": path.stat().st_size}
        with zipfile.ZipFile(path) as archive:
            for row in rows:
                resource_id = row["config"].get("resource_id") or row["id"]
                row["resources"][label] = model_resources(archive, resource_id, legacy=label == "old")
    return {"status": "STATIC_ONLY_NOT_RECOVERED", "apks": sources,
            "config_sha256": {name: fingerprint(config / f"{name}.json") for name in table_names},
            "spirits": sorted(rows, key=lambda row: row["id"])}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("old_apk", type=Path)
    parser.add_argument("original_apk", type=Path)
    parser.add_argument("current_apk", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = await asyncio.to_thread(build_inventory, args.config,
                                    {"old": args.old_apk, "original": args.original_apk, "current": args.current_apk})
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    asyncio.run(main())
