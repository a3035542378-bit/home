"""用原脚本及 native/文件替身验证出战事务；不替代 Android 冷启验收。"""

import asyncio
import json
from pathlib import Path

import pytest

from test_offline_bridge import NODE_WIRE_CHECK


BRIDGE = Path(__file__).with_name("offline_bridge.js")
# 复用现有 native JsonCpp/原子文件替身，只增加宠物 serializer 与多 observer 支持。
SCRIPT = NODE_WIRE_CHECK.split("try { context.configureRoleWire(game, store); }", 1)[0]
SCRIPT = SCRIPT.replace(
    "const hooks = new Map()",
    "let nativePetSnapshot=input.nativePet; const petSnapshots=[]; const hooks = new Map()",
).replace(
    "0x29b9468: 0xd10743ff",
    """0x2bff884:0xd102c3ff,0x2bff888:0xa90053f3,
      0x2c1348c:0xd10083ff,0x2c13490:0xa90053f3,
      0x2c1ab40:0xf001dac2,0x2c1ab44:0xd10443ff,
      0x2ab7c78:0xd102c3ff,0x2ab7c7c:0xa9015bf5,
      0x2a7d980:0xd100c3ff,0x2a7d984:0xa90053f3,
      0x2ab9290:0xd10483ff,0x2ab9294:0xa9036bf9,
      0x2afba4c:0xd10703ff,0x2afba50:0xd10183ff,
      0x2fe924c:0xd100c3ff,0x2fe9250:0xa9015bf5,
      0x2fea720:0xd10143ff,0x2fea724:0xa90053f3,
      0x29b9468: 0xd10743ff""",
).replace(
    "hooks.set(address.address ?? address, callbacks)",
    "hooks.set(address.address ?? address, [...(hooks.get(address.address ?? address) ?? []), callbacks])",
).replace(
    "if (address.address === 0x4e5f094 || address.address === 0x2d1f964)",
    "if (address.address === 0x2c1348c || address.address === 0x4e5f094 || address.address === 0x2d1f964)",
).replace(
    "if (args[2].address !== 0x2d4053c)",
    """if(args[2].address===0x2c1ab40){
        if(args[0].address!==0x7000)throw new Error('Wrong PetMgr');
        petSnapshots.push(args[1].address);
        values.set(args[1].address,{value:parseValue(JSON.stringify(nativePetSnapshot))});return;
      }
      if (args[2].address !== 0x2d4053c)""",
)
SCRIPT += r"""
let predicate;
try{
 predicate=context.configureOfflinePetState(game,store);
 context.configureRoleWire(game,store,predicate);
}catch(error){process.stdout.write(JSON.stringify({configurationError:error.message,diskWrites}));process.exit(0);}
function enter(address,args,threadId,caller=0){
 return (hooks.get(address)??[]).map(callback=>{
  const invocation={threadId,returnAddress:pointer(caller)};
  callback.onEnter?.call(invocation,args);return {callback,invocation};
 });
}
function leave(invocations,result){for(const {callback,invocation} of invocations)callback.onLeave?.call(invocation,result);}
const requests=[];
for(const query of input.queries??[{}]){
 const body=query.body??{rid:10001,pet_id:4399,state:1};
 const root=string(''),tag=string(query.tag??'REQUEST_PET_SET_TAMESTATE');
 const request=query.reuse===undefined?string(''):requests[query.reuse].request,raw=string('');
 values.set(root.address,{value:parseValue(JSON.stringify(body))});
 memory.set(request.address+0x40,tag);memory.set(raw.address+0x18,request);
 nativePetSnapshot=query.pet??input.nativePet;
 const thread=query.thread??1;
 const sender=query.skipSender?[]:enter(0x2bff884,[pointer(query.manager??0x7000),pointer(query.nullPet?0:0x7100),pointer(query.senderState??body.state)],thread);
 const constructor=enter(query.oldConstructor?0x2ab9290:0x2ab7c78,[pointer(0),pointer(query.command??478),root,pointer(0),tag],query.requestThread??thread);
 const committedBeforeBind=diskWrites;
 if(!query.skipQueue)enter(0x2a7d980,[pointer(0),query.nullRequest?pointer(0):request],query.queueThread??query.requestThread??thread,query.queueCaller??0x2ab8c74);
 leave(constructor,query.nullRequest?pointer(0):request);leave(sender,pointer(1));
 requests.push({request,raw,committedBeforeBind,prepared:predicate(request)});
}
if(input.failBeforeResponse)store.blockLottery();
const packets=[];
for(const index of input.responseOrder??requests.map((_request,index)=>index)){
 const {request,raw}=requests[index],start=writes.length;
 enter(0x2ab75d8,[pointer(0),pointer(0),raw],1);
 const converter=[pointer(0),request,pointer(0),pointer(1),pointer(1)];
 enter(0x2a97c18,converter,1);
 packets.push({index,writes:writes.slice(start),decode:converter[4].toInt32()});
}
const storedText=store.exists()?store.text():null;
let restored=null;
if(input.reload&&persisted!==null){diskText=persisted;reads=0;restored=JSON.parse(context.createNativeSaveStore(game).roleResponse()).savedata;}
process.stdout.write(JSON.stringify({packets,prepared:requests.map(({prepared,committedBeforeBind})=>({prepared,committedBeforeBind})),
 diskWrites,healthy:store.healthy(),storedText,persisted: persisted===null?null:JSON.parse(persisted),
 restored,snapshotCalls,petSnapshots,destroyed,reports}));
"""


