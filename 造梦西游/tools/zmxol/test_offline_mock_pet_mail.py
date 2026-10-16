"""Mock 最终形态宠物邮件事务；native 替身验证时序，不代替实机资源及战斗验收。"""

import copy
import json
from pathlib import Path

import pytest

from test_offline_bridge import run_production_js
from test_offline_mock_bagua import PILL_RECEIPT
from test_offline_mock_mail import BAGUA_RECEIPT, CLAIM, LIST, NODE_MAIL_CHECK, PET_ID, PET_ITEM, body


BAG = {"spiritcount": 17145, "maxglobalitemid": 4407, "item": [{"A2": 504100, "A4": 1}]}
OLD_PET = {"petid": 4399, "dataid": 210, "level": 1, "tamestate": 1, "petexp": 32,
           "master_unique_rid": 100010001, "triones": [1, 1, 0, 0, 0, 0, 0, 0, 0], "skill": [210000]}
BEFORE = {"petinfo": [OLD_PET], "bagsize": 8, "maxglobalpetid": 4400}
AFTER = {"petinfo": [OLD_PET, {**PET_ITEM, "petid": 4400}], "bagsize": 8, "maxglobalpetid": 4401}


def pet_mail_harness():
    script = NODE_MAIL_CHECK

    def replace(old, new):
        nonlocal script
        assert script.count(old) == 1
        script = script.replace(old, new)

    replace("const mailSteps = [], mailIds = new Map(), baguaObjects = new Map();",
            "const mailSteps = [], mailIds = new Map(), baguaObjects = new Map();\n"
            "let nativePetFactories = 0, petSnapshotCalls = 0; const petObjects = new Map(), petFactoryInputs = [];")
    replace("function NativeFunction(address) {", "function NativeFunction(address, resultType, argumentTypes) {")
    replace("if (input.baguaWire && address.address === 0x3c6b750) {", r"""
    if (input.petMailWire && address.address === 0x3c6b750) {
      nativePetFactories++;
      const source = JSON.parse(JSON.stringify(values.get(args[0].address).value)); petFactoryInputs.push(source);
      if (input.factoryNull) return pointer(0);
      const object = pointer(0x780000 + nativePetFactories * 0x100), pet = object.add(0x50);
      const snapshot = nativePetFactories === 2 && input.petRoundtripChange ? {...source, ...input.petRoundtripChange} : {...source, ...(input.nativePetChange ?? {})};
      petObjects.set(pet.address, snapshot); memory.set(object.address, pointer(input.badPetItemType ? 0x65d2168 : 0x65d2160));
      memory.set(pet.address, pointer(0x765000)); memory.set(0x766a58, pointer(input.badPetSerializer ? 0x3a0c61c : 0x3a0c618));
      memory.set(0x766800, pointer(0x399726c)); return object;
    }
    if (input.petMailWire && address.address === 0x4ffd82c) return input.castNull ? pointer(0) : args[0];
    if (input.petMailWire && address.address === 0x3c93dd4) return input.unwrapNull ? pointer(0) : args[0].add(0x50);
    if (input.petMailWire && address.address === 0x399726c) return input.nativePetStage ?? 5;
    if (input.petMailWire && address.address === 0x2c1348c) return pointer(0x760000);
    if (input.petMailWire && address.address === 0x2fecd6c) {
      if (resultType !== 'pointer' || argumentTypes.length !== 0) throw new Error('Wrong SaveMgr ABI');
      return pointer(input.nullSaveManager ? 0 : 0x790000);
    }
    if (input.petMailWire && [0x2fe19a4, 0x2fe1a98].includes(address.address)) {
      if (resultType !== 'int' || argumentTypes.join() !== 'pointer' || args[0].address !== 0x790000) throw new Error('Wrong owner getter ABI');
      return address.address === 0x2fe19a4 ? (input.ownerRoleId ?? 10001) : (input.ownerServiceId ?? 1);
    }
    if (input.petMailWire && address.address === 0xdeadbe98) throw new Error('Role pointer must not be used as owner ID');
    if (input.baguaWire && address.address === 0x3c6b750) {""")
    replace("memory.set(0x8000, pointer(0x9000)); memory.set(0x9058, pointer(0xdeadbeef));",
            "memory.set(0x8000, pointer(0x9000)); memory.set(0x9058, pointer(0xdeadbeef)); memory.set(0x9098, pointer(0xdeadbe98));")
    replace("if (args[2].address === 0x3c85cac) {", r"""
      if (args[2].address === 0x3a0c618) { values.set(args[1].address, {value: parseValue(JSON.stringify(petObjects.get(args[0].address)))}); return; }
      if (args[2].address === 0x2c1ab40) {
        petSnapshotCalls++;
        if (petSnapshotCalls === input.petSnapshotFailAt) throw new Error('Test pet snapshot failure');
        let snapshot = nativeMailCalls === 0 ? input.nativePetBefore : input.nativePetAfter;
        if (petSnapshotCalls === 2 && input.previewChangesPet) snapshot = input.nativePetAfter;
        values.set(args[1].address, {value: parseValue(JSON.stringify(snapshot))}); return;
      }
      if (args[2].address === 0x3c85cac) {""")
    replace("let store = input.nativeStore", "memory.set(0x67776e0, pointer(0x65d2130));\nlet store = input.nativeStore")
    replace("process.stdout.write(JSON.stringify({packets, nativeMailCalls,", "process.stdout.write(JSON.stringify({nativePetFactories, petSnapshotCalls, petFactoryInputs, packets, nativeMailCalls,")
    return script


