import asyncio
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent


def run_node(payload):
    async def run():
        script = '''const fs=require('fs'),vm=require('vm'),c=vm.createContext({});
vm.runInContext('const offlineShopPrices='+fs.readFileSync(process.argv[1]+'/offline_shop_prices.json','utf8')+';',c);
vm.runInContext(fs.readFileSync(process.argv[1]+'/offline_shop.js','utf8'),c);
const p=JSON.parse(process.argv[2]);
try{const plan=c.offlineShopPlan(p.request,p.point,p.bag,{purchases:[]});
if(p.after)c.offlineShopCheckResult(plan,p.bag,p.after);
process.stdout.write(JSON.stringify(plan));}catch(e){process.stdout.write(JSON.stringify({error:e.message}));}'''
        process = await asyncio.create_subprocess_exec('node', '-e', script, str(ROOT), json.dumps(payload), stdout=asyncio.subprocess.PIPE)
        output, _ = await process.communicate()
        assert process.returncode == 0
        return json.loads(output)
    return asyncio.run(run())


def purchase():
    bag = {'item': [{'A2': 502000, 'A4': 21, 'CP': 9999999}, {'A2': 502001, 'A4': 5, 'CP': 9999999}]}
    return {'point': 198, 'bag': bag, 'request': {'rid': 10001, 'service': 1, 'category': 0, 'goodsid': 502000, 'num': 1, 'savedata': {'point': 198, 'bag': json.loads(json.dumps(bag))}}}


def test_native_grant_and_debit_contract():
    payload = purchase()
    payload['after'] = json.loads(json.dumps(payload['bag']))
    payload['after']['item'][0]['A4'] = 22
    plan = run_node(payload)
    assert plan['pointAfter'] == 197 and plan['after'] == 22 and plan['cost'] == 1


@pytest.mark.parametrize('case', ['insufficient', 'invalid', 'negative', 'overflow', 'stale_bag', 'stale_point', 'full', 'duplicate_grant', 'unrelated_change'])
def test_purchase_fails_closed(case):
    payload = purchase()
    if case == 'insufficient':
        payload['point'] = 0
    elif case == 'invalid':
        payload['request']['goodsid'] = 99999999
    elif case == 'negative':
        payload['request']['num'] = -1
    elif case == 'overflow':
        payload['point'] = 2**53 + 1
    elif case == 'stale_bag':
        payload['request']['savedata']['bag']['item'][0]['A4'] = 20
    elif case == 'stale_point':
        payload['request']['savedata']['point'] = 197
    elif case == 'full':
        payload['bag']['item'][0]['CP'] = 21
    else:
        payload['after'] = json.loads(json.dumps(payload['bag']))
        payload['after']['item'][0]['A4'] = 23 if case == 'duplicate_grant' else 22
        if case == 'unrelated_change':
            payload['after']['item'][1]['A4'] = 0
    assert 'error' in run_node(payload)


def test_user_prices_match_original_item_config():
    prices = json.loads((ROOT / 'offline_shop_prices.json').read_text())
    assert len(prices['categories']) == 6
    expected = {'503345': 198, '503346': 88, '530002': 20000, '532420': 3000, '532202': 600}
    assert {key: value['price'] for key, value in prices['prices'].items() if value['source'] == 'USER_DEFINED'} == expected


