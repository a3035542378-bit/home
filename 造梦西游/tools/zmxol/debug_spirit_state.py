"""在既有固定融合实验桥上恢复原版469状态提交；不用于正式APK。"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path


def build_spirit_state_script(source: str) -> str:
    additions = Path(__file__).with_suffix('.js').read_text()
    replacements = [
        ("debugFusion={response:null,used:false,receipt:null,thunk};", "debugFusion={response:null,used:false,receipt:null,thunk};\n" + additions),
        ("return (tag==='REQUEST_BEAST_MIX'", "return (tag==='REQUEST_BEAST_SET_TAMESTATE'&&debugFusion?.preparedState(req)&&store.healthy())||(tag==='REQUEST_BEAST_MIX'"),
        ("else if(tag==='REQUEST_BEAST_MIX'){", "else if(tag==='REQUEST_BEAST_SET_TAMESTATE'){text='{\"code\":1000}';}\n else if(tag==='REQUEST_BEAST_MIX'){"),
        ("  debugFusionSave(snapshot,receipt){", "  debugSpiritStateSave(snapshot){const value=fromText('{\"pet\":'+(snapshot.pet._DEBUG_ONLY_raw||JSON.stringify(snapshot.pet))+',\"true_spirit_bag\":'+JSON.stringify(snapshot.true_spirit_bag)+'}');try{store.capture(value,false);}finally{dtor(value);}},\n  debugFusionSave(snapshot,receipt){"),
    ]
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError('Ambiguous spirit state integration point')
        source = source.replace(before, after, 1)
    return source


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fusion_bridge', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    script = build_spirit_state_script(args.fusion_bridge.read_text())
    with args.output.open('x') as stream:
        stream.write(script)
    args.output.chmod(0o600)


if __name__ == '__main__':
    asyncio.run(main())
