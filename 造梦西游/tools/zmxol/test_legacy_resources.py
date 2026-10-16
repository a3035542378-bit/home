import hashlib
import plistlib
import zipfile
from pathlib import Path, PurePosixPath

import pytest

import legacy_resources
from legacy_resources import LegacyResourceError, load_legacy_game_resources


ROLE_PAGES = {
    1: ["wk.png", *(f"wk{index}.png" for index in range(2, 106))],
    5: ["ll.png", *(f"ll{index}.png" for index in range(2, 103))],
}
SOURCE_PREFIX = "assets/images/hd/skeleton/"
TARGET_PREFIX = "assets/images/hd/skeleton/role/"
ENEMY_TARGET_PREFIX = "assets/images/hd/skeleton/enemy/"
ENEMY_IDS = [300, 301, 302, 303, 304, 305, 322, 323, 324, 516]
ENEMY_NAMES = [f"{enemy_id}.{extension}" for enemy_id in ENEMY_IDS for extension in ("json", "atlas", "png")]
PET_TARGET_PREFIX = "assets/images/hd/skeleton/pet/"
PET_NAMES = [f"{pet_id}.{extension}" for pet_id in (210, 252) for extension in ("json", "atlas", "png")]
STATIC_BACKGROUND_PREFIX = "assets/images/hd/levels/level_static_bg/"
STATIC_BACKGROUND_ENTRIES = [f"{STATIC_BACKGROUND_PREFIX}level_static_{background_id}_bg.png" for background_id in (1, 2)]
BULLET_PREFIX = "assets/images/hd/roles/role_1/bullet/"
BULLET_IDS = [
    1001, 1011, 1021, 1031, *range(1101, 1106), 1111, *range(1113, 1120),
    *range(1131, 1134), *range(1141, 1144), 1201, 1211, 1212, 1221, 1222,
    *range(1231, 1236), *range(1241, 1244),
]
BULLET_ENTRIES = [
    f"{BULLET_PREFIX}role_1_bul_{bullet_id}/role_1_bul_{bullet_id}.{extension}"
    for bullet_id in BULLET_IDS for extension in ("plist", "pvr.ccz")
]


