from pathlib import Path
import re

import pytest

from debug_true_spirit_entry import DEBUG, INSTALL, MARKER, build_debug_script


def test_debug_entry_keeps_production_source_and_requires_explicit_trigger():
    source = Path(__file__).with_name("offline_bridge.js").read_text()
    result = build_debug_script(source)
    assert result.removeprefix(DEBUG).replace(
        MARKER + INSTALL, MARKER, 1
    ) == source
    assert "entry.readU32()!==0xd10043ff" in result
    assert "entry.add(4).readU32()!==0xa9007bf3" in result
    assert "game.base.add(0x5fd87c0)" in result
    assert result.index("if(access(trigger,0)!==0)return;") < result.index("construct(layer);")
    assert result.index("scene.readPointer().equals(game.base.add(0x67086e0))") < result.index("if(access(trigger,0)!==0)return;")
    assert result.index("if(unlink(trigger)!==0)") < result.index("construct(layer);")
    assert "true_spirit_bag" not in DEBUG
    assert DEBUG.index("if(access(grant,0)===0)") < DEBUG.index("!add(bag,item,bag,0,1,0)")
    assert "add(bag,value" not in DEBUG
    assert "for(const id of [503344,503345,503346,503347])" in DEBUG
    assert result.index("configureRoleWire(game,offlineStore,isPreparedPetRequest);") < result.index(INSTALL)


@pytest.mark.parametrize("source", ["", MARKER * 2, MARKER + "configureDebugTrueSpiritEntry"])
def test_reject_ambiguous_or_already_debug_source(source):
    with pytest.raises(ValueError):
        build_debug_script(source)


def test_debug_exports_exist_in_actual_arm64_library():
    library = Path(__file__).resolve().parents[2] / "artifacts/zmxol-offline/squad-build/libgame.so"
    if not library.is_file():
        pytest.skip("Actual restored ARM64 library required")
    raw = library.read_bytes()
    for symbol in re.findall(r"game.getExportByName\('([^']+)'\)", DEBUG):
        assert symbol.encode() + b"\0" in raw, symbol