async def run(**options):
    process = await asyncio.create_subprocess_exec(
        "node", "-e", SCRIPT, str(BRIDGE), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    output, error = await process.communicate(json.dumps({"nativeStore": True, **options}).encode())
    assert process.returncode == 0, error.decode()
    return json.loads(output)


def pet_snapshot():
    return {"petinfo": [
        {"petid": 4399, "dataid": 210, "tamestate": 1, "petexp": 80, "lifetime": 97},
        {"petid": 4400, "dataid": 210, "tamestate": 2, "petexp": 20, "lifetime": 98},
    ], "bagsize": 8, "maxglobalpetid": 4401}


def test_native_full_pet_snapshot_is_saved_before_ack_and_survives_restore():
    baseline = {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 7}},
                "bag": {"spiritcount": 17145}, "point": 0, "mire": {"storytask": []},
                "pet": {"petinfo": [{"petid": 4399, "tamestate": 2}], "bagsize": 8, "maxglobalpetid": 4400}}
    result = asyncio.run(run(nativePet=pet_snapshot(), baseline=baseline, reload=True))
    assert result.get("configurationError") is None
    assert result["healthy"] and result["diskWrites"] == 1
    assert result["prepared"] == [{"prepared": True, "committedBeforeBind": 1}]
    stored = json.loads(result["storedText"])
    assert stored == {**baseline, "pet": pet_snapshot()}
    assert result["restored"]["pet"] == pet_snapshot()
    assert result["snapshotCalls"] == 1
    assert all(pointer in result["destroyed"] for pointer in result["petSnapshots"])
    assert json.loads(result["packets"][0]["writes"][0]["body"]) == {"code": 1000}
    assert result["packets"][0]["decode"] == 0


def test_pet_capture_preserves_int64_point_without_js_roundtrip():
    result = asyncio.run(run(nativePet=pet_snapshot(), nativePoint="9223372036854775807"))
    assert '"point":9223372036854775807' in result["storedText"]


