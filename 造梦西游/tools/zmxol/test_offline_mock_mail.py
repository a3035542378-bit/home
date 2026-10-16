"""原生产邮件 store/wire 契约测试；native、文件和通知均为替身，不代表实机领取。"""

import copy
import json

import pytest

from test_offline_bridge import NODE_WIRE_CHECK, run_production_js


MAIL_ID = 900504100
LIST = {"rid": 10001, "type": 2, "owner_type": 2, "offset": 0}
CLAIM = {"rid": "10001", "id": MAIL_ID, "type": 37, "mtype": 0, "is_user": 0, "offset": 0}
BEFORE = {"spiritcount": 2080, "item": [{"A2": 504100, "A4": 4}]}
AFTER = {"spiritcount": 2080, "item": [{"A2": 504100, "A4": 5}]}
BAGUA_ID = 900504200
BAGUA_ITEM = {"A2": 504200, "A4": 1, "A5": 4406, "A7": 91, "UNIRID": 100010001,
              "AQ": 0, "AT": 0, "AV": 0, "AW": 0, "BE": 0}
BAGUA_RECEIPT = {"version": 1, "rid": 10001, "id": BAGUA_ID, "phase": "committed",
                 "dateline": 1, "expired": 2000000000, "reward": [BAGUA_ITEM]}
PET_ID = 900000252
PET_ITEM = {"dataid": 252, "level": 60, "petid": 1, "petexp": 0, "lifetime": 100,
            "tamestate": 2, "iselite": 0, "ferity": 1, "mixlevel": 0, "isspecialchange": 0,
            "basehp": 150, "basemp": 100, "basestr": 10, "basedef": 2, "hpimprove": 600,
            "mpimprove": 600, "strimprove": 600, "defimprove": 200, "comprehension": 1,
            "spiritpower": 1, "bonelevel": 1, "skill": [210000, 210010, 210020, 210030, 210040, 210050],
            "triones": [1, 1, 0, 0, 0, 0, 0, 0, 0], "petequips": [], "master_unique_rid": 100010001}
PET_RECEIPT = {"version": 1, "rid": 10001, "id": PET_ID, "phase": "committed",
               "dateline": 1, "expired": 2000000000, "reward": [PET_ITEM]}


