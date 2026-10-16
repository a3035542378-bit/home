"""原生产八卦邮件与固定实例事务；工厂/serializer 替身不证明真实属性公式。"""

import copy
import json

import pytest

from test_offline_bridge import run_production_js
from test_offline_mock_mail import BAGUA_ID, BAGUA_ITEM, CLAIM, LIST, MAIL_ID, NODE_MAIL_CHECK, body


PILL_RECEIPT = {"version": 1, "rid": 10001, "id": MAIL_ID, "phase": "committed",
                "dateline": 1, "expired": 2000000000, "reward": [{"A2": 504100, "A4": 1}]}
BEFORE = {"spiritcount": 17145, "maxglobalitemid": 4406, "item": [{"A2": 504100, "A4": 1}]}
RESERVED = {**BEFORE, "maxglobalitemid": 4407}
AFTER = {**RESERVED, "item": [*BEFORE["item"], BAGUA_ITEM]}


def run(run_production_js, **changes):
    baseline = {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 7}},
                "point": 0, "bag": BEFORE, "_offline_mock_mail": PILL_RECEIPT,
                "pet": {"petinfo": [{"petid": 4399, "dataid": 210, "tamestate": 1}]}}
    values = {"nativeStore": True, "mailWire": True, "baguaWire": True, "nativePoint": "0",
              "baseline": baseline, "listRequest": LIST, "claimRequest": {**CLAIM, "id": BAGUA_ID},
              "nativeBagBefore": BEFORE, "nativeBagReserved": RESERVED, "nativeBagAfter": AFTER,
              "nativeBaguaItem": BAGUA_ITEM}
    return run_production_js(NODE_MAIL_CHECK, copy.deepcopy({**values, **changes}))


def test_original_factory_instance_and_allocator_are_saved_before_list_without_award(run_production_js):
    result = run(run_production_js, listOnly=True, reloadMail=True)
    response = json.loads(body(result, 0))
    assert len(response["mails"]) == 1 and response["mails"][0]["id"] == str(BAGUA_ID)
    assert response["mails"][0]["title"].startswith("[Mock]")
    assert response["mails"][0]["reward"] == [BAGUA_ITEM]
    assert result["nativeBaguaFactories"] == 2 and result["nativeMailCalls"] == 0
    assert result["diskWrites"] == 1 and result["stored"] == result["persisted"]
    assert result["stored"]["bag"] == RESERVED and result["afterReload"] == response
    assert result["stored"]["_offline_mock_mail"] == PILL_RECEIPT
    assert result["stored"]["_offline_mock_bagua"]["phase"] == "offered"
    assert "_offline_mock_bagua" not in result["role"]["savedata"]
    assert len(result["retained"]) == 2 and result["released"] == list(reversed(result["retained"]))


def test_fixed_bagua_claim_commits_native_full_item_once_and_survives_restart(run_production_js):
    result = run(run_production_js, repeatMail=True, repeatMailRequest=True, reloadMail=True)
    assert result["healthy"] and result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 1
    assert result["mailSteps"] == [{"kind": "reward", "phase": "claiming"}, {"kind": "ack", "phase": "committed"}, {"kind": "clear", "phase": "committed"}]
    assert result["stored"]["bag"] == AFTER and result["stored"]["_offline_mock_mail"] == PILL_RECEIPT
    assert result["stored"]["_offline_mock_bagua"]["reward"] == [BAGUA_ITEM]
    assert result["stored"]["_offline_mock_bagua"]["phase"] == "committed" and result["afterReload"]["mails"] == []
    restarted = run(run_production_js, baseline=result["persisted"], nativeBagBefore=AFTER)
    assert restarted["nativeBaguaFactories"] == restarted["nativeMailCalls"] == 0 and restarted["stored"] == result["persisted"]


@pytest.mark.parametrize("conditions", [
    {"factoryNull": True}, {"castNull": True}, {"badBaguaType": True},
    {"roundtripChange": {"A7": 92}}, {"roundtripChange": {"UNIRID": 100010002}},
    {"nativeBaguaItem": {**BAGUA_ITEM, "A5": 0}}, {"nativeBaguaItem": {**BAGUA_ITEM, "A5": 4405}},
    {"nativeBagReserved": BEFORE},
    {"nativeBagReserved": {**RESERVED, "spiritcount": 17146}},
    {"failWriteAt": 1},
])
def test_unstable_or_unreserved_native_instance_is_not_shown_or_acknowledged(run_production_js, conditions):
    result = run(run_production_js, **conditions)
    assert body(result, 0) is None and json.loads(body(result, 1))["code"] == -1
    assert "reward" not in json.loads(body(result, 1))
    assert result["notifications"] == [{"name": "GO_ON", "phase": None}]
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 0 and not result["healthy"]
    assert "_offline_mock_bagua" not in result["stored"]
    assert result["stored"]["bag"] == BEFORE and result["stored"]["_offline_mock_mail"] == PILL_RECEIPT


@pytest.mark.parametrize("after", [
    RESERVED,
    {**AFTER, "item": [*BEFORE["item"], {**BAGUA_ITEM, "A7": 92}]},
    {**AFTER, "item": [*BEFORE["item"], {**BAGUA_ITEM, "A5": 4407}]},
    {**AFTER, "item": [*BEFORE["item"], BAGUA_ITEM, BAGUA_ITEM]},
    {**AFTER, "itemlimit": [BAGUA_ITEM]},
    {**AFTER, "maxglobalitemid": 4406},
])
def test_claim_requires_exact_native_properties_one_instance_and_reserved_watermark(run_production_js, after):
    result = run(run_production_js, nativeBagAfter=after, repeatMail=True)
    assert result["nativeMailCalls"] == 1 and not result["healthy"]
    assert result["nativeMailAcks"] == result["nativeMailClears"] == 0 and result["notifications"] == []
    assert result["stored"]["_offline_mock_bagua"]["phase"] == "claiming"
    assert result["stored"]["_offline_mock_mail"] == PILL_RECEIPT


@pytest.mark.parametrize("interrupted", [{"noDeliver": True}, {"failWriteAt": 3}])
def test_interrupted_bagua_claim_reuses_fixed_instance_without_reroll(run_production_js, interrupted):
    first = run(run_production_js, **interrupted)
    assert first["persisted"]["_offline_mock_bagua"]["phase"] == "claiming"
    resumed = run(run_production_js, baseline=first["persisted"], nativeBagBefore=RESERVED)
    assert resumed["nativeBaguaFactories"] == 0 and resumed["nativeMailCalls"] == 1
    assert resumed["stored"]["_offline_mock_bagua"]["reward"] == [BAGUA_ITEM]
    assert resumed["stored"]["bag"] == AFTER and resumed["healthy"]


@pytest.mark.parametrize("address", [0x3C85CAC, 0x3C85CB0, 0x3D293B8, 0x3D293BC])
def test_bagua_native_serializer_and_json_array_fingerprints_are_required(run_production_js, address):
    result = run(run_production_js, badFingerprint=address)
    assert result["configurationError"] == "Mock bagua native entry fingerprint mismatch"
