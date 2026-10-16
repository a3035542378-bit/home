"""从已核对的 11.6.0 原包恢复已验证的角色、敌人、宠物、子弹和关卡背景资源。"""

import hashlib
import logging
import plistlib
import zipfile
from collections import Counter
from pathlib import Path
from xml.parsers.expat import ExpatError


LOGGER = logging.getLogger(__name__)
EXPECTED_APK_SHA256 = "ecff6494a962e066812434497282adb614c0163cb7be856c1f64be36861e3d6a"
SOURCE_PREFIX = "assets/images/hd/skeleton/"
ROLE_PAGES = {
    1: frozenset(("wk.png", *(f"wk{index}.png" for index in range(2, 106)))),
    5: frozenset(("ll.png", *(f"ll{index}.png" for index in range(2, 103)))),
}
ENEMY_PAGES = {
    enemy_id: frozenset((f"{enemy_id}.png",))
    for enemy_id in (300, 301, 302, 303, 304, 305, 322, 323, 324, 516)
}
# 蟠桃园天兵 322/323 的掉宠配置和捕捉教学使用火丸 210。
# 用户 Mock 邮件赠送最终火猿 252，模型保持旧包原资源。
PET_PAGES = {210: frozenset(("210.png",)), 252: frozenset(("252.png",))}
STATIC_BACKGROUND_PREFIX = "assets/images/hd/levels/level_static_bg/"
# 子关 700002/700004 引用 1，700003 引用 2。
STATIC_BACKGROUND_IDS = (1, 2)
BULLET_PREFIX = "assets/images/hd/roles/role_1/bullet/"
BULLET_IDS = (
    1001, 1011, 1021, 1031, *range(1101, 1106), 1111, *range(1113, 1120),
    *range(1131, 1134), *range(1141, 1144), 1201, 1211, 1212, 1221, 1222,
    *range(1231, 1236), *range(1241, 1244),
)


class LegacyResourceError(ValueError):
    """旧包指纹或游戏资源不符合已验证的输入。"""


def _atlas_pages(atlas: bytes, expected_pages: frozenset[str]) -> list[str]:
    try:
        lines = atlas.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise LegacyResourceError("Invalid legacy atlas encoding") from error
    # 每页从空行后的文件名开始；原敌人 atlas 省略 size，直接写 format。
    pages = [
        line for index, line in enumerate(lines[:-1])
        if line and (index == 0 or not lines[index - 1])
        and lines[index + 1].startswith(("size:", "format:"))
    ]
    if len(pages) != len(set(pages)):
        raise LegacyResourceError("Duplicate legacy atlas page")
    if any(page not in expected_pages for page in pages):
        raise LegacyResourceError("Unexpected or unsafe legacy atlas page")
    if set(pages) != expected_pages:
        raise LegacyResourceError("Incomplete legacy atlas pages")
    return pages


def _bullet_texture(payload: bytes, expected_name: str) -> str:
    try:
        data = plistlib.loads(payload)
    except (ValueError, TypeError, OverflowError, ExpatError) as error:
        raise LegacyResourceError("Invalid legacy bullet plist") from error
    metadata = data.get("metadata") if isinstance(data, dict) else None
    if not isinstance(metadata, dict):
        raise LegacyResourceError("Invalid legacy bullet plist metadata")
    texture = metadata.get("textureFileName")
    # 固定原文件名既限定已验证纹理，也拒绝绝对路径、目录跳转和别的动作。
    if texture != expected_name or metadata.get("realTextureFileName") != expected_name:
        raise LegacyResourceError("Unexpected or unsafe legacy bullet texture")
    return texture


