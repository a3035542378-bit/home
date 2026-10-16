"""生成限定测试档的固定结果融合实验桥；不修改生产源或输入存档。"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path

from debug_true_spirit_entry import build_debug_script


# shortcut: 仅固定派生测试档；推广正式、多次或多角色融合时须恢复通用分配与原规则。
SOURCE_SHA256 = "50bf21c36cf0ac6bce7a30297ec35d9df981c1aeafcfa4d7e012bad6dda8d95c"
FIELDS = set("exp level skill iselite triones globalid opbasehp opbasemp spiritid basepetid bonelevel hpimprove mpimprove opbasedef opbasestr petequips tamestate defimprove mastername strimprove spiritpower talentskill opskilllevel passiveskill comprehension sageskilllevel opsageskilllevel sageskillposition tabooextraskilllevel".split())


def build_fusion_script(source: str, profile: dict, template: dict, *, experimental: bool = False) -> str:
    if not experimental:
        raise ValueError("Explicit experimental fixed-result mode required")
    if hashlib.sha256(source.encode()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Production bridge changed; reverify integration points")
    if profile.get("roledata", {}).get("player", {}).get("roleid") != 1:
        raise ValueError("Only isolated role 1 is supported")
    if "_DEBUG_ONLY_fusion" in profile or "true_spirit_bag" in profile:
        raise ValueError("Existing fusion state requires recovery, not another experiment")
    pets = profile.get("pet", {}).get("petinfo", [])
    ids = [p.get("petid") for p in pets]
    if any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids) or 4407 in ids:
        raise ValueError("Invalid isolated pet identities")
    for pet_id, data_id, level in ((4405, 221, 75), (4406, 229, 60)):
        rows = [p for p in pets if p["petid"] == pet_id]
        if len(rows) != 1 or rows[0].get("dataid") != data_id or rows[0].get("level") != level or rows[0].get("tamestate") != 2 or rows[0].get("master_unique_rid") != 100010001:
            raise ValueError("Expected V5.1 isolated fusion pet pair")
    if set(template) != FIELDS or template["spiritid"] != 9001 or template["globalid"] != 0 or template["skill"] != []:
        raise ValueError("Expected original native default 9001 serializer template")
    target = copy.deepcopy(template)
    main = next(p for p in pets if p["petid"] == 4405)
    target.update(globalid=4407, level=75, skill=[9001000, 9001010, 9001020, 9001030], tamestate=2, basepetid=221)
    for key in ("hpimprove", "mpimprove", "strimprove", "defimprove", "comprehension", "spiritpower", "bonelevel"):
        value = main[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100000:
            raise ValueError("Invalid isolated inheritance input")
        target[key] = value
    response = {"code": 1000, "target": target, "main_global_id": 4405, "auxiliary_global_id": 4406,
                "cost_material": [{"A2": 503345, "A4": 2}, {"A2": 503346, "A4": 6}]}
    native = Path(__file__).with_suffix(".js").read_text().replace("RESPONSE_JSON", json.dumps(response, separators=(",", ":")))
    script = native + build_debug_script(source)
    replacements = [
        ("configureDebugTrueSpiritEntry(game,offlineStore);", "configureDebugTrueSpiritEntry(game,offlineStore);configureDebugFusion(game,offlineStore);"),
        ("return localTags.has(tag)", "return (tag==='REQUEST_BEAST_MIX'&&debugFusion?.response!==null)||localTags.has(tag)"),
        ("else if(tag==='REQUEST_LEVEL_LOTTERY'){", "else if(tag==='REQUEST_BEAST_MIX'){text=debugFusion.response;}\n else if(tag==='REQUEST_LEVEL_LOTTERY'){"),
        ("'roledata','bag','level','point','pet','mire','eggdata'", "'roledata','bag','level','point','pet','true_spirit_bag','mire','eggdata'"),
        ("capture(source,isCreate,lottery,mockMail){", "capture(source,isCreate,lottery,mockMail,fusion){"),
        ("    const text=dump(candidate);validate(text);const length=commit(text);", "    if(fusion!==undefined){const key=Memory.allocUtf8String('_DEBUG_ONLY_fusion'),value=fromText(JSON.stringify(fusion));try{assign(member(candidate,key),value);}finally{dtor(value);}}\n    const text=dump(candidate);validate(text);const length=commit(text);"),
        (" const keys=Object.keys(incoming);", " if(incoming.true_spirit_bag)validateDebugSpiritBag(incoming.true_spirit_bag);\n const keys=Object.keys(incoming);"),
        ("  readRequest(source){", "  debugFusionSave(snapshot,receipt){const value=fromText('{\"bag\":'+(snapshot.bag._DEBUG_ONLY_raw||JSON.stringify(snapshot.bag))+',\"pet\":'+(snapshot.pet._DEBUG_ONLY_raw||JSON.stringify(snapshot.pet))+',\"true_spirit_bag\":'+JSON.stringify(snapshot.true_spirit_bag)+'}');try{store.capture(value,false,undefined,undefined,receipt);}finally{dtor(value);}},\n  debugFusionState(){return baseline!==null&&has(baseline,Memory.allocUtf8String('_DEBUG_ONLY_fusion'))?JSON.parse(dump(get(baseline,Memory.allocUtf8String('_DEBUG_ONLY_fusion')))):null;},\n  readRequestText(source){return dump(source);},\n  readRequest(source){"),
        ("key!=='_offline_lottery'", "key!=='_DEBUG_ONLY_fusion'&&key!=='_offline_lottery'"),
    ]
    for before, after in replacements:
        if script.count(before) != 1:
            raise ValueError("Ambiguous fusion integration point")
        script = script.replace(before, after, 1)
    bag_entry = r"""
  const bagTrigger=Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files/DEBUG_ONLY_true_spirit_bag');
  if(access(bagTrigger,0)===0){
   if(unlink(bagTrigger)!==0)throw new Error('DEBUG_ONLY bag trigger failed');
   const develop=allocate(0x230);
   new NativeFunction(game.base.add(0x26d07f0),'void',['pointer'])(develop);
   if(!develop.readPointer().equals(game.base.add(0x5fdd4d0)))throw new Error('DEBUG_ONLY wrong spirit develop type');
   if(!new NativeFunction(develop.readPointer().add(0x38).readPointer(),'bool',['pointer'])(develop))throw new Error('DEBUG_ONLY spirit bag initialization failed');
   autorelease(develop);addChild(scene,develop,9001,7798);
   report({event:'DEBUG_ONLY-original-spirit-bag-opened'});return;
  }
"""
    marker = "  const layer=allocate(0x220);"
    if script.count(marker) != 1:
        raise ValueError("Missing isolated entry integration point")
    script = script.replace(marker, bag_entry + marker, 1)
    return script


async def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--experimental-fixed-9001", action="store_true")
    args = parser.parse_args()
    script = build_fusion_script(args.source.read_text(), json.loads(args.profile.read_text()),
                                 json.loads(args.template.read_text()), experimental=args.experimental_fixed_9001)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(script)
    args.output.chmod(0o600)


if __name__ == "__main__":
    asyncio.run(run())
