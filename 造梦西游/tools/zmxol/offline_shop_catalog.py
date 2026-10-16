"""从限定原表提取六类商品候选；配置存在不等于资源/购买/使用验收通过。"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

TABLES = ('item', 'equip', 'noblest_equip', 'pet', 'pet_pill', 'pet_equip', 'stone', 'magic')


def extract_catalog(database: Path, prices: dict) -> dict:
    categories = prices['categories']
    rows, evidence = {}, {}
    suits = database / 'role_suit.json'
    fashion_ids = set()
    if suits.exists():
        for row in json.loads(suits.read_text()).values():
            for key in ('fashion_ids', 'wing_ids', 'weapon_fashion_ids'):
                fashion_ids.update(row.get(key, []))
    for table in TABLES:
        path = database / (table + '.json')
        if not path.exists():
            continue
        raw = path.read_bytes()
        evidence[table] = hashlib.sha256(raw).hexdigest()
        for key, original in json.loads(raw).items():
            item_id, name = original.get('id'), original.get('name')
            if not isinstance(item_id, int) or isinstance(item_id, bool) or str(item_id) != key or item_id <= 0 or not isinstance(name, str) or not name:
                raise ValueError(f'Invalid original goods identity: {table}:{key}')
            text = name + original.get('type_info', '')
            if item_id in fashion_ids or '时装' in text:
                category, kind = categories[0], 'FASHION_INSTANCE'
            elif table == 'pet':
                category, kind = categories[1], 'TRUE_SPIRIT_INSTANCE' if original.get('is_beast') else 'PET_INSTANCE'
            elif any(word in text for word in ('礼盒', '礼包', '宝箱', '福袋')):
                category, kind = categories[5], 'GIFT_CONTRACT'
            elif table in ('pet_pill', 'pet_equip') or any(word in text for word in ('融灵', '灵元', '妖魂', '洗髓', '真灵', '宠物', '资质', '进化')):
                category, kind = categories[3], 'ITEM_OR_SPECIAL_INSTANCE'
            elif table in ('equip', 'noblest_equip', 'stone', 'magic') or any(word in text for word in ('启灵', '强化', '琉璃', '装备', '仙器', '镶嵌', '打造材料')):
                category, kind = categories[4], 'EQUIPMENT_OR_MATERIAL'
            else:
                category, kind = categories[2], 'ITEM_OR_SPECIAL_INSTANCE'
            override = prices['prices'].get(key)
            if override:
                if override['name'] != name:
                    raise ValueError(f'Configured name does not match original ID: {key}')
                price, source = override['price'], override['source']
                price_evidence = 'offline_shop_prices.json:prices.' + key
            elif isinstance(original.get('coupon_cost'), int) and original['coupon_cost'] > 0:
                price, source = original['coupon_cost'], 'HISTORICAL_PRICE'
                price_evidence = table + '.json:coupon_cost（客户端表值，非现服价格）'
            else:
                price, source = prices['default_prices'][category], 'OFFLINE_COMPAT'
                price_evidence = 'offline_shop_prices.json:default_prices.' + category
            if not isinstance(price, int) or isinstance(price, bool) or price <= 0 or source not in ('USER_DEFINED', 'HISTORICAL_PRICE', 'OFFLINE_COMPAT', 'UNKNOWN'):
                raise ValueError(f'Invalid price: {key}')
            previous = rows.get(item_id)
            if previous and previous['name'] != name:
                raise ValueError(f'Conflicting original ID: {key}')
            # 保留各原表的路由依据；商城分类不能替代原生容器类型。
            routing = {} if previous is None else dict(previous['original_routing'])
            routing[table] = {field: original[field] for field in (
                'type', 'bag_type', 'stackable', 'equip_type', 'use_type', 'is_beast'
            ) if field in original}
            rows[item_id] = {'id': item_id, 'name': name, 'category': category, 'instance_kind': kind,
                'source_tables': ([] if previous is None else previous['source_tables']) + [table],
                'original_routing': routing,
                'price': price, 'price_source': source, 'price_evidence': price_evidence,
                'description': original.get('introduction', ''),
                'status': 'PURCHASE_VALIDATED_USAGE_PENDING' if item_id in prices['enabled_material_ids'] else 'PENDING_RUNTIME_VALIDATION',
                'resource_status': 'UNKNOWN', 'purchase_enabled': item_id in prices['enabled_material_ids']}
    missing = set(prices['prices']) - {str(key) for key in rows}
    if missing:
        raise ValueError('Configured IDs absent from original tables: ' + ','.join(sorted(missing)))
    return {'version': 1, 'categories': categories, 'source_sha256': evidence,
            'classification': 'OFFLINE_COMPAT（收藏版候选分类，非原服商品目录）',
            'goods': sorted(rows.values(), key=lambda row: (categories.index(row['category']), row['id']))}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    prices = json.loads(Path(__file__).with_name('offline_shop_prices.json').read_text())
    result = await asyncio.to_thread(extract_catalog, args.database, prices)
    await asyncio.to_thread(args.output.write_text, json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({category: sum(row['category'] == category for row in result['goods']) for category in result['categories']}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