def load_legacy_game_resources(source: Path) -> tuple[dict[str, bytes], dict]:
    """返回已验证原资源的新包 entry→原 bytes 和来源报告；不写文件。"""
    source = Path(source)
    try:
        # 在同一个文件句柄上校验和读取，避免重新打开路径时换入另一份文件。
        with source.open("rb") as stream:
            source_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            if source_sha256 != EXPECTED_APK_SHA256:
                raise LegacyResourceError("Unsupported legacy APK fingerprint")
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                counts = Counter(archive.namelist())
                entries = {}
                files = []
                roles = []
                enemies = []
                pets = []
                bullets = []
                groups = [("role", key, pages) for key, pages in ROLE_PAGES.items()]
                groups.extend(("enemy", key, pages) for key, pages in ENEMY_PAGES.items())
                groups.extend(("pet", key, pages) for key, pages in PET_PAGES.items())
                for kind, resource_id, expected_pages in groups:
                    id_key = f"{kind}_id"
                    atlas_name = f"{resource_id}.atlas"
                    if counts[SOURCE_PREFIX + atlas_name] != 1:
                        raise LegacyResourceError("Missing or duplicate legacy resource entry")
                    atlas = archive.read(SOURCE_PREFIX + atlas_name)
                    pages = _atlas_pages(atlas, expected_pages)
                    skeleton_extension = "skel" if kind == "role" else "json"
                    names = [f"{resource_id}.{skeleton_extension}", atlas_name, *pages]
                    if any(counts[SOURCE_PREFIX + name] != 1 for name in names):
                        raise LegacyResourceError("Missing or duplicate legacy resource entry")
                    target_prefix = f"assets/images/hd/skeleton/{kind}/"
                    if kind == "role":
                        target_prefix += f"{resource_id}/"
                    group_files = []
                    for name in names:
                        source_entry = SOURCE_PREFIX + name
                        target_entry = target_prefix + name
                        payload = atlas if name == atlas_name else archive.read(source_entry)
                        entries[target_entry] = payload
                        group_files.append({
                            id_key: resource_id,
                            "source_entry": source_entry,
                            "target_entry": target_entry,
                            "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                        })
                    files.extend(group_files)
                    summary = {
                        id_key: resource_id,
                        "target_prefix": target_prefix,
                        "texture_page_count": len(pages),
                        "file_count": len(names),
                        "total_bytes": sum(item["bytes"] for item in group_files),
                    }
                    {"role": roles, "enemy": enemies, "pet": pets}[kind].append(summary)
                for background_id in STATIC_BACKGROUND_IDS:
                    entry = f"{STATIC_BACKGROUND_PREFIX}level_static_{background_id}_bg.png"
                    if counts[entry] != 1:
                        raise LegacyResourceError("Missing or duplicate legacy static background")
                    payload = archive.read(entry)
                    entries[entry] = payload
                    files.append({
                        "static_background_id": background_id,
                        "source_entry": entry,
                        "target_entry": entry,
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    })
                for bullet_id in BULLET_IDS:
                    name = f"role_1_bul_{bullet_id}"
                    directory = f"{BULLET_PREFIX}{name}/"
                    plist_entry = directory + name + ".plist"
                    if counts[plist_entry] != 1:
                        raise LegacyResourceError("Missing or duplicate legacy bullet plist")
                    plist = archive.read(plist_entry)
                    texture_entry = directory + _bullet_texture(plist, name + ".pvr.ccz")
                    if counts[texture_entry] != 1:
                        raise LegacyResourceError("Missing or duplicate legacy bullet texture")
                    texture = archive.read(texture_entry)
                    for entry, payload in ((plist_entry, plist), (texture_entry, texture)):
                        entries[entry] = payload
                        files.append({
                            "bullet_id": bullet_id,
                            "source_entry": entry,
                            "target_entry": entry,
                            "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                        })
                    bullets.append({
                        "bullet_id": bullet_id,
                        "plist_entry": plist_entry,
                        "texture_entry": texture_entry,
                        "file_count": 2,
                        "total_bytes": len(plist) + len(texture),
                    })
    except LegacyResourceError:
        LOGGER.error("Legacy game resource validation failed")
        raise
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as error:
        LOGGER.error("Legacy game resource read failed: %s", type(error).__name__)
        raise LegacyResourceError("Unable to read verified legacy resources") from error
    return entries, {
        "source_apk": str(source),
        "source_version": "11.6.0",
        "source_sha256": source_sha256,
        "role_ids": list(ROLE_PAGES),
        "enemy_ids": list(ENEMY_PAGES),
        "pet_ids": list(PET_PAGES),
        "static_background_ids": list(STATIC_BACKGROUND_IDS),
        "bullet_ids": list(BULLET_IDS),
        "texture_page_count": sum(item["texture_page_count"] for item in roles + enemies + pets),
        "bullet_texture_count": len(bullets),
        "file_count": len(entries),
        "total_bytes": sum(item["bytes"] for item in files),
        "roles": roles,
        "enemies": enemies,
        "pets": pets,
        "bullets": bullets,
        "files": files,
    }
