import asyncio
import json
from pathlib import Path

import pytest

from playable_bridge import build_playable_bridge


def test_build_is_narrow(tmp_path):
    source = Path(__file__).with_name('offline_bridge.js').read_text()
    generated = build_playable_bridge(source)
    assert "if(baseline!==null)throw" in generated
    assert "offlineStore.seed(text)" in generated
    assert 'DEBUG_ONLY_true_spirit_entry' not in generated
    assert "tag==='REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER'?entryRequest!==null" in generated
    with pytest.raises(ValueError):
        build_playable_bridge('invalid')
    path = tmp_path / 'bridge.js'
    path.write_text(generated)

    async def check():
        process = await asyncio.create_subprocess_exec('node', '--check', str(path))
        assert await process.wait() == 0

    asyncio.run(check())


@pytest.mark.parametrize('tag,expected', [
    ('REQUEST_ITEM_LIST', 'OFFLINE_COMPAT'),
    ('REQUEST_SAVE_DATA', 'OFFLINE_COMPAT'),
    ('REQUEST_SHOP_BUY', 'UNSUPPORTED'),
])
def test_capability_classification(tag, expected):
    async def check():
        script = "const fs=require('fs'),vm=require('vm'),c=vm.createContext({});vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);process.stdout.write(c.offlineCapability(process.argv[2]));"
        process = await asyncio.create_subprocess_exec('node', '-e', script, str(Path(__file__).with_name('playable_bridge.js')), tag, stdout=asyncio.subprocess.PIPE)
        output, _ = await process.communicate()
        assert process.returncode == 0
        assert output.decode() == expected
    asyncio.run(check())


@pytest.mark.parametrize('level,supported', [(700002, True), (700004, False)])
def test_only_verified_level_gets_local_entry_ack(tmp_path, level, supported):
    from test_offline_bridge import NODE_WIRE_CHECK

    generated = build_playable_bridge(Path(__file__).with_name('offline_bridge.js').read_text())
    # 复用协议/原子存储替身；此替身只保存单个hook，不模拟独立UI提示观察器。
    generated = generated.replace("const shopPurchase=configureOfflineShopPurchase(game,store,{snapshot:use=>withBagSnapshot(use),point:currentPoint,post:(kind,args)=>kind===3?post3(...args):post2(...args)});", "const shopPurchase={response:()=>undefined,defer:()=>false};").replace("configurePlayableFeedback(game);", '').replace("const shopList=configureOfflineShopList(game,store);", "const shopList=()=>undefined;")
    path = tmp_path / 'bridge.js'
    path.write_text(generated)

    async def check():
        payload = {'tag': 'REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER', 'command': 37,
                   'nativeStore': True, 'send': True, 'requestBody': {'levelid': level}}
        process = await asyncio.create_subprocess_exec('node', '-e', NODE_WIRE_CHECK, str(path), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, error = await process.communicate(json.dumps(payload).encode())
        assert process.returncode == 0, error.decode()
        result = json.loads(output)
        assert result.get('callbackError') is None
        assert bool(result['writes']) is supported

    asyncio.run(check())




@pytest.mark.parametrize('payload,valid', [
    ({'rid': 10001}, True), ({'rid': 10002}, False),
    ({'rid': 10001, 'extra': 1}, False), (None, False), ([], False),
])
def test_shop_preview_contract(payload, valid):
    async def check():
        script = """const fs=require('fs'),vm=require('vm'),c=vm.createContext({});
vm.runInContext('const offlineShopPrices='+fs.readFileSync(process.argv[1].replace('playable_bridge.js','offline_shop_prices.json'),'utf8')+';',c);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);
try{process.stdout.write(c.offlineShopListResponse(JSON.parse(process.argv[2]),'{"code":1000,"point":9007199254740993}'));}
catch(e){process.stdout.write(JSON.stringify({error:e.message}));}"""
        process = await asyncio.create_subprocess_exec('node', '-e', script,
            str(Path(__file__).with_name('playable_bridge.js')), json.dumps(payload), stdout=asyncio.subprocess.PIPE)
        output, _ = await process.communicate()
        assert process.returncode == 0
        value = json.loads(output)
        if valid:
            assert value['point'] == 9007199254740993
            assert [row['id'] for row in value['item']] == [502000, 502001, 530002]
            assert value['hotsale'] == value['item']
            assert value['fashion'] == value['petitem'] == value['stone'] == []
            assert [row['price']['A4'] for row in value['item']] == [1, 1, 20000]
        else:
            assert 'error' in value
    asyncio.run(check())