NODE_PET_MAIL_CHECK = pet_mail_harness()


def run(run_production_js, **changes):
    baseline = {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 90}}, "point": 0,
                "bag": BAG, "pet": BEFORE, "_offline_mock_mail": PILL_RECEIPT, "_offline_mock_bagua": BAGUA_RECEIPT}
    values = {"nativeStore": True, "mailWire": True, "petMailWire": True, "nativePoint": "0",
              "baseline": baseline, "listRequest": LIST, "claimRequest": {**CLAIM, "id": PET_ID},
              "nativeBagBefore": BAG, "nativeBagAfter": BAG, "nativePetBefore": BEFORE, "nativePetAfter": AFTER}
    return run_production_js(NODE_PET_MAIL_CHECK, copy.deepcopy({**values, **changes}))


def test_template_matches_final_fire_monkey_config_and_native_mail_shape():
    database = Path(__file__).resolve().parents[2] / "artifacts/zmxol-offline/15.7.2/decoded/database/pet.json"
    config = json.loads(database.read_text())["252"]
    assert config["stage"] == 5 and config["evolution_id"] == 0 and config["base_id"] == 210
    assert PET_ITEM["skill"] == config["born_skill"] and "A2" not in PET_ITEM
    for field, source in {"basehp": "hp_min", "basemp": "mp_min", "basestr": "str_min", "basedef": "def_min",
                          "hpimprove": "hp_improve_min", "mpimprove": "mp_improve_min", "strimprove": "str_improve_min",
                          "defimprove": "def_improve_min", "comprehension": "comprehension_min",
                          "spiritpower": "spirit_power_min", "bonelevel": "bone_level_min"}.items():
        assert PET_ITEM[field] == config[source]


def test_pet_mail_preview_uses_native_roundtrip_without_adding_or_editing_pets(run_production_js):
    result = run(run_production_js, listOnly=True, reloadMail=True)
    mail = json.loads(body(result, 0))["mails"][0]
    assert mail["id"] == str(PET_ID) and "[Mock]" in mail["title"] and "圣佛邪君" in mail["title"]
    assert mail["reward"] == [PET_ITEM] and result["nativePetFactories"] == 2
    assert result["petFactoryInputs"] == [PET_ITEM, PET_ITEM]
    assert result["stored"]["pet"] == BEFORE and result["stored"]["bag"] == BAG
    assert result["nativeMailCalls"] == 0 and result["diskWrites"] == 1 and result["healthy"]
    assert "_offline_mock_pet" not in result["role"]["savedata"]
    assert result["afterReload"] == json.loads(body(result, 0))


