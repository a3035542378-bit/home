import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from debug_mock_mail import MAILS, prepare_mail, run


def profile():
    value = {"roledata": {"player": {"level": 90, "completeguide": [900023]}},
             "pet": {"pets": [{"tid": 252, "level": 60}, {"tid": 210, "level": 1}]},
             "bag": {"item": [{"A2": 504100, "A4": 1}]}, "point": 0,
             "_offline_lottery": {"phase": "drawn"}}
    for _, (mail_id, key) in MAILS.items():
        value[key] = {"version": 1, "rid": 10001, "id": mail_id, "phase": "committed"}
    return value


@pytest.mark.parametrize("kind", MAILS)
def test_unique_debug_mail_added_and_formal_receipt_preserved(kind):
    original = profile()
    before = copy.deepcopy(original)
    output = prepare_mail(original, kind)
    expected = copy.deepcopy(before)
    expected["_offline_debug_mail_900600000"] = {"version": 1, "rid": 10001, "id": 900600000, "kind": kind, "phase": "requested"}
    assert output == expected
    assert original == before
    assert output["roledata"]["player"]["level"] == 90
    assert output["pet"] == before["pet"]
    assert output["bag"] == before["bag"]


@pytest.mark.parametrize("phase", ["offered", "claiming", "unknown"])
def test_pending_rewards_cannot_be_reissued(phase):
    value = profile()
    value[MAILS["pet"][1]]["phase"] = phase
    with pytest.raises(ValueError, match="committed"):
        prepare_mail(value, "pet")


@pytest.mark.parametrize("field,new", [("id", 1), ("rid", 10002), ("version", 2)])
def test_wrong_receipt_rejected(field, new):
    value = profile()
    value[MAILS["pet"][1]][field] = new
    with pytest.raises(ValueError):
        prepare_mail(value, "pet")


def test_missing_receipt_is_already_ready():
    value = profile()
    del value[MAILS["pet"][1]]
    assert prepare_mail(value, "pet") == value


@pytest.mark.parametrize("value,kind", [({}, "pet"), ([], "pet"), (profile(), "all")])
def test_invalid_profile_or_kind_rejected(value, kind):
    with pytest.raises(ValueError):
        prepare_mail(value, kind)


def test_local_dry_run_does_not_use_adb_or_modify_file(tmp_path, capsys):
    path = tmp_path / "save.json"
    source = json.dumps(profile()).encode()
    path.write_bytes(source)
    args = SimpleNamespace(serial="emulator-5576", input=str(path), dry_run=True,
                           kind="pet", adb="/nonexistent-adb")
    asyncio.run(run(args))
    assert json.loads(capsys.readouterr().out)["other_fields_unchanged"] is True
    assert path.read_bytes() == source


@pytest.mark.parametrize("serial", ["x;rm", "$(id)", "", "x\ny"])
def test_unsafe_serial_rejected_before_adb(serial):
    args = SimpleNamespace(serial=serial)
    with pytest.raises(ValueError, match="serial"):
        asyncio.run(run(args))


def test_keys_match_production_source():
    source = Path(__file__).with_name("offline_bridge.js").read_text()
    for _, (mail_id, key) in MAILS.items():
        assert str(mail_id) in source
        assert f"Memory.allocUtf8String('{key}')" in source


def test_subsequent_debug_mail_has_new_id_and_preserves_committed_history():
    value = prepare_mail(profile(), "pet")
    value["_offline_debug_mail_900600000"]["phase"] = "committed"
    output = prepare_mail(value, "pet")
    assert output["_offline_debug_mail_900600001"]["id"] == 900600001
    assert all(output[key] == receipt for key, receipt in value.items())


@pytest.mark.parametrize("phase", ["requested", "offered", "claiming"])
def test_existing_pending_debug_mail_rejected(phase):
    value = prepare_mail(profile(), "pet")
    value["_offline_debug_mail_900600000"]["phase"] = phase
    with pytest.raises(ValueError, match="pending"):
        prepare_mail(value, "pill")


def test_debug_id_overflow_rejected():
    value = profile()
    value["_offline_debug_mail_2147483647"] = {"version": 1, "rid": 10001, "id": 2147483647, "kind": "pet", "phase": "committed"}
    with pytest.raises(ValueError, match="exhausted"):
        prepare_mail(value, "pet")
