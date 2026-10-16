import copy
import json
from pathlib import Path

import pytest

from prepare_fusion_materials import prepare_materials


@pytest.fixture
def inputs():
    config = Path(__file__).resolve().parents[2] / "artifacts/zmxol-offline/15.7.2/decoded/database"
    if not config.is_dir():
        pytest.skip("Actual decoded 15.7.2 configuration is required")
    tables = {name: json.loads((config / f"{name}.json").read_text())
              for name in ("pet", "pet_skill", "item", "beast_mix_rule")}
    profile = {"pet": {"bagsize": 8, "maxglobalpetid": 10,
                       "petinfo": [{"petid": 9, "master_unique_rid": 100010001, "unknown": [42]}]},
               "bag": {"bagsize": 20, "item": [{"A2": 502001, "A4": 1}]},
               "roledata": {"level": 90}, "receipt": {"phase": "committed"}}
    return profile, tables


def test_preparation_preserves_original_assets_and_adds_recipe_materials(inputs):
    profile, tables = inputs
    before = copy.deepcopy(profile)
    result = prepare_materials(profile, tables)
    assert profile == before
    assert result["pet"]["petinfo"][:1] == profile["pet"]["petinfo"]
    assert [(p["petid"], p["dataid"], p["level"]) for p in result["pet"]["petinfo"][1:]] == [(11, 221, 75), (12, 229, 60)]
    assert result["bag"] == profile["bag"]
    assert result["receipt"] == profile["receipt"]
    assert "true_spirit_bag" not in result


@pytest.mark.parametrize("case", ["capacity", "counter", "duplicate", "owner", "material", "skill"])
def test_reject_unsafe_preparation(inputs, case):
    profile, tables = inputs
    if case == "capacity":
        profile["pet"]["bagsize"] = 1
    elif case == "counter":
        profile["pet"]["maxglobalpetid"] = 8
    elif case == "duplicate":
        profile["pet"]["petinfo"] *= 2
    elif case == "owner":
        profile["pet"]["petinfo"].append({"petid": 10, "master_unique_rid": 2})
    elif case == "material":
        profile["bag"]["item"].append({"A2": 503345, "A4": 1})
    else:
        tables["pet"]["221"]["born_skill"] = [-1]
    with pytest.raises(ValueError):
        prepare_materials(profile, tables)