def test_original_mail_grant_appends_one_pet_and_commits_before_ack_and_go_on(run_production_js):
    result = run(run_production_js, repeatMail=True, repeatMailRequest=True, reloadMail=True)
    assert result["healthy"] and result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 1
    assert result["stored"] == result["persisted"] and result["stored"]["pet"] == AFTER
    assert result["stored"]["bag"] == BAG and result["stored"]["pet"]["petinfo"][0] == OLD_PET
    assert result["stored"]["_offline_mock_pet"]["phase"] == "committed"
    assert result["stored"]["_offline_mock_mail"] == PILL_RECEIPT and result["stored"]["_offline_mock_bagua"] == BAGUA_RECEIPT
    assert result["mailSteps"] == [{"kind": "reward", "phase": "claiming"}, {"kind": "ack", "phase": "committed"}, {"kind": "clear", "phase": "committed"}]
    assert result["notifications"] == [{"name": "GO_ON", "phase": "committed"}] * 2
    assert result["afterReload"]["mails"] == [] and json.loads(body(result, 2))["code"] == -1
    cold = run(run_production_js, baseline=result["persisted"], nativePetBefore=AFTER)
    assert cold["nativePetFactories"] == cold["nativeMailCalls"] == 0 and cold["stored"] == result["persisted"]


@pytest.mark.parametrize("condition", [
    {"factoryNull": True}, {"castNull": True}, {"unwrapNull": True}, {"badPetItemType": True},
    {"badPetSerializer": True}, {"nativePetStage": 4}, {"nativePetChange": {"dataid": 213}},
    {"nativePetChange": {"level": 59}}, {"petRoundtripChange": {"hpimprove": 601}},
    {"previewChangesPet": True}, {"failWriteAt": 1},
])
def test_invalid_or_mutating_pet_preview_is_never_offered(run_production_js, condition):
    result = run(run_production_js, listOnly=True, **condition)
    assert body(result, 0) is None and result["nativeMailCalls"] == 0 and not result["healthy"]
    assert result["stored"]["pet"] == BEFORE and "_offline_mock_pet" not in result["stored"]


@pytest.mark.parametrize("after", [
    BEFORE,
    {**AFTER, "petinfo": [OLD_PET, {**PET_ITEM, "petid": 4399}]},
    {**AFTER, "petinfo": [OLD_PET, {**PET_ITEM, "petid": 4398}]},
    {**AFTER, "petinfo": [{**OLD_PET, "level": 60}, {**PET_ITEM, "petid": 4400}]},
    {**AFTER, "petinfo": [OLD_PET, {**PET_ITEM, "petid": 4400, "dataid": 213}]},
    {**AFTER, "petinfo": [OLD_PET, {**PET_ITEM, "petid": 4400, "tamestate": 1}]},
    {**AFTER, "petinfo": [OLD_PET, {**PET_ITEM, "petid": 4400, "skill": [210000]}]},
    {**AFTER, "petinfo": [OLD_PET, {**PET_ITEM, "petid": 4400}, {**PET_ITEM, "petid": 4401}]},
    {**AFTER, "bagsize": 9}, {**AFTER, "maxglobalpetid": 4400},
])
def test_wrong_native_pet_delta_never_commits_or_acknowledges(run_production_js, after):
    result = run(run_production_js, nativePetAfter=after, repeatMail=True)
    assert result["nativeMailCalls"] == 1 and not result["healthy"]
    assert result["nativeMailAcks"] == result["nativeMailClears"] == 0 and result["notifications"] == []
    assert result["stored"]["pet"] == BEFORE and result["stored"]["_offline_mock_pet"]["phase"] == "claiming"


@pytest.mark.parametrize("condition", [
    {"nativeBagAfter": {**BAG, "spiritcount": 17144}}, {"nativePointAfter": "1"},
    {"petSnapshotFailAt": 5}, {"failWriteAt": 3},
])
def test_pet_and_bag_commit_is_atomic_on_snapshot_and_storage_failure(run_production_js, condition):
    result = run(run_production_js, **condition)
    assert result["nativeMailCalls"] == 1 and not result["healthy"]
    assert result["nativeMailAcks"] == result["nativeMailClears"] == 0 and result["notifications"] == []
    assert result["stored"]["pet"] == BEFORE and result["stored"]["bag"] == BAG


def test_full_pet_bag_is_rejected_before_native_award(run_production_js):
    full = {**BEFORE, "bagsize": 1}
    result = run(run_production_js, nativePetBefore=full)
    assert json.loads(body(result, 1))["code"] == -1 and result["nativeMailCalls"] == 0
    assert result["notifications"] == [{"name": "GO_ON", "phase": "offered"}]
    assert result["stored"]["_offline_mock_pet"]["phase"] == "offered"