@pytest.fixture
def legacy_apk(tmp_path, monkeypatch):
    def build(*, role_id=1, pages=None, omitted=None, duplicate=None, atlas=None, enemy_atlas=None, pet_atlas=None, bullet_plist=None):
        payloads = {"2.skel": b"unrelated-role-must-not-be-exported", "306.json": b"unrelated-enemy-must-not-be-exported", "214.json": b"unverified-pet-must-not-be-exported"}
        for current_role, expected_pages in ROLE_PAGES.items():
            current_pages = pages if current_role == role_id and pages is not None else expected_pages
            current_atlas = atlas if current_role == role_id else None
            if current_atlas is None:
                current_atlas = "".join(
                    f"\n{page}\nsize: 512,64\nformat: RGBA8888\nregion_{index}\n  size: 8,8\n"
                    for index, page in enumerate(current_pages)
                ).encode()
            payloads.update({
                f"{current_role}.skel": b"original-skeleton-bytes\x00\xff" + str(current_role).encode(),
                f"{current_role}.atlas": current_atlas,
                **{name: b"original-png-bytes-" + name.encode() for name in expected_pages},
            })
        for enemy_id in ENEMY_IDS:
            current_atlas = f"\n{enemy_id}.png\nformat: RGBA8888\nfilter: Nearest,Nearest\nregion\n  rotate: false\n  size: 8,8\n".encode()
            if enemy_id == 300 and enemy_atlas is not None:
                current_atlas = enemy_atlas
            payloads.update({
                f"{enemy_id}.json": b'{"bones":[],"animations":{"rest":{}}}',
                f"{enemy_id}.atlas": current_atlas,
                f"{enemy_id}.png": b"original-enemy-png-" + str(enemy_id).encode(),
            })
        payloads.update({
            "210.json": b'{"bones":[],"animations":{"rest":{}}}',
            "210.atlas": pet_atlas if pet_atlas is not None else b"\n210.png\nsize: 64,64\nformat: RGBA8888\nregion\n  rotate: false\n  size: 8,8\n",
            "210.png": b"original-pet-png-210",
        })
        payloads.update({
            "252.json": b'{"bones":[],"animations":{"rest":{},"210000":{}}}',
            "252.atlas": b"\n252.png\nsize: 64,64\nformat: RGBA8888\nregion\n  rotate: false\n  size: 8,8\n",
            "252.png": b"original-pet-png-252",
        })
        for background_id in (1, 2, 3):
            payloads[f"{STATIC_BACKGROUND_PREFIX}level_static_{background_id}_bg.png"] = b"original-background-png-" + str(background_id).encode()
        for bullet_id in BULLET_IDS:
            name = f"role_1_bul_{bullet_id}"
            plist = plistlib.dumps({
                "frames": {name + "_0.png": {"rotated": False}},
                "metadata": {"textureFileName": name + ".pvr.ccz", "realTextureFileName": name + ".pvr.ccz"},
            })
            if bullet_id == 1001 and bullet_plist is not None:
                plist = bullet_plist
            payloads[f"{BULLET_PREFIX}{name}/{name}.plist"] = plist
            payloads[f"{BULLET_PREFIX}{name}/{name}.pvr.ccz"] = b"original-compressed-texture-" + name.encode()
        payloads[BULLET_PREFIX + "role_1_bul_1112/role_1_bul_1112.plist"] = b"unverified-bullet-must-not-be-exported"
        source = tmp_path / "legacy.apk"
        with zipfile.ZipFile(source, "w") as archive:
            for name, payload in payloads.items():
                if name != omitted:
                    archive.writestr(name if name.startswith("assets/") else SOURCE_PREFIX + name, payload)
            if duplicate:
                with pytest.warns(UserWarning, match="Duplicate name"):
                    archive.writestr(duplicate if duplicate.startswith("assets/") else SOURCE_PREFIX + duplicate, payloads[duplicate])
        monkeypatch.setattr(legacy_resources, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
        return source, payloads
    return build


def test_recovers_every_atlas_page_with_original_bytes_and_hashes(legacy_apk):
    source, payloads = legacy_apk()
    original = source.read_bytes()
    entries, report = load_legacy_game_resources(source)
    expected_names = {name for role_id, pages in ROLE_PAGES.items() for name in [f"{role_id}.skel", f"{role_id}.atlas", *pages]}
    expected_names.update(ENEMY_NAMES)
    expected_names.update(PET_NAMES)
    expected_names.update(BULLET_ENTRIES)
    expected_names.update(STATIC_BACKGROUND_ENTRIES)
    expected_targets = {f"{TARGET_PREFIX}{role_id}/{name}" for role_id, pages in ROLE_PAGES.items() for name in [f"{role_id}.skel", f"{role_id}.atlas", *pages]}
    expected_targets.update(ENEMY_TARGET_PREFIX + name for name in ENEMY_NAMES)
    expected_targets.update(PET_TARGET_PREFIX + name for name in PET_NAMES)
    expected_targets.update(BULLET_ENTRIES)
    expected_targets.update(STATIC_BACKGROUND_ENTRIES)
    assert set(entries) == expected_targets
    assert len(entries) == report["file_count"] == 321
    assert report["texture_page_count"] == 219
    assert report["bullet_texture_count"] == 36
    assert report["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert report["source_version"] == "11.6.0"
    assert report["role_ids"] == [1, 5]
    assert report["enemy_ids"] == ENEMY_IDS
    assert report["pet_ids"] == [210, 252]
    assert report["bullet_ids"] == BULLET_IDS
    assert report["static_background_ids"] == [1, 2]
    assert all("role_1_bul_1112" not in name for name in entries)
    assert ENEMY_TARGET_PREFIX + "306.json" not in entries
    assert PET_TARGET_PREFIX + "214.json" not in entries
    assert STATIC_BACKGROUND_PREFIX + "level_static_3_bg.png" not in entries
    assert [(item["role_id"], item["texture_page_count"], item["file_count"]) for item in report["roles"]] == [(1, 105, 107), (5, 102, 104)]
    assert [(item["enemy_id"], item["texture_page_count"], item["file_count"]) for item in report["enemies"]] == [(enemy_id, 1, 3) for enemy_id in ENEMY_IDS]
    assert [(item["pet_id"], item["texture_page_count"], item["file_count"]) for item in report["pets"]] == [(210, 1, 3), (252, 1, 3)]
    assert report["total_bytes"] == sum(len(payloads[name]) for name in expected_names)
    assert source.read_bytes() == original
    assert len(report["files"]) == 321
    for item in report["files"]:
        name = PurePosixPath(item["source_entry"]).name
        if "bullet_id" in item:
            assert item["source_entry"] == item["target_entry"]
            assert item["target_entry"] in BULLET_ENTRIES
            key = item["source_entry"]
        elif "static_background_id" in item:
            assert item["source_entry"] == item["target_entry"]
            assert item["target_entry"] in STATIC_BACKGROUND_ENTRIES
            key = item["source_entry"]
        elif "role_id" in item:
            assert item["source_entry"] == SOURCE_PREFIX + name
            assert item["target_entry"] == f"{TARGET_PREFIX}{item['role_id']}/{name}"
            key = name
        elif "pet_id" in item:
            assert item["source_entry"] == SOURCE_PREFIX + name
            assert item["pet_id"] in (210, 252)
            assert item["target_entry"] == PET_TARGET_PREFIX + name
            key = name
        else:
            assert item["source_entry"] == SOURCE_PREFIX + name
            assert item["enemy_id"] in ENEMY_IDS
            assert item["target_entry"] == ENEMY_TARGET_PREFIX + name
            key = name
        assert entries[item["target_entry"]] == payloads[key]
        assert item["bytes"] == len(payloads[key])
        assert item["sha256"] == hashlib.sha256(payloads[key]).hexdigest()
    assert len(report["bullets"]) == 36
    for item in report["bullets"]:
        metadata = plistlib.loads(entries[item["plist_entry"]])["metadata"]
        assert item["texture_entry"] == str(PurePosixPath(item["plist_entry"]).parent / metadata["textureFileName"])
        assert item["file_count"] == 2
        assert item["total_bytes"] == len(entries[item["plist_entry"]]) + len(entries[item["texture_entry"]])


@pytest.mark.parametrize("missing", ["1.skel", "1.atlas", "wk.png", "wk105.png", "5.skel", "5.atlas", "ll102.png", *ENEMY_NAMES, *PET_NAMES, *STATIC_BACKGROUND_ENTRIES])
def test_rejects_missing_required_resource(legacy_apk, missing):
    source, _ = legacy_apk(omitted=missing)
    with pytest.raises(LegacyResourceError, match="Missing or duplicate"):
        load_legacy_game_resources(source)


@pytest.mark.parametrize("duplicate", ["1.atlas", "wk105.png", "5.atlas", "ll102.png", "300.atlas", "303.png", *PET_NAMES, *STATIC_BACKGROUND_ENTRIES])
def test_rejects_ambiguous_duplicate_zip_entries(legacy_apk, duplicate):
    source, _ = legacy_apk(duplicate=duplicate)
    with pytest.raises(LegacyResourceError, match="Missing or duplicate"):
        load_legacy_game_resources(source)


@pytest.mark.parametrize("unsafe", ["../wk.png", "/wk.png", "C:wt.png", "sub/wk.png", "..\\wk.png", "./wk.png", "wk.png\x00other", "wk106.png"])
def test_rejects_unsafe_or_unverified_atlas_pages(legacy_apk, unsafe):
    source, _ = legacy_apk(pages=[unsafe, *ROLE_PAGES[1][1:]])
    with pytest.raises(LegacyResourceError, match="unsafe"):
        load_legacy_game_resources(source)


def test_rejects_duplicate_atlas_page_even_with_expected_page_count(legacy_apk):
    source, _ = legacy_apk(pages=[*ROLE_PAGES[1][:-1], ROLE_PAGES[1][0]])
    with pytest.raises(LegacyResourceError, match="Duplicate legacy atlas"):
        load_legacy_game_resources(source)


@pytest.mark.parametrize("role_id", [1, 5])
def test_rejects_incomplete_atlas_instead_of_silently_exporting_partial_resources(legacy_apk, role_id):
    source, _ = legacy_apk(role_id=role_id, pages=ROLE_PAGES[role_id][:-1])
    with pytest.raises(LegacyResourceError, match="Incomplete"):
        load_legacy_game_resources(source)


def test_rejects_invalid_atlas_encoding(legacy_apk):
    source, _ = legacy_apk(atlas=b"\xff")
    with pytest.raises(LegacyResourceError, match="encoding"):
        load_legacy_game_resources(source)


@pytest.mark.parametrize("atlas", [b"\n../300.png\nformat: RGBA8888\n", b"\n300.png\nformat: RGBA8888\n\nextra.png\nformat: RGBA8888\n"])
def test_rejects_path_traversal_or_extra_page_in_old_enemy_atlas_format(legacy_apk, atlas):
    source, _ = legacy_apk(enemy_atlas=atlas)
    with pytest.raises(LegacyResourceError, match="unsafe"):
        load_legacy_game_resources(source)


@pytest.mark.parametrize("atlas, message", [
    (b"\n../210.png\nsize: 64,64\n", "unsafe"),
    (b"\n210.png\nsize: 64,64\n\nextra.png\nsize: 64,64\n", "unsafe"),
    (b"\n210.png\nsize: 64,64\n\n210.png\nsize: 64,64\n", "Duplicate"),
    (b"", "Incomplete"),
])
def test_rejects_unsafe_duplicate_or_incomplete_pet_atlas(legacy_apk, atlas, message):
    source, _ = legacy_apk(pet_atlas=atlas)
    with pytest.raises(LegacyResourceError, match=message):
        load_legacy_game_resources(source)


@pytest.mark.parametrize("entry", [BULLET_ENTRIES[0], BULLET_ENTRIES[1], BULLET_ENTRIES[-1]])
@pytest.mark.parametrize("problem", ["missing", "duplicate"])
def test_rejects_missing_or_ambiguous_bullet_plist_and_texture(legacy_apk, entry, problem):
    source, _ = legacy_apk(**{"omitted" if problem == "missing" else "duplicate": entry})
    with pytest.raises(LegacyResourceError, match="Missing or duplicate legacy bullet"):
        load_legacy_game_resources(source)


@pytest.mark.parametrize("texture", ["../outside.pvr.ccz", "/outside.pvr.ccz", "C:outside.pvr.ccz", "sub/texture.pvr.ccz", "..\\outside.pvr.ccz", "./role_1_bul_1001.pvr.ccz", "role_1_bul_1001.pvr.ccz\x00extra", "role_1_bul_1112.pvr.ccz"])
def test_rejects_unsafe_or_unverified_plist_texture_dependency(legacy_apk, texture):
    plist = plistlib.dumps({"metadata": {"textureFileName": texture, "realTextureFileName": texture}}, fmt=plistlib.FMT_BINARY)
    source, _ = legacy_apk(bullet_plist=plist)
    with pytest.raises(LegacyResourceError, match="unsafe legacy bullet texture"):
        load_legacy_game_resources(source)


@pytest.mark.parametrize("metadata", [
    {"textureFileName": "role_1_bul_1001.pvr.ccz"},
    {"realTextureFileName": "role_1_bul_1001.pvr.ccz"},
    {"textureFileName": "role_1_bul_1001.pvr.ccz", "realTextureFileName": "other.pvr.ccz"},
    {"textureFileName": 1001, "realTextureFileName": "role_1_bul_1001.pvr.ccz"},
])
def test_rejects_missing_conflicting_or_wrongly_typed_texture_names(legacy_apk, metadata):
    source, _ = legacy_apk(bullet_plist=plistlib.dumps({"metadata": metadata}))
    with pytest.raises(LegacyResourceError, match="unsafe legacy bullet texture"):
        load_legacy_game_resources(source)


@pytest.mark.parametrize("plist", [b"not a plist", b"<?xml version='1.0'?><plist><dict>", plistlib.dumps("not a dictionary"), plistlib.dumps({}), plistlib.dumps({"metadata": []})])
def test_rejects_malformed_bullet_plist_as_resource_error(legacy_apk, plist):
    source, _ = legacy_apk(bullet_plist=plist)
    with pytest.raises(LegacyResourceError, match="Invalid legacy bullet plist"):
        load_legacy_game_resources(source)


def test_rejects_any_apk_without_verified_source_fingerprint(tmp_path):
    source = tmp_path / "other.apk"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(SOURCE_PREFIX + "1.atlas", b"unknown-atlas")
    with pytest.raises(LegacyResourceError, match="fingerprint"):
        load_legacy_game_resources(source)


def test_converts_unreadable_source_to_resource_error(tmp_path):
    with pytest.raises(LegacyResourceError, match="Unable to read"):
        load_legacy_game_resources(tmp_path / "missing.apk")


def test_converts_invalid_archive_to_resource_error(tmp_path, monkeypatch):
    source = tmp_path / "bad.apk"
    source.write_bytes(b"not a zip archive")
    monkeypatch.setattr(legacy_resources, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(LegacyResourceError, match="Unable to read"):
        load_legacy_game_resources(source)


def test_verified_1160_apk_recovers_all_321_unchanged_original_files():
    source = Path("/Users/baize/Downloads/造梦西游OL.apk.1")
    if not source.is_file():
        pytest.skip("Requires the verified local 11.6.0 source APK")
    entries, report = load_legacy_game_resources(source)
    assert report["source_sha256"] == "ecff6494a962e066812434497282adb614c0163cb7be856c1f64be36861e3d6a"
    assert report["texture_page_count"] == 219
    assert report["bullet_texture_count"] == 36
    assert report["bullet_ids"] == BULLET_IDS
    assert report["static_background_ids"] == [1, 2]
    assert len(entries) == report["file_count"] == 321
    assert report["total_bytes"] == 15493606
    assert report["pet_ids"] == [210, 252]
    assert report["pets"] == [{"pet_id": 210, "target_prefix": PET_TARGET_PREFIX, "texture_page_count": 1, "file_count": 3, "total_bytes": 14150}, {"pet_id": 252, "target_prefix": PET_TARGET_PREFIX, "texture_page_count": 1, "file_count": 3, "total_bytes": 670903}]
    assert sum(item["total_bytes"] for item in report["bullets"]) == 4106596
    assert hashlib.sha256(entries[TARGET_PREFIX + "1/1.skel"]).hexdigest() == "2ba46e7d39418508f6fb4858d06bd3c4e2fe6142bbea6a92726e5ccf05c77440"
    assert hashlib.sha256(entries[TARGET_PREFIX + "1/1.atlas"]).hexdigest() == "8395a4ded64cb149ad6edcaa4bd60580f3ed7c0892b8ae36e2a678fb54ebba5a"
    assert hashlib.sha256(entries[TARGET_PREFIX + "5/5.skel"]).hexdigest() == "e33a4a5f890a6cc250124edf04b2fdb7a26cb72a0eb02d14968807ef886ab56d"
    assert hashlib.sha256(entries[TARGET_PREFIX + "5/5.atlas"]).hexdigest() == "b62e78cd05390c01adf64d6d5769dd82b411bf5b5ee231067761aac90fa276e6"
    assert hashlib.sha256(entries[ENEMY_TARGET_PREFIX + "300.json"]).hexdigest() == "a7d84d7ba0ae59743032454834cad069a908a306a45b5f840063a68e8753cf2f"
    assert hashlib.sha256(entries[ENEMY_TARGET_PREFIX + "303.json"]).hexdigest() == "d56581221dc39356b33198338520a0a5a0c24c01fc14b264a8ba4c6941ecc701"
    assert [item["total_bytes"] for item in report["enemies"]] == [26926, 48451, 35709, 47923, 51188, 47571, 21701, 30637, 100072, 601696]
    expected_targets = {f"{TARGET_PREFIX}{role_id}/{name}" for role_id, pages in ROLE_PAGES.items() for name in [f"{role_id}.skel", f"{role_id}.atlas", *pages]}
    expected_targets.update(ENEMY_TARGET_PREFIX + name for name in ENEMY_NAMES)
    expected_targets.update(PET_TARGET_PREFIX + name for name in PET_NAMES)
    expected_targets.update(BULLET_ENTRIES)
    expected_targets.update(STATIC_BACKGROUND_ENTRIES)
    assert set(entries) == expected_targets
    with zipfile.ZipFile(source) as archive:
        for item in report["files"]:
            original = archive.read(item["source_entry"])
            assert entries[item["target_entry"]] == original
            assert item["sha256"] == hashlib.sha256(original).hexdigest()
            path = PurePosixPath(item["target_entry"])
            assert not path.is_absolute()
            assert not {".", ".."}.intersection(path.parts)
            assert item["target_entry"].startswith((TARGET_PREFIX, ENEMY_TARGET_PREFIX, PET_TARGET_PREFIX, BULLET_PREFIX, STATIC_BACKGROUND_PREFIX))
    for item in report["bullets"]:
        metadata = plistlib.loads(entries[item["plist_entry"]])["metadata"]
        assert metadata["textureFileName"] == metadata["realTextureFileName"]
        assert item["texture_entry"] == str(PurePosixPath(item["plist_entry"]).parent / metadata["textureFileName"])
        assert item["texture_entry"] in entries


@pytest.mark.parametrize("entry", ["252.json", "252.atlas", "252.png"])
@pytest.mark.parametrize("problem", ["missing", "duplicate"])
def test_final_pet_group_requires_every_unique_original_resource(legacy_apk, entry, problem):
    source, _ = legacy_apk(**{"omitted" if problem == "missing" else "duplicate": entry})
    with pytest.raises(LegacyResourceError, match="Missing or duplicate legacy resource entry"):
        load_legacy_game_resources(source)


def test_verified_final_pet_preserves_model_and_atlas_page_bytes():
    source = Path("/Users/baize/Downloads/造梦西游OL.apk.1")
    if not source.is_file():
        pytest.skip("Requires verified local legacy APK")
    entries, _ = load_legacy_game_resources(source)
    expected = {
        "json": "afaa95925122fa388fafa2d391633657e9015e31336cc40fe87d3ea5b213203b",
        "atlas": "dc677602bfb5019f258042db7f72b0b3bff670c8f5b0f8f643036fcd2bff481e",
        "png": "42f93207011772df92f93cd6940147bf2e16472f89af89983e60eb33872b8f8e",
    }
    for extension, sha256 in expected.items():
        assert hashlib.sha256(entries[f"{PET_TARGET_PREFIX}252.{extension}"]).hexdigest() == sha256
    assert legacy_resources._atlas_pages(entries[PET_TARGET_PREFIX + "252.atlas"], frozenset(("252.png",))) == ["252.png"]


@pytest.mark.parametrize("entry", ["516.json", "516.atlas", "516.png"])
@pytest.mark.parametrize("problem", ["missing", "duplicate"])
def test_fategod_original_enemy_model_requires_complete_unique_resources(legacy_apk, entry, problem):
    source, _ = legacy_apk(**{"omitted" if problem == "missing" else "duplicate": entry})
    with pytest.raises(LegacyResourceError, match="Missing or duplicate legacy resource entry"):
        load_legacy_game_resources(source)


def test_verified_fategod_516_restores_original_enemy_skeleton_bytes():
    source = Path("/Users/baize/Downloads/造梦西游OL.apk.1")
    if not source.is_file():
        pytest.skip("Requires verified local legacy APK")
    entries, _ = load_legacy_game_resources(source)
    expected = {
        "json": "a96866652c44a23cfca5554b3892ba6c6d6cc50dd74ee29521744ae7002fb2a5",
        "atlas": "83c099d500372723dd87f6c6e06dbeb6ea4fc8ed6a49536bb162ea25cb569102",
        "png": "1049ec1d2639effcf97b54341330d4414c3e107ee83e19ae04c625e71a3d7af8",
    }
    for extension, sha256 in expected.items():
        assert hashlib.sha256(entries[f"{ENEMY_TARGET_PREFIX}516.{extension}"]).hexdigest() == sha256
    assert legacy_resources._atlas_pages(entries[ENEMY_TARGET_PREFIX + "516.atlas"], frozenset(("516.png",))) == ["516.png"]