def mail_harness():
    script = NODE_WIRE_CHECK

    def replace(old, new):
        nonlocal script
        assert script.count(old) == 1
        script = script.replace(old, new)

    replace("let store = input.nativeStore", "if (!input.petMailWire) { const profile = parseValue(diskText); profile._offline_mock_pet = parseValue(" + json.dumps(json.dumps(PET_RECEIPT)) + "); diskText = JSON.stringify(profile); }\nlet store = input.nativeStore")

    replace("let nativeLotteryCalls = 0, nativeOtherCalls = 0;", "let nativeLotteryCalls = 0, nativeOtherCalls = 0, nativeMailCalls = 0, nativeMailAcks = 0, nativeMailClears = 0, nativeBaguaFactories = 0, diskOpens = 0;\nconst mailSteps = [], mailIds = new Map(), baguaObjects = new Map();")
    replace("if (address.address === 0x3c6b750) {", r"""
    if (address.address === 0x3d293b8) {
      const array = values.get(args[0].address).value, result = string('');
      values.set(result.address, {get value() { return array[args[1]] ?? null; }}); return result;
    }
    if (input.baguaWire && address.address === 0x3c6b750) {
      nativeBaguaFactories++;
      if (input.factoryNull) return pointer(0);
      const source = values.get(args[0].address).value, object = pointer(0x720000 + nativeBaguaFactories * 0x100);
      let snapshot = source.A5 === undefined ? parseValue(JSON.stringify(input.nativeBaguaItem)) : parseValue(JSON.stringify(source));
      if (input.roundtripChange && nativeBaguaFactories === 2) snapshot = {...snapshot, ...parseValue(JSON.stringify(input.roundtripChange))};
      baguaObjects.set(object.address, snapshot); return object;
    }
    if (input.baguaWire && address.address === 0x4ffd82c) {
      if (input.castNull) return pointer(0);
      memory.set(args[0].address, pointer(0x730000)); memory.set(0x7300b8, pointer(input.badBaguaType ? 0x3c85cb0 : 0x3c85cac)); return args[0];
    }
    if (address.address === 0x3c6b750) {""")
    replace("if (args[2].address !== 0x2d4053c)", "if (args[2].address === 0x3c85cac) { values.set(args[1].address, {value: parseValue(JSON.stringify(baguaObjects.get(args[0].address)))}); return; }\n      if (args[2].address !== 0x2d4053c)")
    replace("if (address.address === 0x29b9468) {", r"""
    if (address.address === 0xdeada070) return pointer(mailIds.get(args[0].address));
    if (address.address === 0x2fe924c || address.address === 0x2fea720) {
      if (address.address === 0x2fe924c) nativeMailAcks++; else nativeMailClears++;
      mailSteps.push({kind: address.address === 0x2fe924c ? 'ack' : 'clear', phase: JSON.parse(persisted ?? diskText)._offline_mock_mail?.phase}); return;
    }
    if (address.address === 0x2afba4c) {
      const tag = args[1].add(0x38).readPointer().add(0x18).readPointer().readUtf8String();
      if (tag !== 'REQUEST_MAIL_RECIEVE_REWARD') { nativeOtherCalls++; return; }
      nativeMailCalls++;
      mailSteps.push({kind: 'reward', phase: JSON.parse(persisted ?? diskText)._offline_mock_mail?.phase});
      if (!input.skipMailAck) replacements.get(0x2fe924c).call({returnAddress: pointer(input.mailAckCaller ?? 0x2afc4fc)}, pointer(0xa000), pointer(0xa100));
      replacements.get(0x2fea720).call({returnAddress: pointer(0x2afc504)}, pointer(0xa000));
      replacements.get(0x4e5f908).call({returnAddress: pointer(0x2afbe30)}, pointer(0x7000), string('GO_ON'));
      return;
    }
    if (address.address === 0x29b9468) {""")
    replace("const bag = input.recoveryRuns && nativeAddCalls === 0 ? input.nativeBagBefore : input.nativeBagAfter;", "const bag = input.mailWire ? (nativeMailCalls === 0 ? (input.baguaWire && nativeBaguaFactories ? input.nativeBagReserved : input.nativeBagBefore) : input.nativeBagAfter) : (input.recoveryRuns && nativeAddCalls === 0 ? input.nativeBagBefore : input.nativeBagAfter);")
    replace("input.recoveryRuns && nativeAddCalls === 0 ? input.nativePoint", "(input.mailWire ? nativeMailCalls === 0 : input.recoveryRuns && nativeAddCalls === 0) ? input.nativePoint")
    replace("notifications.push({name: args[1].readUtf8String(), phase: persisted === null ? null : JSON.parse(persisted)._offline_lottery?.phase}); return;", "notifications.push({name: args[1].readUtf8String(), phase: persisted === null ? null : JSON.parse(persisted)._offline_mock_mail?.phase}); return;")
    replace("input.failDirectorySync && args[0] === 8", "(input.failDirectorySync || diskWrites === input.failDirectorySyncAt) && args[0] === 8")
    replace("if (args[1] & 0x200) pendingDisk = '';", "if (!(args[1] & 0x200) && !(args[1] & 0x4000)) { reads = 0; diskText = ++diskOpens > 1 && input.changedDiskOnRetry ? JSON.stringify(input.changedDiskOnRetry) : persisted ?? diskText; }\n      if (args[1] & 0x200) pendingDisk = '';")
    replace("if (name === 'fsync') return", "if (name === 'fsync' && args[0] !== 8 && diskWrites === input.failSyncAt) return {value: -1, errno: 5};\n    if (name === 'fsync') return")
    replace("if (input.recoveryRuns) {", r"""
if (input.mailWire) {
  const packets = [];
  function fire(command, tagText, body) {
    const root = string(''), tag = string(tagText), request = string(''), raw = string('');
    values.set(root.address, {value: parseValue(JSON.stringify(body))});
    memory.set(request.address + 0x40, tag); memory.set(raw.address + 0x18, request);
    const start = writes.length;
    const args = [pointer(0), pointer(command), root, pointer(0), tag];
    if (input.legacyMailSender) hooks.get(0x2ab7c78).onEnter(args);
    else {
      const invocation = {returnAddress: pointer(input.mailCaller ?? 0x2af36e0)};
      hooks.get(0x2ab9290).onEnter.call(invocation, args);
      hooks.get(0x2ab9290).onLeave.call(invocation, input.nullMailRequest ? pointer(0) : request);
    }
    if (input.wrongRawRequest) {
      const other = string(''); memory.set(other.address + 0x40, tag); memory.set(raw.address + 0x18, other);
    }
    hooks.get(0x2ab75d8).onEnter([pointer(0), pointer(0), raw]);
    const packet = {tag: tagText, id: body.id, writes: writes.slice(start)}; packets.push(packet); return packet;
  }
  const list = fire(552, 'REQUEST_REQUEST_MAIL_LIST_NEW', input.listRequest);
  if (input.unrelatedNativeCalls) {
    const response = string(''), tagObject = string('');
    memory.set(tagObject.address + 0x18, string('REQUEST_OTHER_MAIL'));
    memory.set(response.address + 0x38, tagObject);
    replacements.get(0x2afba4c)(pointer(0x7100), response);
    replacements.get(0x2fe924c).call({returnAddress: pointer(0x1234)}, pointer(0xa000), pointer(0xa100));
    replacements.get(0x2fea720).call({returnAddress: pointer(0x1234)}, pointer(0xa000));
    replacements.get(0x4e5f908).call({returnAddress: pointer(0x1234)}, pointer(0x7000), string('GO_ON'));
  }
  if (!input.listOnly) {
    const claim = input.claimRequest;
    if (!input.omitSavedata) claim.savedata = input.claimSavedata ?? {bag: input.nativeBagBefore};
    const packet = fire(14, 'REQUEST_MAIL_RECIEVE_REWARD', claim);
    function deliver(packet) {
    const body = packet.writes.find(write => write.body !== undefined)?.body ?? '{}';
    const response = string(''), tagObject = string(''), bodyObject = string('');
    memory.set(tagObject.address + 0x18, string('REQUEST_MAIL_RECIEVE_REWARD'));
    memory.set(bodyObject.address + 0x18, string(input.mismatchMailBody ? '{}' : body));
    memory.set(response.address + 0x38, tagObject); memory.set(response.address + 0x30, bodyObject);
    memory.set(response.address, pointer(input.badMailVtable ? 0x6045ea8 : 0x6045ea0));
    memory.set(0x6045f10, pointer(0xdeada070)); mailIds.set(response.address, input.mailUserdata ?? packet.id);
    replacements.get(0x2afba4c)(pointer(0x7100), response);
    if (input.repeatMail) replacements.get(0x2afba4c)(pointer(0x7100), response);
    }
    if (!input.noDeliver) deliver(packet);
    if (input.repeatMailRequest) fire(14, 'REQUEST_MAIL_RECIEVE_REWARD', claim);
    if (input.retryMail) { const next = fire(14, 'REQUEST_MAIL_RECIEVE_REWARD', input.retryMailId === undefined ? claim : {...claim, id: input.retryMailId}); deliver(next); if (input.lateFirstMail) deliver(packet); }
  }
  let afterReload;
  if (input.reloadMail) {
    diskText = persisted ?? diskText; reads = 0; store = context.createNativeSaveStore(game);
    afterReload = JSON.parse(store.mockMailList(input.listRequest));
  }
  process.stdout.write(JSON.stringify({packets, nativeMailCalls, nativeMailAcks, nativeMailClears, nativeOtherCalls, nativeBaguaFactories, retained, released, snapshotCalls, mailSteps, notifications, reports,
    diskWrites, healthy: store.healthy(), stored: JSON.parse(store.text()), persisted: JSON.parse(persisted ?? diskText),
    role: JSON.parse(store.roleResponse()), afterReload})); process.exit(0);
}
if (input.recoveryRuns) {""")
    return script.replace("._offline_mock_mail?.phase", "[input.petMailWire ? '_offline_mock_pet' : input.baguaWire ? '_offline_mock_bagua' : '_offline_mock_mail']?.phase")


