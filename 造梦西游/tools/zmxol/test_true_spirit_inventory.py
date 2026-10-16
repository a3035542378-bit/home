"""映射检查只使用隔离 ZIP，不冒充原客户端功能测试。"""

import json
import zipfile

import pytest

from true_spirit_inventory import build_inventory, model_resources


@pytest.mark.parametrize("missing,legacy", [(False, False), (True, False), (False, True)])
def test_all_atlas_pages_required_and_member_bytes_fingerprinted(tmp_path, missing, legacy):
    path = tmp_path / "test.apk"
    prefix = f"assets/images/hd/skeleton/{'' if legacy else 'pet/'}9000"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(prefix + ".skel", b"native-model")
        archive.writestr(prefix + ".atlas", "9000.png\nsize: 1,1\n\n9000_2.png\nformat: RGBA8888\n")
        archive.writestr(prefix + ".png", b"page-one")
        if not missing:
            archive.writestr(prefix + "_2.png", b"page-two")
    with zipfile.ZipFile(path) as archive:
        result = model_resources(archive, 9000, legacy=legacy)
    assert result["basic_model_complete"] is not missing
    assert result["missing_pages"] == ([prefix + "_2.png"] if missing else [])
    assert all(len(member["sha256"]) == 64 for member in result["members"])
    assert result["animation_and_combat_verified"] is False


@pytest.mark.parametrize("page", ["../9000.png", "/9000.png", "foo\\9000.png"])
def test_unsafe_atlas_reference_rejected(tmp_path, page):
    path = tmp_path / "unsafe.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("assets/images/hd/skeleton/pet/9000.atlas", page + "\nsize: 1,1\n")
    with zipfile.ZipFile(path) as archive, pytest.raises(ValueError):
        model_resources(archive, 9000)


def test_mapping_uses_ids_not_weights_and_keeps_missing_skill_unknown(tmp_path):
    tables = {"pet": {"9000": {"id": 9000, "type": 17, "is_beast": 1, "name": "test",
                              "born_skill": [42], "ai_file": "ai_pet_9000"},
                       "210": {"is_beast": 0}}, "pet_skill": {}, "item": {"7": {"name": "material"}},
              "true_spirit_auxiliary_config": {},
              "beast_mix_rule": {"1": {"id": 1, "target": [9000, 10000], "other_materials": [7, 2]},
                                 "2": {"id": 2, "target": [210, 9000], "other_materials": []}}}
    for name, table in tables.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(table))
    apk = tmp_path / "test.apk"
    with zipfile.ZipFile(apk, "w"):
        pass
    result = build_inventory(tmp_path, {"current": apk})
    assert result["status"] == "STATIC_ONLY_NOT_RECOVERED"
    assert len(result["spirits"]) == 1
    row = result["spirits"][0]
    assert [rule["id"] for rule in row["fusion_rules"]] == [1]
    assert row["fusion_rules"][0]["materials"] == [{"id": 7, "count": 2, "name": "material"}]
    assert row["skills"][0]["config"] is None
    assert row["save"].startswith("UNKNOWN")
    assert row["resources"]["current"]["basic_model_complete"] is False