@pytest.mark.parametrize("query", [
    {"skipSender": True}, {"senderState": 2}, {"requestThread": 2}, {"manager": 0x7500},
    {"nullPet": True}, {"command": 477}, {"tag": "REQUEST_OTHER_PET"},
    {"oldConstructor": True},
    {"body": {"rid": "10001", "pet_id": 4399, "state": 1}},
    {"body": {"rid": 10002, "pet_id": 4399, "state": 1}},
    {"body": {"rid": 10001, "pet_id": 4399, "state": 2}},
    {"body": {"rid": 10001, "pet_id": 4401, "state": 1}},
    {"body": {"rid": 10001, "pet_id": 4399, "state": 1, "unknown": 1}},
])
def test_unowned_or_unsupported_requests_never_receive_local_success(query):
    result = asyncio.run(run(nativePet=pet_snapshot(), queries=[query]))
    assert result["diskWrites"] == 0
    assert result["packets"] == [{"index": 0, "writes": [], "decode": 1}]


@pytest.mark.parametrize("snapshot", [
    {}, {"petinfo": [], "bagsize": 8, "maxglobalpetid": 4400},
    {**pet_snapshot(), "bagsize": -1}, {**pet_snapshot(), "maxglobalpetid": 2**32},
    {**pet_snapshot(), "petinfo": [{"petid": 4399, "tamestate": 2}]},
    {**pet_snapshot(), "petinfo": [{"petid": 4399, "tamestate": 1}] * 2},
])
def test_incomplete_or_mismatched_snapshot_cannot_be_acknowledged(snapshot):
    result = asyncio.run(run(nativePet=snapshot))
    assert result["diskWrites"] == 0
    assert result["packets"][0]["writes"] == []
    assert all(pointer in result["destroyed"] for pointer in result["petSnapshots"])


@pytest.mark.parametrize("options", [{"failWriteAt": 1}, {"failDirectorySync": True}, {"snapshotFails": True}, {"noBaseline": True}])
def test_storage_or_native_failure_never_changes_failure_response(options):
    result = asyncio.run(run(nativePet=pet_snapshot(), **options))
    assert result["packets"][0] == {"index": 0, "writes": [], "decode": 1}
    assert not result["prepared"][0]["prepared"]
    if "failWriteAt" in options or "failDirectorySync" in options:
        assert not result["healthy"]


def test_request_identity_and_thread_binding_survive_out_of_order_responses():
    result = asyncio.run(run(nativePet=pet_snapshot(), queries=[{}, {"skipSender": True}], responseOrder=[1, 0]))
    assert result["packets"][0]["writes"] == []
    assert result["packets"][1]["writes"][0]["body"] == '{"code":1000}'
    assert result["diskWrites"] == 1


def test_reused_unprepared_request_pointer_revokes_old_identity():
    result = asyncio.run(run(nativePet=pet_snapshot(), queries=[{}, {"reuse": 0, "skipSender": True}]))
    assert all(packet["writes"] == [] for packet in result["packets"])
    assert result["diskWrites"] == 1


def test_later_storage_failure_revokes_prepared_response():
    result = asyncio.run(run(nativePet=pet_snapshot(), failBeforeResponse=True))
    assert result["diskWrites"] == 1
    assert result["packets"][0]["writes"] == []
    assert result["packets"][0]["decode"] == 1


@pytest.mark.parametrize("query", [{"skipQueue": True}, {"queueCaller": 0}, {"queueThread": 2}])
def test_committed_state_requires_the_matching_real_queue_call(query):
    result = asyncio.run(run(nativePet=pet_snapshot(), queries=[query]))
    assert result["diskWrites"] == 1
    assert not result["prepared"][0]["prepared"]
    assert result["packets"][0]["writes"] == []


@pytest.mark.parametrize("address", [0x2bff884, 0x2c1348c, 0x2c1ab40, 0x2ab7c78, 0x2a7d980])
def test_unknown_native_build_is_rejected_before_hooking(address):
    result = asyncio.run(run(nativePet=pet_snapshot(), badFingerprint=address))
    assert "Pet state native entry fingerprint mismatch" in result["configurationError"]
    assert result["diskWrites"] == 0