NODE_MAIL_CHECK = mail_harness()
NODE_PILL_CHECK = NODE_MAIL_CHECK.replace(
    "let store = input.nativeStore",
    "const initialProfile = parseValue(diskText); initialProfile._offline_mock_bagua = parseValue(" + json.dumps(json.dumps(BAGUA_RECEIPT)) + "); diskText = JSON.stringify(initialProfile);\nlet store = input.nativeStore",
)


def run(run_production_js, **overrides):
    return run_production_js(NODE_PILL_CHECK, {
        "nativeStore": True, "nativePoint": "71", "mailWire": True,
        "listRequest": copy.deepcopy(LIST), "claimRequest": copy.deepcopy(CLAIM),
        "nativeBagBefore": copy.deepcopy(BEFORE), "nativeBagAfter": copy.deepcopy(AFTER), **overrides,
    })


def body(result, index):
    return next((entry["body"] for entry in result["packets"][index]["writes"] if "body" in entry), None)


def test_mock_mail_list_is_explicit_fixed_and_does_not_grant_items(run_production_js):
    result = run(run_production_js, listOnly=True, reloadMail=True)
    response = json.loads(body(result, 0))
    mail = response["mails"][0]
    assert mail["id"] == str(MAIL_ID) and mail["title"].startswith("[Mock]") and mail["from"].startswith("[Mock]")
    assert mail["reward"] == [{"A2": 504100, "A4": 1}] and mail["mtype"] == mail["type"] == mail["is_user"] == 0
    assert 0 <= mail["dateline"] < mail["expired"] <= 0x7FFFFFFF
    assert response == result["afterReload"] and result["diskWrites"] == 1 and result["nativeMailCalls"] == 0
    assert result["stored"]["bag"] == {"spiritcount": 2000}
    assert "_offline_mock_mail" not in result["role"]["savedata"]


