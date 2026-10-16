"""实验桥生成边界测试；不代替原 ARM64 工厂和 Android 验收。"""
import asyncio
import copy
import json
from pathlib import Path

import pytest

from debug_fusion_response import FIELDS, build_fusion_script

ROOT = Path(__file__).resolve().parents[2]


def inputs():
    source = Path(__file__).with_name("offline_bridge.js").read_text()
    profile = {"roledata": {"player": {"roleid": 1}}, "pet": {"petinfo": []}}
    for pet_id, data_id, level in ((4405, 221, 75), (4406, 229, 60)):
        profile["pet"]["petinfo"].append({"petid": pet_id, "dataid": data_id, "level": level,
            "tamestate": 2, "master_unique_rid": 100010001, "hpimprove": 800, "mpimprove": 500,
            "strimprove": 800, "defimprove": 300, "comprehension": 5, "spiritpower": 1, "bonelevel": 1})
    template = {k: 0 for k in FIELDS}
    template.update(spiritid=9001, skill=[], petequips=[], talentskill=[], passiveskill=[],
                    sageskillposition=[], triones=[1, 1, 0, 0, 0, 0, 0, 0, 0], mastername="",
                    opskilllevel=None, sageskilllevel=None, opsageskilllevel=None, tabooextraskilllevel=None)
    return source, profile, template


def test_requires_explicit_experimental_mode():
    with pytest.raises(ValueError, match="Explicit experimental"):
        build_fusion_script(*inputs())


def test_generation_preserves_inputs_and_orders_native_fingerprint_checks():
    source, profile, template = inputs()
    original = copy.deepcopy((profile, template))
    script = build_fusion_script(source, profile, template, experimental=True)
    assert (profile, template) == original
    assert "RESPONSE_JSON" not in script
    assert "DEBUG_ONLY_FIXED_COMPAT_9001" in script
    assert "configureDebugTrueSpiritEntry(game,offlineStore);configureDebugFusion(game,offlineStore);" in script
    assert "store.debugFusionSave(before,debugFusion.receipt);" in script
    assert script.index("store.debugFusionSave(before,debugFusion.receipt);") < script.index("debugFusion.response=JSON.stringify(response)")
    assert "snapshot(objectAt(array,i),0x3a67b30)" in script
    assert "getPets().add(0x298)" in script
    assert "find(getBag(),key,-1,1)" in script
    assert "result.replace(0);debugFusion.response=null;" in script
    assert "Existing fusion receipt:" in script
    assert "JSON.stringify(snapshot.true_spirit_bag)" in script
    assert "key!=='_DEBUG_ONLY_fusion'" in script
    assert "thunk};" in script


@pytest.mark.parametrize("case", ["changed_source", "other_role", "existing_receipt", "existing_spirit", "empty_old_bag", "duplicate_pet", "colliding_id", "wrong_pair", "wrong_owner", "wrong_level", "battle_pet", "unknown_template", "wrong_template_type", "nondefault_template", "bad_attribute"])
def test_rejects_unsafe_or_unsupported_generation(case):
    source, profile, template = inputs()
    if case == "changed_source": source += "\n"
    elif case == "other_role": profile["roledata"]["player"]["roleid"] = 2
    elif case == "existing_receipt": profile["_DEBUG_ONLY_fusion"] = {"phase": "prepared"}
    elif case == "existing_spirit": profile["true_spirit_bag"] = {"list": [{"globalid": 1}]}
    elif case == "empty_old_bag": profile["true_spirit_bag"] = {"list": [], "bagsize": 8, "maxspiritid": 9999}
    elif case == "duplicate_pet": profile["pet"]["petinfo"].append(copy.deepcopy(profile["pet"]["petinfo"][0]))
    elif case == "colliding_id": profile["pet"]["petinfo"].append({"petid": 4407})
    elif case == "wrong_pair": profile["pet"]["petinfo"][0]["dataid"] = 229
    elif case == "wrong_owner": profile["pet"]["petinfo"][0]["master_unique_rid"] = 200010001
    elif case == "wrong_level": profile["pet"]["petinfo"][0]["level"] = 74
    elif case == "battle_pet": profile["pet"]["petinfo"][0]["tamestate"] = 1
    elif case == "unknown_template": template["petid"] = 1
    elif case == "wrong_template_type": template["spiritid"] = 9003
    elif case == "nondefault_template": template["globalid"] = 42
    elif case == "bad_attribute": profile["pet"]["petinfo"][0]["hpimprove"] = float("nan")
    with pytest.raises(ValueError):
        build_fusion_script(source, profile, template, experimental=True)