@pytest.mark.parametrize("interruption", [{"noDeliver": True}, {"failWriteAt": 3}])
def test_interrupted_pet_mail_is_retried_from_durable_pre_grant_state(run_production_js, interruption):
    first = run(run_production_js, **interruption)
    assert first["persisted"]["_offline_mock_pet"]["phase"] == "claiming"
    resumed = run(run_production_js, baseline=first["persisted"])
    assert resumed["nativePetFactories"] == 0 and resumed["nativeMailCalls"] == 1 and resumed["healthy"]
    assert resumed["stored"]["pet"] == AFTER and resumed["stored"]["_offline_mock_pet"]["phase"] == "committed"


def test_directory_sync_failure_after_rename_does_not_duplicate_pet_on_restart(run_production_js):
    first = run(run_production_js, failDirectorySyncAt=3)
    assert not first["healthy"] and first["nativeMailAcks"] == 0
    assert first["persisted"]["_offline_mock_pet"]["phase"] == "committed" and first["persisted"]["pet"] == AFTER
    resumed = run(run_production_js, baseline=first["persisted"], nativePetBefore=AFTER)
    assert resumed["nativeMailCalls"] == 0 and resumed["stored"]["pet"] == AFTER


@pytest.mark.parametrize("address", [0x3C93DD4, 0x3C93DD8, 0x3A0C618, 0x3A0C61C, 0x2C1AB40, 0x2C1AB44, 0x2C1348C, 0x2C13490])
def test_pet_native_fingerprints_are_required(run_production_js, address):
    result = run(run_production_js, badFingerprint=address)
    assert result["configurationError"] == "Mock pet native entry fingerprint mismatch"


def test_owner_identity_uses_native_current_account_instead_of_existing_pet(run_production_js):
    empty = {"petinfo": [], "bagsize": 8, "maxglobalpetid": 1}
    result = run(run_production_js, listOnly=True, ownerRoleId=20002, ownerServiceId=3, nativePetBefore=empty)
    mail = json.loads(body(result, 0))["mails"][0]
    assert result["healthy"] and mail["reward"][0]["master_unique_rid"] == 300020002
    assert all(item["master_unique_rid"] == 300020002 for item in result["petFactoryInputs"])


@pytest.mark.parametrize("condition", [{"ownerRoleId": 0}, {"ownerRoleId": 100000000}, {"ownerServiceId": -1}, {"ownerServiceId": 2147483647}, {"nullSaveManager": True}])
def test_invalid_current_account_is_never_offered(run_production_js, condition):
    result = run(run_production_js, listOnly=True, **condition)
    assert body(result, 0) is None and result["nativePetFactories"] == 0 and result["nativeMailCalls"] == 0
    assert "_offline_mock_pet" not in result["stored"]


@pytest.mark.parametrize("address", [0x2FECD6C, 0x2FECD70, 0x2FE19A4, 0x2FE19A8, 0x2FE1A98, 0x2FE1A9C])
def test_owner_identity_native_fingerprints_are_required(run_production_js, address):
    result = run(run_production_js, badFingerprint=address)
    assert result["configurationError"] == "Mock pet native entry fingerprint mismatch"


@pytest.mark.parametrize("failure", [{"failWriteAt": 2}, {"failSyncAt": 2}])
def test_pet_mail_storage_failure_retry_preserves_role_and_old_pet(run_production_js, failure):
    result = run(run_production_js, retryMail=True, repeatMail=True, reloadMail=True, **failure)
    assert json.loads(body(result, 1))["code"] == -1
    assert "reward" not in json.loads(body(result, 1))
    assert json.loads(body(result, 2))["code"] == 1000
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 1
    assert result["stored"] == result["persisted"] and result["stored"]["pet"] == AFTER
    assert result["stored"]["pet"]["petinfo"][0] == OLD_PET
    assert result["stored"]["bag"] == BAG and result["stored"]["point"] == 0
    assert result["stored"]["roledata"]["role"]["rolelv"] == 90
    assert result["stored"]["_offline_mock_pet"]["phase"] == "committed"
    assert result["afterReload"]["mails"] == []