def test_mail_uses_native_grant_and_commits_before_ack_clear_and_go_on(run_production_js):
    result = run(run_production_js, repeatMail=True, repeatMailRequest=True, reloadMail=True)
    response = json.loads(body(result, 1))
    assert response == {"code": 1000, "point": 71, "reward": [{"A2": 504100, "A4": 1}], "mails": [], "offset": 0, "total_page_num": 1}
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 1
    assert result["mailSteps"] == [{"kind": "reward", "phase": "claiming"}, {"kind": "ack", "phase": "committed"}, {"kind": "clear", "phase": "committed"}]
    assert result["notifications"] == [{"name": "GO_ON", "phase": "committed"}] * 2
    assert result["stored"] == result["persisted"] and result["stored"]["bag"] == AFTER
    assert result["stored"]["point"] == 71 and result["stored"]["_offline_mock_mail"]["phase"] == "committed"
    assert result["afterReload"]["mails"] == [] and json.loads(body(result, 2))["code"] == -1
    assert any(event["event"] == "offline-mock-mail-replay-blocked" for event in result["reports"])


@pytest.mark.parametrize("list_request", [
    {**LIST, "rid": "10001"}, {**LIST, "rid": 10002}, {**LIST, "owner_type": 0},
    {**LIST, "offset": 1}, {**LIST, "offset": "0"}, {**LIST, "type": 3},
])
def test_invalid_mail_list_never_creates_receipt(run_production_js, list_request):
    result = run(run_production_js, listRequest=list_request, listOnly=True)
    assert body(result, 0) is None and result["diskWrites"] == 0
    assert "_offline_mock_mail" not in result["stored"]


@pytest.mark.parametrize("list_request", [{**LIST, "owner_type": 1}, {"rid": 10001, "type": 1, "offset": 0}])
def test_other_native_mail_categories_are_empty_without_issuing_the_gift(run_production_js, list_request):
    result = run(run_production_js, listRequest=list_request, listOnly=True)
    assert json.loads(body(result, 0))["mails"] == [] and result["diskWrites"] == 0


@pytest.mark.parametrize("field,value", [
    ("rid", 10001), ("rid", "10002"), ("id", str(MAIL_ID)), ("id", MAIL_ID + 1),
    ("type", 2), ("mtype", 1), ("mtype", False), ("is_user", 1), ("is_user", False), ("offset", 1),
])
def test_claim_identity_and_types_are_strict(run_production_js, field, value):
    result = run(run_production_js, claimRequest={**CLAIM, field: value})
    assert body(result, 1) is None and result["nativeMailCalls"] == 0
    assert result["stored"]["_offline_mock_mail"]["phase"] == "offered" and result["diskWrites"] == 1