@pytest.mark.parametrize('fail_write', [False, True])
def test_shop_assets_and_receipt_share_native_atomic_write(tmp_path, fail_write):
    from playable_bridge import build_playable_bridge
    from test_offline_bridge import NODE_WIRE_CHECK

    path = tmp_path / 'shop.js'
    path.write_text(build_playable_bridge((ROOT / 'offline_bridge.js').read_text()))
    script = NODE_WIRE_CHECK.replace(
        "else if (action.kind === 'begin')",
        "else if (action.kind === 'shop') store.shopSave(null, nativeValue(action.bag), String(action.point), action.ledger);\n      else if (action.kind === 'begin')")
    baseline = {'roledata': {'player': {'roleid': 1}, 'role': {'rolelv': 90}}, 'point': 198,
                'bag': {'item': [{'A2': 502000, 'A4': 21, 'CP': 9999999}]}}
    ledger = {'version': 1, 'creditGranted': True, 'purchases': [{'seq': 1, 'id': 502000, 'cost': 1}]}
    payload = {'nativeStore': True, 'baseline': baseline,
               'lotteryActions': [{'kind': 'shop', 'point': 197, 'bag': {'item': [{'A2': 502000, 'A4': 22, 'CP': 9999999}]}, 'ledger': ledger}]}
    if fail_write:
        payload['failWriteAt'] = 1

    async def check():
        process = await asyncio.create_subprocess_exec('node', '-e', script, str(path), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, error = await process.communicate(json.dumps(payload).encode())
        assert process.returncode == 0, error.decode()
        result = json.loads(output)
        if fail_write:
            assert result['stored'] == baseline and result['persisted'] is None
            assert result['healthy'] is False and 'error' in result['results'][0]
        else:
            assert result['stored']['point'] == 197
            assert result['stored']['bag']['item'][0]['A4'] == 22
            assert result['stored']['_offline_shop'] == ledger
            assert result['persisted'] == result['stored']
            assert '_offline_shop' not in result['role']['savedata']
    asyncio.run(check())


@pytest.mark.parametrize('state,balance,expected', [
    ({'creditGranted': False}, 0, {'amount': 2000000, 'after': 2000000, 'total': 2000000}),
    ({'creditGranted': True, 'credit': {'amount': 198}}, 197, {'amount': 1999802, 'after': 1999999, 'total': 2000000}),
    ({'creditGranted': True, 'credit': {'amount': 2000000}}, 1999999, None),
])
def test_test_credit_migration_is_once_and_keeps_spending(state, balance, expected):
    async def check():
        script = '''const fs=require('fs'),vm=require('vm'),c=vm.createContext({});
vm.runInContext('const offlineShopPrices='+fs.readFileSync(process.argv[1]+'/offline_shop_prices.json','utf8')+';',c);
vm.runInContext(fs.readFileSync(process.argv[1]+'/offline_shop.js','utf8'),c);
process.stdout.write(JSON.stringify(c.offlineShopCredit(JSON.parse(process.argv[2]),Number(process.argv[3]))));'''
        process = await asyncio.create_subprocess_exec('node', '-e', script, str(ROOT), json.dumps(state), str(balance), stdout=asyncio.subprocess.PIPE)
        output, _ = await process.communicate()
        assert process.returncode == 0 and json.loads(output) == expected
    asyncio.run(check())


def test_catalog_candidates_preserve_ids_and_price_priority(tmp_path):
    from offline_shop_catalog import extract_catalog
    prices = json.loads((ROOT / 'offline_shop_prices.json').read_text())
    prices['prices'] = {'503345': prices['prices']['503345']}
    (tmp_path / 'item.json').write_text(json.dumps({
        '503345': {'id': 503345, 'name': '虚天灵元丹', 'type_info': '', 'coupon_cost': 999},
        '999': {'id': 999, 'name': '原表药水', 'coupon_cost': 5},
        '998': {'id': 998, 'name': '原表礼盒', 'coupon_cost': 0},
    }))
    catalog = extract_catalog(tmp_path, prices)
    goods = {row['id']: row for row in catalog['goods']}
    assert set(goods) == {503345, 999, 998}
    assert goods[503345]['price'] == 198 and goods[503345]['price_source'] == 'USER_DEFINED'
    assert goods[999]['price'] == 5 and goods[999]['price_source'] == 'HISTORICAL_PRICE'
    assert goods[998]['price_source'] == 'OFFLINE_COMPAT' and goods[998]['category'] == '礼盒'
    assert not any(row['purchase_enabled'] for row in goods.values())
    assert all(row['status'] == 'PENDING_RUNTIME_VALIDATION' for row in goods.values())
    (tmp_path / 'item.json').write_text(json.dumps({'503345': {'id': 503346, 'name': '错误映射'}}))
    with pytest.raises(ValueError, match='identity'):
        extract_catalog(tmp_path, prices)


def test_catalog_keeps_native_routes_separate_from_shop_categories(tmp_path):
    from offline_shop_catalog import extract_catalog
    prices = json.loads((ROOT / 'offline_shop_prices.json').read_text())
    prices['prices'] = {}
    original = {'id': 501120, 'name': '青锋', 'type_info': '时装',
                'type': 12, 'bag_type': 0, 'stackable': 0, 'equip_type': 4}
    (tmp_path / 'equip.json').write_text(json.dumps({'501120': original}))
    (tmp_path / 'noblest_equip.json').write_text(json.dumps({
        '501120': {**original, 'bag_type': 1}}))
    (tmp_path / 'pet.json').write_text(json.dumps({
        '9001': {'id': 9001, 'name': '真灵样本', 'type': 17, 'is_beast': 1}}))
    goods = {row['id']: row for row in extract_catalog(tmp_path, prices)['goods']}
    assert goods[501120]['category'] == '时装'
    assert goods[501120]['original_routing'] == {
        'equip': {'type': 12, 'bag_type': 0, 'stackable': 0, 'equip_type': 4},
        'noblest_equip': {'type': 12, 'bag_type': 1, 'stackable': 0, 'equip_type': 4}}
    assert goods[9001]['instance_kind'] == 'TRUE_SPIRIT_INSTANCE'
    assert goods[9001]['original_routing']['pet']['is_beast'] == 1
    assert not any(row['purchase_enabled'] for row in goods.values())


@pytest.mark.parametrize('full', [False, True])
def test_new_material_stack_requires_capacity_and_exact_native_result(full):
    payload = purchase()
    payload['point'] = 2000000
    payload['bag']['bagsize'] = len(payload['bag']['item']) if full else 72
    payload['request']['goodsid'] = 530002
    payload['request']['savedata'] = {'point': 2000000, 'bag': json.loads(json.dumps(payload['bag']))}
    payload['after'] = json.loads(json.dumps(payload['bag']))
    payload['after']['item'].append({'A2': 530002, 'A4': 1})
    result = run_node(payload)
    if full:
        assert 'error' in result
    else:
        assert result['pointAfter'] == 1980000 and result['priceSource'] == 'USER_DEFINED'


def test_point_adapter_clears_native_temporary_delta():
    async def check():
        script = '''const fs=require('fs'),vm=require('vm');let base=198,temporary=1;const calls=[];
const player={readPointer:()=>({add:offset=>({readPointer:()=>offset})})};
const c=vm.createContext({Int64:function(value){this.toString=()=>value;},NativeFunction:function(offset){
return (_player,value)=>{calls.push(offset);if(offset===0x60)base=Number(value);else if(offset===0x80)temporary=value;else throw Error('Unexpected virtual function');};}});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);
c.setOfflineShopPoint(player,197);if(base+temporary!==197||JSON.stringify(calls)!=='[96,128]')throw Error('Stale point delta survived');'''
        process = await asyncio.create_subprocess_exec('node', '-e', script, str(ROOT / 'offline_shop.js'))
        assert await process.wait() == 0
    asyncio.run(check())


def test_cached_list_cannot_restore_pre_purchase_balance(tmp_path):
    from playable_bridge import build_playable_bridge
    from test_offline_bridge import NODE_WIRE_CHECK
    path = tmp_path / 'shop.js'
    path.write_text(build_playable_bridge((ROOT / 'offline_bridge.js').read_text()))
    script = NODE_WIRE_CHECK.replace("else if (action.kind === 'begin')", "else if (action.kind === 'cached_list') {const value=nativeValue(action.list);store.shopSyncPoint(value);result=store.readRequest(value);}\n      else if (action.kind === 'begin')")
    baseline = {'roledata': {'player': {'roleid': 1}, 'role': {'rolelv': 90}}, 'point': 197,
                'bag': {'item': [{'A2': 502000, 'A4': 22}]}}
    cached = {'code': 1000, 'point': 198, 'item': [{'id': 502000}], 'hotsale': []}
    async def check():
        process = await asyncio.create_subprocess_exec('node', '-e', script, str(path), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, error = await process.communicate(json.dumps({'nativeStore': True, 'baseline': baseline, 'lotteryActions': [{'kind': 'cached_list', 'list': cached}]}).encode())
        assert process.returncode == 0, error.decode()
        result = json.loads(output)
        assert result['results'][0]['result'] == {**cached, 'point': 197}
        assert result['stored'] == baseline and result['diskWrites'] == 0
    asyncio.run(check())