def test_generated_javascript_parses(tmp_path):
    async def check():
        output = tmp_path / "experiment.js"
        output.write_text(build_fusion_script(*inputs(), experimental=True))
        process = await asyncio.create_subprocess_exec("node", "--check", str(output), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, error = await process.communicate()
        assert process.returncode == 0, error.decode()
    asyncio.run(check())


def run_native_store(tmp_path, payload):
    from test_offline_bridge import NODE_WIRE_CHECK
    async def execute():
        generated = tmp_path / "bridge.js"
        generated.write_text(build_fusion_script(*inputs(), experimental=True))
        harness = NODE_WIRE_CHECK.replace("{results, stored: JSON.parse(store.text())", "{results, persistedText: persisted, stored: JSON.parse(store.text())").replace("else throw new Error('Unknown test action');", "else if (action.kind === 'fusion') store.debugFusionSave(action.snapshot, action.receipt); else throw new Error('Unknown test action');", 1)
        process = await asyncio.create_subprocess_exec("node", "-e", harness, str(generated), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate(json.dumps(payload).encode())
        assert process.returncode == 0, stderr.decode()
        return json.loads(stdout)
    return asyncio.run(execute())


def fusion_actions():
    _, _, spirit = inputs()
    spirit.update(globalid=4407, level=75, skill=[9001000, 9001010, 9001020, 9001030])
    before = {"bag": {"spiritcount": 17245}, "pet": {"petinfo": [{"petid": 4405}, {"petid": 4406}]}, "true_spirit_bag": {"list": [], "bagsize": 10, "maxspiritid": 0}}
    after = {"bag": {"spiritcount": 17245}, "pet": {"petinfo": []}, "true_spirit_bag": {"list": [spirit], "bagsize": 10, "maxspiritid": 4407}}
    return [{"kind": "fusion", "snapshot": before, "receipt": {"phase": "prepared"}},
            {"kind": "fusion", "snapshot": after, "receipt": {"phase": "committed"}}, {"kind": "reload"}]


def test_store_commits_separate_spirit_bag_and_receipt_together_and_projects_cold_role(tmp_path):
    result = run_native_store(tmp_path, {"nativeStore": True, "lotteryActions": fusion_actions()})
    assert all("error" not in row for row in result["results"])
    assert result["stored"]["_DEBUG_ONLY_fusion"]["phase"] == "committed"
    assert result["role"]["savedata"]["true_spirit_bag"]["list"][0]["globalid"] == 4407
    assert "_DEBUG_ONLY_fusion" not in result["role"]["savedata"]
    assert result["stored"]["pet"]["petinfo"] == []


def test_commit_write_failure_keeps_prepared_sources_on_restart(tmp_path):
    result = run_native_store(tmp_path, {"nativeStore": True, "failWriteAt": 2, "lotteryActions": fusion_actions()})
    assert "write failed" in result["results"][1]["error"]
    assert result["stored"]["_DEBUG_ONLY_fusion"]["phase"] == "prepared"
    assert result["stored"]["true_spirit_bag"]["list"] == []
    assert len(result["stored"]["pet"]["petinfo"]) == 2


def test_prepare_write_failure_blocks_followup_commit(tmp_path):
    result = run_native_store(tmp_path, {"nativeStore": True, "failWriteAt": 1, "lotteryActions": fusion_actions()[:2]})
    assert "write failed" in result["results"][0]["error"]
    assert "previously failed" in result["results"][1]["error"]
    assert "true_spirit_bag" not in result["stored"]
    assert result["persisted"] is None


def test_directory_sync_failure_recovers_actual_durable_prepared_state(tmp_path):
    actions = fusion_actions()
    result = run_native_store(tmp_path, {"nativeStore": True, "failDirectorySync": True, "lotteryActions": actions})
    assert "directory flush failed" in result["results"][0]["error"]
    assert "previously failed" in result["results"][1]["error"]
    assert result["stored"]["_DEBUG_ONLY_fusion"]["phase"] == "prepared"
    assert result["stored"]["true_spirit_bag"]["list"] == []


@pytest.mark.parametrize("case", ["duplicate", "counter", "capacity", "missing_field", "ordinary_pet", "invalid_skill", "scalar", "equipment"])
def test_runtime_spirit_schema_rejects_invalid_native_snapshot(tmp_path, case):
    actions = fusion_actions()
    bag = actions[1]["snapshot"]["true_spirit_bag"]
    if case == "duplicate": bag["list"].append(copy.deepcopy(bag["list"][0]))
    elif case == "counter": bag["maxspiritid"] = 1
    elif case == "capacity": bag["bagsize"] = 0
    elif case == "missing_field": del bag["list"][0]["globalid"]
    elif case == "ordinary_pet": bag["list"][0]["spiritid"] = 221
    elif case == "invalid_skill": bag["list"][0]["skill"] = [-1]
    elif case == "scalar": bag["list"][0]["hpimprove"] = "800"
    elif case == "equipment": bag["list"][0]["petequips"] = [{"petid": 1}]
    result = run_native_store(tmp_path, {"nativeStore": True, "lotteryActions": actions})
    assert "error" in result["results"][1]
    assert result["stored"]["_DEBUG_ONLY_fusion"]["phase"] == "prepared"
    assert result["stored"]["true_spirit_bag"]["list"] == []


def test_native_inventory_snapshot_keeps_int64_owner_text(tmp_path):
    actions = fusion_actions()
    exact = 9223372036854775806
    actions[1]["snapshot"]["bag"]["_DEBUG_ONLY_raw"] = '{"spiritcount":17245,"item":[{"A2":904180,"UNIRID":'+str(exact)+'}]}'
    result = run_native_store(tmp_path, {"nativeStore": True, "lotteryActions": actions})
    assert all("error" not in row for row in result["results"])
    assert '"UNIRID":'+str(exact) in result["persistedText"]


def run_guard(name, args):
    async def execute():
        harness = "const fs=require('fs'),vm=require('vm');const c=vm.createContext({});vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);const i=JSON.parse(fs.readFileSync(0,'utf8'));try{c[i.name](...i.args);process.stdout.write(JSON.stringify({accepted:true}));}catch(e){process.stdout.write(JSON.stringify({accepted:false,error:e.message}));}"
        process = await asyncio.create_subprocess_exec("node", "-e", harness, str(Path(__file__).with_name("debug_fusion_response.js")), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, error = await process.communicate(json.dumps({"name": name, "args": args}).encode())
        assert process.returncode == 0, error.decode()
        return json.loads(out)
    return asyncio.run(execute())


@pytest.mark.parametrize("phase", ["prepared", "committed", "unknown", False, 0])
def test_existing_or_ambiguous_receipt_blocks_duplicate_request(phase):
    receipt = {"phase": phase} if isinstance(phase, str) else phase
    assert not run_guard("assertDebugFusionCanPrepare", [receipt])["accepted"]


def test_no_receipt_allows_first_request():
    assert run_guard("assertDebugFusionCanPrepare", [None])["accepted"]


@pytest.mark.parametrize("case,accepted", [("first", True), ("reordered", True), ("duplicate", False), ("unprepared", False), ("mismatch", False)])
def test_response_guard_requires_exact_prepared_result_once(case, accepted):
    body = {"code": 1000, "target": {"spiritid": 9001, "globalid": 4407}}
    state = {"response": json.dumps(body), "used": case == "duplicate"}
    if case == "unprepared": state["response"] = None
    if case == "mismatch": body["target"]["globalid"] = 4408
    if case == "reordered": body = {"target": {"globalid": 4407, "spiritid": 9001}, "code": 1000}
    assert run_guard("assertDebugFusionResponse", [state, body])["accepted"] is accepted


@pytest.mark.parametrize("case", ["valid", "material1", "material2", "missing_pet", "wrong_type", "low_level", "battle_pet", "duplicate", "id_collision", "existing_spirit", "other_role"])
def test_native_input_guard_checks_materials_and_real_source_instances(case):
    _, profile, _ = inputs()
    req = {"rid": 10001, "main_pet": {"type_id": 221, "global_id": 4405}, "auxiliary_pet": {"type_id": 229, "global_id": 4406}, "is_common_fusion": 1}
    before = {"pet": profile["pet"], "true_spirit_bag": {"list": []}, "materials": [{"A2": 503345, "A4": 100}, {"A2": 503346, "A4": 100}]}
    if case == "material1": before["materials"][0]["A4"] = 1
    elif case == "material2": before["materials"][1]["A4"] = 5
    elif case == "missing_pet": before["pet"]["petinfo"].pop()
    elif case == "wrong_type": before["pet"]["petinfo"][0]["dataid"] = 229
    elif case == "low_level": before["pet"]["petinfo"][0]["level"] = 74
    elif case == "battle_pet": before["pet"]["petinfo"][0]["tamestate"] = 1
    elif case == "duplicate": before["pet"]["petinfo"].append(copy.deepcopy(before["pet"]["petinfo"][0]))
    elif case == "id_collision": before["pet"]["petinfo"].append({"petid": 4407})
    elif case == "existing_spirit": before["true_spirit_bag"]["list"] = [{"globalid": 1}]
    elif case == "other_role": req["rid"] = 20001
    assert run_guard("validateDebugFusionSources", [req, before])["accepted"] is (case == "valid")


def test_exit_after_preparation_keeps_both_pets_and_blocks_unknown_retry(tmp_path):
    result = run_native_store(tmp_path, {"nativeStore": True, "lotteryActions": [fusion_actions()[0], {"kind": "reload"}]})
    assert len(result["stored"]["pet"]["petinfo"]) == 2
    assert result["stored"]["true_spirit_bag"]["list"] == []
    assert not run_guard("assertDebugFusionCanPrepare", [result["stored"]["_DEBUG_ONLY_fusion"]])["accepted"]


def test_lost_success_response_reload_retains_single_result_and_blocks_new_request(tmp_path):
    result = run_native_store(tmp_path, {"nativeStore": True, "lotteryActions": fusion_actions()})
    assert len(result["stored"]["true_spirit_bag"]["list"]) == 1
    assert not run_guard("assertDebugFusionCanPrepare", [result["stored"]["_DEBUG_ONLY_fusion"]])["accepted"]