@pytest.mark.parametrize("condition", [
    {"omitSavedata": True}, {"claimSavedata": {"unknown": {}}}, {"failWriteAt": 2},
    {"mismatchMailBody": True}, {"mailUserdata": MAIL_ID + 1}, {"badMailVtable": True},
])
def test_unprepared_or_wrong_response_never_reaches_native_grant(run_production_js, condition):
    result = run(run_production_js, **condition)
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 0
    if "omitSavedata" in condition or "claimSavedata" in condition or "failWriteAt" in condition:
        assert json.loads(body(result, 1))["code"] == -1
        assert "reward" not in json.loads(body(result, 1))
        assert result["notifications"] == [{"name": "GO_ON", "phase": "offered"}]
    else:
        assert result["notifications"] == []


@pytest.mark.parametrize("condition", [
    {"legacyMailSender": True}, {"mailCaller": 0x2AF36DC}, {"nullMailRequest": True}, {"wrongRawRequest": True},
])
def test_mail_preparation_requires_original_constructor_caller_and_returned_request(run_production_js, condition):
    result = run(run_production_js, **condition)
    assert body(result, 0) is None and body(result, 1) is None
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 0
    assert result["notifications"] == []


@pytest.mark.parametrize("offset", [0x2AB9290, 0x2AB9294])
def test_mail_request_constructor_fingerprint_must_match(run_production_js, offset):
    result = run(run_production_js, badFingerprint=offset)
    assert result["configurationError"] == "Mock mail request entry fingerprint mismatch"


@pytest.mark.parametrize("condition", [
    {"nativeBagAfter": BEFORE}, {"nativeBagAfter": {"spiritcount": 2080, "item": [{"A2": 504100, "A4": 6}]}},
    {"nativePointAfter": "72"}, {"snapshotFailAt": 2}, {"failWriteAt": 3},
])
def test_failed_post_grant_snapshot_never_acknowledges_or_clears_dirty(run_production_js, condition):
    result = run(run_production_js, repeatMail=True, **condition)
    assert result["nativeMailCalls"] == 1 and result["nativeMailAcks"] == result["nativeMailClears"] == 0
    assert not result["healthy"] and result["notifications"] == []
    assert result["stored"] == result["persisted"] and result["stored"]["bag"] == BEFORE
    assert result["stored"]["_offline_mock_mail"]["phase"] == "claiming"


@pytest.mark.parametrize("interrupt", [{"noDeliver": True}, {"failWriteAt": 3}])
def test_claiming_cold_restart_keeps_same_mail_and_grants_only_on_successful_retry(run_production_js, interrupt):
    interrupted = run(run_production_js, **interrupt)
    saved = interrupted["persisted"]
    assert saved["_offline_mock_mail"]["phase"] == "claiming" and saved["bag"] == BEFORE
    recovered = run(run_production_js, baseline=saved, reloadMail=True)
    assert recovered["nativeMailCalls"] == 1 and recovered["stored"]["bag"] == AFTER
    assert recovered["stored"]["_offline_mock_mail"]["reward"] == saved["_offline_mock_mail"]["reward"]
    assert recovered["afterReload"]["mails"] == []
    completed = run(run_production_js, baseline=recovered["persisted"])
    assert completed["nativeMailCalls"] == 0 and json.loads(body(completed, 1))["code"] == -1
    assert completed["stored"]["bag"] == AFTER


def test_renamed_commit_survives_directory_sync_failure_without_reissuing_mail(run_production_js):
    interrupted = run(run_production_js, failDirectorySyncAt=3, repeatMail=True)
    assert not interrupted["healthy"] and interrupted["nativeMailCalls"] == 1
    assert interrupted["nativeMailAcks"] == interrupted["nativeMailClears"] == 0 and interrupted["notifications"] == []
    assert interrupted["stored"]["_offline_mock_mail"]["phase"] == "claiming"
    assert interrupted["persisted"]["_offline_mock_mail"]["phase"] == "committed"
    assert interrupted["persisted"]["bag"] == AFTER
    restarted = run(run_production_js, baseline=interrupted["persisted"])
    assert restarted["nativeMailCalls"] == 0 and json.loads(body(restarted, 0))["mails"] == []
    assert restarted["stored"]["bag"] == AFTER


