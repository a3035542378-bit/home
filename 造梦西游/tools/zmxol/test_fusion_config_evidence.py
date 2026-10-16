"""配置解析测试，真实配置关联核查与模拟器融合验收分开。"""

from pathlib import Path

import pytest

from fusion_config_evidence import build_evidence, pairs, parallel_arrays


@pytest.mark.parametrize("values", [[1], [1, -1], [True, 1], [1, 2.0], "1,2", None])
def test_malformed_pair_arrays_rejected(values):
    with pytest.raises(ValueError):
        pairs(values, "target")


def test_duplicate_candidates_and_zero_weights_preserved():
    assert pairs([9045, 5000, 9045, 5000, 9000, 0], "target") == [
        {"key": 9045, "value": 5000}, {"key": 9045, "value": 5000}, {"key": 9000, "value": 0}]


def test_blood_probabilities_are_parallel_arrays_not_interleaved_pairs():
    row = {"target": [9012, 9015], "probability_of_composition": [7500, 2500]}
    assert parallel_arrays(row, ("target", "probability_of_composition"), "blood") == [
        {"target": 9012, "probability_of_composition": 7500},
        {"target": 9015, "probability_of_composition": 2500}]
    with pytest.raises(ValueError):
        parallel_arrays({**row, "target": [9012]}, ("target", "probability_of_composition"), "blood")


@pytest.fixture(scope="module")
def actual_evidence():
    config = Path(__file__).resolve().parents[2] / "artifacts/zmxol-offline/15.7.2/decoded/database"
    if not config.is_dir():
        pytest.skip("Local original 15.7.2 decoded configuration unavailable")
    return build_evidence(config)


def test_actual_source_counts_and_hashes(actual_evidence):
    assert {name: source["rows"] for name, source in actual_evidence["sources"].items()} == {
        "pet": 180, "pet_skill": 309, "beast_mix_rule": 704, "true_spirit_main_config": 11,
        "true_spirit_auxiliary_config": 66, "true_spirit_blood_config": 52, "item": 6267, "rule": 341}
    assert all(len(source["sha256"]) == 64 for source in actual_evidence["sources"].values())


def test_9045_cannot_bootstrap_from_ordinary_pets(actual_evidence):
    priority = actual_evidence["priority_9045"]
    assert priority["candidate_count"] == 38
    assert priority["all_candidates_require_existing_9045"] is True
    assert priority["ordinary_pet_only_recipe_ids"] == []


def test_generic_outcome_codes_not_misreported_as_pet_quality_or_ids(actual_evidence):
    row = next(r for r in actual_evidence["main_config"] if r["id"] == 7522000)
    assert row["out_different_pairs"] == [
        {"key": 1, "value": 5000}, {"key": 4, "value": 3000}, {"key": 6, "value": 2000}]
    assert all(value is False for value in actual_evidence["interpretation_limits"].values())


def test_quality_and_material_references_keep_distinct_contracts(actual_evidence):
    assert {0, 1, 2, 3, 4, 5} == set(actual_evidence["quality_members"])
    assert all(r["id"] < 9000 for r in actual_evidence["quality_members"][0])
    row = next(r for r in actual_evidence["fusion_rules"] if r["id"] == 6820022)
    assert [(p["key"], p["value"]) for p in row["material_pairs"]] == [(503345, 2), (503346, 6)]
    assert [p["key"] for p in row["target_pairs"]] == [221, 9027, 9029]


def test_missing_configuration_fails_before_output(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_evidence(tmp_path)
