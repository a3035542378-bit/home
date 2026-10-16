"""验证首讨伐任务兼容规则；不代替 Android 任务 UI 与存档验证。"""
import asyncio
import json
from pathlib import Path

import pytest
from test_offline_bridge import NODE_WIRE_CHECK


BRIDGE = Path(__file__).with_name("offline_bridge.js")
SCRIPT = r"""
const fs=require('node:fs'),vm=require('node:vm');
const context=vm.createContext({Process:{findModuleByName:()=>null},Module:{getExportByName:()=>null},Interceptor:{attach:()=>{}}});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
context.input=JSON.parse(fs.readFileSync(0,'utf8'));
const before=JSON.stringify(context.input);
let result;
try{result={tasks:vm.runInContext('offlineMissionTasks(input)',context)};}
catch(error){result={error:error.message};}
result.unchanged=JSON.stringify(context.input)===before;
process.stdout.write(JSON.stringify(result));
"""


async def run(profile, script=SCRIPT):
    process = await asyncio.create_subprocess_exec(
        "node", "-e", script, str(BRIDGE),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate(json.dumps(profile).encode())
    assert process.returncode == 0, err.decode()
    return json.loads(out)


def profile(*, guides=None, story=None, role=1):
    return {"roledata": {"player": {"roleid": role, "completeguide": guides if guides is not None else [900023]}},
            "mire": {"storytask": story if story is not None else []}}


def test_first_task_uses_native_auto_accept_and_no_invented_reward():
    result = asyncio.run(run(profile()))
    assert result == {"tasks": [{"tid": 6000000, "state": 6, "targetprogress": [], "rewards": []}], "unchanged": True}


def test_native_progress_and_completion_survive_repeated_list_requests():
    task = {"tid": 6000000, "state": 3, "targetprogress": [
        {"mission_content_type": 2, "mission_target_id": 700004, "mission_progress": 1},
        {"mission_content_type": 1, "mission_target_id": 304, "mission_progress": 1},
    ]}
    result = asyncio.run(run(profile(guides=[900023, 900037], story=[task])))
    assert result["tasks"] == [{**task, "rewards": []}]
    assert result["unchanged"]


@pytest.mark.parametrize("value", [
    {}, profile(role=2), profile(guides=[]), profile(guides=[900023, 900037]),
    profile(story=[{"tid": 6000001, "state": 2, "targetprogress": []}]),
    profile(story=[{"tid": 6000000, "state": 99, "targetprogress": []}]),
    profile(story=[{"tid": 6000000, "state": 2, "targetprogress": [
        {"mission_content_type": 1, "mission_target_id": 304, "mission_progress": -1}]}]),
    profile(story=[{"tid": 6000000, "state": 2, "targetprogress": [
        {"mission_content_type": 1, "mission_target_id": 999, "mission_progress": 1}]}]),
])
def test_unknown_tasks_bad_progress_and_reseeding_are_rejected(value):
    result = asyncio.run(run(value))
    assert "error" in result
    assert result["unchanged"]


def test_mission_wire_persists_native_snapshot_and_task_before_ack():
    snapshot = profile()
    snapshot["roledata"]["role"] = {"rolelv": 7}
    snapshot["bag"] = {"spiritcount": 17145}
    result = asyncio.run(run({"tag": "REQUEST_MISSION_LIST", "command": 24,
        "nativeStore": True, "nativePoint": "0", "send": True,
        "requestBody": {"savedata": snapshot}}, NODE_WIRE_CHECK))
    assert result.get("callbackError") is None
    response = json.loads(result["writes"][0]["body"])
    stored = json.loads(result["stored"])
    assert stored["bag"]["spiritcount"] == 17145
    assert stored["mire"]["storytask"] == response["storytask"]
    assert response["storytask"][0]["tid"] == 6000000
    assert result["diskWrites"] == 2 and result["healthy"]


@pytest.mark.parametrize("body", [None, {"savedata": {"unknown_event": {}}}])
def test_mission_wire_does_not_ack_missing_or_unsupported_save(body):
    result = asyncio.run(run({"tag": "REQUEST_MISSION_LIST", "command": 24,
        "nativeStore": True, "nativePoint": "0", "send": True,
        "requestBody": body if body is not None else {}}, NODE_WIRE_CHECK))
    assert result["writes"] == []
    assert result["diskWrites"] == 0


def test_mission_wire_does_not_invent_missing_point_or_seed_task():
    snapshot = profile()
    snapshot["roledata"]["role"] = {"rolelv": 7}
    result = asyncio.run(run({"tag": "REQUEST_MISSION_LIST", "command": 24,
        "nativeStore": True, "send": True, "requestBody": {"savedata": snapshot}}, NODE_WIRE_CHECK))
    assert result["writes"] == []
    assert json.loads(result["stored"])["mire"]["storytask"] == []