def test_shared_native_handlers_pass_through_unrelated_calls(run_production_js):
    result = run(run_production_js, listOnly=True, unrelatedNativeCalls=True)
    assert result["nativeOtherCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 1
    assert result["nativeMailCalls"] == 0 and result["diskWrites"] == 1 and result["healthy"]
    assert result["stored"]["_offline_mock_mail"]["phase"] == "offered"
    assert result["notifications"] == [{"name": "GO_ON", "phase": "offered"}]


@pytest.mark.parametrize("offset", [0x2AFBA4C, 0x2AFBA50, 0x2FE924C, 0x2FE9250, 0x2FEA720, 0x2FEA724])
def test_mail_native_entry_fingerprint_mismatch_refuses_configuration(run_production_js, offset):
    result = run(run_production_js, badFingerprint=offset)
    assert result["configurationError"] == "Mock mail native entry fingerprint mismatch"


@pytest.mark.parametrize("change", [
    {"version": 2}, {"id": MAIL_ID + 1}, {"rid": "10001"}, {"phase": "unknown"},
    {"reward": [{"A2": 504101, "A4": 1}]}, {"reward": [{"A2": 504100, "A4": 2}]},
    {"reward": [{"A2": 504100, "A4": 1, "A5": 1}]}, {"expired": 0}, {"unexpected": True},
])
def test_bad_existing_receipt_is_rejected_without_reissuing_mail(run_production_js, change):
    receipt = {"version": 1, "rid": 10001, "id": MAIL_ID, "phase": "claiming", "dateline": 1,
               "expired": 2000000000, "reward": [{"A2": 504100, "A4": 1}], **change}
    baseline = {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 6}}, "point": 71, "bag": BEFORE, "_offline_mock_mail": receipt}
    result = run(run_production_js, baseline=baseline)
    assert body(result, 0) is None and json.loads(body(result, 1))["code"] == -1
    assert "reward" not in json.loads(body(result, 1))
    assert result["notifications"] == [{"name": "GO_ON", "phase": None}]
    assert result["stored"] == {**baseline, "_offline_mock_bagua": BAGUA_RECEIPT, "_offline_mock_pet": PET_RECEIPT} and result["diskWrites"] == result["nativeMailCalls"] == 0


def test_mail_preserves_other_modules_and_existing_lottery_receipt(run_production_js):
    lottery = {"version": 1, "round": 5, "phase": "committed", "levelid": 700003,
               "removed": [1, 2, 3], "reward": [{"A2": 502211, "A4": 1}]}
    baseline = {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 6}}, "point": 71, "bag": BEFORE,
                "pet": {"petinfo": [{"petid": 4399, "dataid": 210}]}, "mire": {"storytask": []}, "_offline_lottery": lottery}
    result = run(run_production_js, baseline=baseline)
    assert result["stored"]["_offline_lottery"] == lottery
    for key in ("roledata", "pet", "mire", "point"):
        assert result["stored"][key] == baseline[key]


def test_mail_point_response_preserves_native_int64_text(run_production_js):
    result = run(run_production_js, nativePoint="9007199254740993", listOnly=True)
    assert '"point":9007199254740993' in body(result, 0)


@pytest.mark.parametrize("condition", [{"noBaseline": True}, {"failWriteAt": 1}])
def test_mail_never_appears_before_its_initial_receipt_is_durable(run_production_js, condition):
    # 无 baseline 时通用替身的输出也不能读取 store.text()，直接检查 raw 路由。
    if condition.get("noBaseline"):
        script = NODE_MAIL_CHECK.replace("JSON.parse(store.text())", "store.exists() ? JSON.parse(store.text()) : null").replace("JSON.parse(store.roleResponse())", "store.exists() ? JSON.parse(store.roleResponse()) : null")
        result = run_production_js(script, {"nativeStore": True, "nativePoint": "71", "mailWire": True, "listRequest": LIST, "listOnly": True, **condition})
    else:
        result = run(run_production_js, listOnly=True, **condition)
    assert body(result, 0) is None and result["nativeMailCalls"] == 0


@pytest.mark.parametrize("failure", [{"failWriteAt": 2}, {"failSyncAt": 2}])
def test_pre_grant_storage_failure_finishes_ui_without_grant_or_attachment_loss(run_production_js, failure):
    baseline = {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 90}}, "point": 71, "bag": BEFORE}
    result = run(run_production_js, baseline=baseline, repeatMail=True, **failure)
    error = json.loads(body(result, 1))
    assert error["code"] == -1 and "reward" not in error
    assert result["healthy"] and result["stored"] == result["persisted"]
    assert result["stored"]["bag"] == BEFORE and result["stored"]["point"] == 71
    assert result["stored"]["_offline_mock_mail"]["phase"] == "offered"
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 0
    assert result["notifications"] == [{"name": "GO_ON", "phase": "offered"}]
    assert any(event["event"] == "offline-mock-mail-storage-retryable" for event in result["reports"])


