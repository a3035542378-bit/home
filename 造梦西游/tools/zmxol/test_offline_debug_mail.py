"""独立调试邮件：生产原事务的替身回归，不代表安卓真实领取。"""

import json
import pytest
from test_offline_bridge import run_production_js

from test_offline_mock_mail import (BAGUA_RECEIPT, PET_RECEIPT, BEFORE, AFTER, CLAIM,
                                   body, run as run_pill)
from test_offline_mock_bagua import PILL_RECEIPT, run as run_bagua
from test_offline_mock_pet_mail import BEFORE as PET_BEFORE, AFTER as PET_AFTER, BAG, run as run_pet

DEBUG_ID = 900600000
DEBUG_KEY = f"_offline_debug_mail_{DEBUG_ID}"


def baseline(kind):
    return {"roledata": {"player": {"roleid": 1, "completeguide": [900023]}, "role": {"rolelv": 90}},
            "point": 0, "bag": BAG if kind == "pet" else BEFORE,
            "pet": PET_BEFORE, "_offline_mock_mail": PILL_RECEIPT,
            "_offline_mock_bagua": BAGUA_RECEIPT, "_offline_mock_pet": PET_RECEIPT,
            DEBUG_KEY: {"version": 1, "rid": 10001, "id": DEBUG_ID, "kind": kind, "phase": "requested"}}


@pytest.mark.parametrize("kind,runner", [("pill", run_pill), ("bagua", run_bagua), ("pet", run_pet)])
def test_debug_preview_uses_its_own_receipt_and_preserves_formal_mail(run_production_js, kind, runner):
    source = baseline(kind)
    if kind == "bagua":
        source["bag"] = {"spiritcount": 17145, "maxglobalitemid": 4407, "item": []}
        # 已存在正式八卦附件4406；原工厂必须分配全新4407。
        from test_offline_mock_mail import BAGUA_ITEM
        options = {"nativeBaguaItem": {**BAGUA_ITEM, "A5": 4407},
                   "nativeBagBefore": source["bag"], "nativeBagReserved": {**source["bag"], "maxglobalitemid": 4408}}
    else:
        options = {}
    result = runner(run_production_js, baseline=source, listOnly=True, **options)
    assert result["healthy"]
    mail = json.loads(body(result, 0))["mails"]
    assert len(mail) == 1 and mail[0]["id"] == str(DEBUG_ID)
    assert result["stored"][DEBUG_KEY]["phase"] == "offered"
    for key in ("_offline_mock_mail", "_offline_mock_bagua", "_offline_mock_pet"):
        assert result["stored"][key] == source[key]
    assert DEBUG_KEY not in result["role"]["savedata"]
    assert result["nativeMailCalls"] == 0
    assert result["stored"]["roledata"] == source["roledata"]
    assert result["stored"]["pet"] == source["pet"]


@pytest.mark.parametrize("kind,runner", [("pill", run_pill), ("pet", run_pet)])
def test_debug_grant_once_replay_and_cold_restart_keep_formal_receipts(run_production_js, kind, runner):
    source = baseline(kind)
    options = {"nativeBagBefore": source["bag"], "nativeBagAfter": source["bag"] if kind == "pet" else AFTER}
    result = runner(run_production_js, baseline=source, claimRequest={**CLAIM, "id": DEBUG_ID},
                    repeatMail=True, repeatMailRequest=True, reloadMail=True, **options)
    assert result["healthy"]
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 1
    assert result["stored"][DEBUG_KEY]["phase"] == "committed"
    assert result["afterReload"]["mails"] == []
    for key in ("_offline_mock_mail", "_offline_mock_bagua", "_offline_mock_pet"):
        assert result["stored"][key] == source[key]
    expected_pet = PET_AFTER if kind == "pet" else source["pet"]
    assert result["stored"]["pet"] == expected_pet
    restart = runner(run_production_js, baseline=result["persisted"], listOnly=True,
                     nativeBagBefore=result["stored"]["bag"], nativePetBefore=expected_pet)
    assert restart["nativeMailCalls"] == 0
    assert json.loads(body(restart, 0))["mails"] == []


@pytest.mark.parametrize("field,value", [("kind", "unknown"), ("id", DEBUG_ID + 1), ("version", 2), ("reward", [])])
def test_invalid_debug_record_never_delivers(run_production_js, field, value):
    source = baseline("pill")
    source[DEBUG_KEY][field] = value
    result = run_pill(run_production_js, baseline=source, listOnly=True)
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 0
    assert result["persisted"] == source
    assert body(result, 0) is None


def test_unknown_debug_id_cannot_be_claimed_without_receipt(run_production_js):
    source = baseline("pill")
    del source[DEBUG_KEY]
    result = run_pill(run_production_js, baseline=source, claimRequest={**CLAIM, "id": DEBUG_ID})
    assert result["nativeMailCalls"] == 0
    assert result["persisted"] == source


def test_debug_bagua_native_reserved_id_grant_and_replay(run_production_js):
    from test_offline_mock_mail import BAGUA_ITEM
    source = baseline("bagua")
    source["bag"] = {"spiritcount": 17145, "maxglobalitemid": 4407, "item": []}
    reserved = {**source["bag"], "maxglobalitemid": 4408}
    item = {**BAGUA_ITEM, "A5": 4407}
    after = {**reserved, "item": [item]}
    result = run_bagua(run_production_js, baseline=source, nativeBagBefore=source["bag"],
                       nativeBagReserved=reserved, nativeBagAfter=after, nativeBaguaItem=item,
                       claimRequest={**CLAIM, "id": DEBUG_ID}, repeatMail=True, reloadMail=True)
    assert result["healthy"]
    assert result["nativeMailCalls"] == result["nativeMailAcks"] == result["nativeMailClears"] == 1
    assert result["stored"]["bag"] == after
    assert result["stored"][DEBUG_KEY]["reward"] == [item]
    assert result["stored"][DEBUG_KEY]["phase"] == "committed"
    assert result["stored"]["_offline_mock_bagua"] == BAGUA_RECEIPT
    assert result["afterReload"]["mails"] == []
    cold = run_bagua(run_production_js, baseline=result["persisted"], listOnly=True, nativeBagBefore=after)
    assert cold["nativeBaguaFactories"] == cold["nativeMailCalls"] == 0


@pytest.mark.parametrize("kind,runner", [("pill", run_pill), ("pet", run_pet)])
def test_debug_claiming_cold_restart_retries_same_fixed_reward_once(run_production_js, kind, runner):
    source = baseline(kind)
    options = {"nativeBagBefore": source["bag"], "nativeBagAfter": source["bag"] if kind == "pet" else AFTER}
    interrupted = runner(run_production_js, baseline=source, claimRequest={**CLAIM, "id": DEBUG_ID}, noDeliver=True, **options)
    pending = interrupted["persisted"]
    assert pending[DEBUG_KEY]["phase"] == "claiming"
    assert pending["bag"] == source["bag"] and pending["pet"] == source["pet"]
    recovered = runner(run_production_js, baseline=pending, claimRequest={**CLAIM, "id": DEBUG_ID}, repeatMail=True, **options)
    assert recovered["healthy"] and recovered["nativeMailCalls"] == 1
    assert recovered["stored"][DEBUG_KEY]["reward"] == pending[DEBUG_KEY]["reward"]
    assert recovered["stored"][DEBUG_KEY]["phase"] == "committed"
    for key in ("_offline_mock_mail", "_offline_mock_bagua", "_offline_mock_pet"):
        assert recovered["stored"][key] == source[key]