@pytest.mark.parametrize("failure", [{"failWriteAt": 2}, {"failSyncAt": 2}])
def test_same_process_retry_after_storage_failure_grants_exactly_once(run_production_js, failure):
    result = run(run_production_js, retryMail=True, repeatMail=True, reloadMail=True, **failure)
    assert json.loads(body(result, 1))["code"] == -1
    assert json.loads(body(result, 2))["code"] == 1000
    assert result["healthy"] and result["nativeMailCalls"] == 1
    assert result["nativeMailAcks"] == result["nativeMailClears"] == 1
    assert result["stored"] == result["persisted"] and result["stored"]["bag"] == AFTER
    assert result["stored"]["_offline_mock_mail"]["phase"] == "committed"
    assert result["afterReload"]["mails"] == []
    assert [event["phase"] for event in result["notifications"]] == ["offered", "committed", "committed"]


def test_timeout_before_native_delivery_can_retry_same_process_without_duplicate_grant(run_production_js):
    result = run(run_production_js, noDeliver=True, retryMail=True, repeatMail=True, lateFirstMail=True)
    assert json.loads(body(result, 1))["code"] == json.loads(body(result, 2))["code"] == 1000
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 1
    assert result["stored"] == result["persisted"] and result["stored"]["bag"] == AFTER
    assert result["stored"]["_offline_mock_mail"]["phase"] == "committed"


def test_changed_main_file_cannot_unlock_failed_storage_for_retry(run_production_js):
    changed = {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 90}}, "point": 72, "bag": BEFORE}
    result = run(run_production_js, failSyncAt=2, changedDiskOnRetry=changed, retryMail=True)
    assert not result["healthy"] and result["nativeMailCalls"] == 0
    assert not any(event["event"] == "offline-mock-mail-storage-retryable" for event in result["reports"])
    assert result["stored"]["_offline_mock_mail"]["phase"] == "offered"
    assert all(json.loads(body(result, index))["code"] == -1 for index in (1, 2))


def test_pre_grant_rename_directory_sync_failure_stays_blocked(run_production_js):
    result = run(run_production_js, failDirectorySyncAt=2, retryMail=True)
    assert not result["healthy"] and result["nativeMailCalls"] == 0
    assert result["stored"]["_offline_mock_mail"]["phase"] == "offered"
    assert result["persisted"]["_offline_mock_mail"]["phase"] == "claiming"
    assert result["persisted"]["bag"] == BEFORE
    assert not any(event["event"] == "offline-mock-mail-storage-retryable" for event in result["reports"])


@pytest.mark.parametrize("storage_error", [{"failDirectorySyncAt": 2}, {"failWriteAt": 3}])
def test_globally_blocked_other_valid_mail_ends_loading_without_native_retry(run_production_js, storage_error):
    result = run(run_production_js, retryMail=True, retryMailId=BAGUA_ID, repeatMail=True, **storage_error)
    assert not result["healthy"]
    response = json.loads(body(result, 2))
    assert response["code"] == -1 and response["offline_mail_id"] == BAGUA_ID and "reward" not in response
    assert result["nativeMailCalls"] == (1 if "failWriteAt" in storage_error else 0)
    assert result["nativeMailAcks"] == result["nativeMailClears"] == 0
    assert result["stored"]["bag"] != AFTER
    endings = [event for event in result["reports"] if event["event"] == "offline-mock-mail-failure-finished"]
    assert len([event for event in endings if event["id"] == BAGUA_ID]) == 1
    assert all(not event["retryable"] for event in endings)


def test_invalid_mail_identity_under_storage_block_never_enters_grant_or_error_delivery(run_production_js):
    result = run(run_production_js, failDirectorySyncAt=2, retryMail=True, retryMailId=MAIL_ID + 1)
    assert not result["healthy"] and body(result, 2) is None
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 0
    assert not any(event["event"] == "offline-mock-mail-failure-finished" and event["id"] == MAIL_ID + 1 for event in result["reports"])
