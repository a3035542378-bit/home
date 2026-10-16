"""生成独立APK用桥：内置测试初档，保留失败语义并说明离线边界。"""
import json
from pathlib import Path


def build_playable_bridge(source: str) -> str:
    prices = json.loads(Path(__file__).with_name('offline_shop_prices.json').read_text())
    if prices['version'] != 1 or any(not isinstance(row['price'], int) or isinstance(row['price'], bool) or row['price'] <= 0 for row in prices['prices'].values()):
        raise ValueError('Invalid offline shop price configuration')
    additions = 'const offlineShopPrices=' + json.dumps(prices, ensure_ascii=False) + ';\n' + Path(__file__).with_suffix('.js').read_text() + '\n' + Path(__file__).with_name('offline_shop.js').read_text()
    replacements = [
        ('  capture(source,isCreate,lottery,mockMail){', '  capture(source,isCreate,lottery,mockMail,shop){'),
        ('    const text=dump(candidate);validate(text);const length=commit(text);', '''    if(shop!==undefined){const value=fromText(JSON.stringify(shop));try{assign(member(candidate,Memory.allocUtf8String('_offline_shop')),value);}finally{dtor(value);}}
    const text=dump(candidate);validate(text);const length=commit(text);'''),
        ("key!=='_offline_lottery'", "key!=='_offline_shop'&&key!=='_offline_lottery'"),
        (" if(activeLottery!==null&&this.returnAddress.equals(at(0x29b9720))", " if(shopPurchase.defer(3,[center,name,response]))return;\n if(activeLottery!==null&&this.returnAddress.equals(at(0x29b9720))"),
        (" if(activeLottery!==null&&this.returnAddress.equals(at(0x29b9734))", " if(shopPurchase.defer(2,[center,name]))return;\n if(activeLottery!==null&&this.returnAddress.equals(at(0x29b9734))"),
        ('const localTags=new Set(', '''const shopPurchase=configureOfflineShopPurchase(game,store,{snapshot:use=>withBagSnapshot(use),point:currentPoint,post:(kind,args)=>kind===3?post3(...args):post2(...args)});
const shopList=configureOfflineShopList(game,store);
const localTags=new Set('''),
        ('  readRequest(source){', '''  seed(text){
   if(baseline!==null)throw new Error('Existing offline profile must not be replaced');
   validate(text);const value=fromText(text);
   try{store.capture(value,true);}finally{dtor(value);}
  },
  shopSyncPoint(value){if(baseline===null||failed||!has(baseline,pointKey)||!has(value,pointKey))throw new Error('Invalid offline shop list balance');assign(member(value,pointKey),get(baseline,pointKey));},
  shopLedger(){const key=Memory.allocUtf8String('_offline_shop');return baseline!==null&&has(baseline,key)?JSON.parse(dump(get(baseline,key))):{version:1,creditGranted:false,purchases:[]};},
  shopClone(source){const value=Memory.alloc(0x18);copy(value,source);return value;},
  shopDestroy(value){dtor(value);},
  shopSave(source,bag,pointText,state){
   const update=source===null?fromText('{}'):store.shopClone(source),point=fromText(pointText);
   try{if(bag!==null)assign(member(update,Memory.allocUtf8String('bag')),bag);assign(member(update,pointKey),point);store.capture(update,false,undefined,undefined,state);}
   finally{dtor(point);dtor(update);}
  },
  readRequest(source){'''),
        ('return localTags.has(tag)',
         "return shopPurchase.response(req)!==undefined||shopList(req)!==undefined||(tag==='REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER'?entryRequest!==null:localTags.has(tag))"),
        ("if(tag==='REQUEST_WILD_BOSS_LEVEL_INFO')", "if(tag==='REQUEST_PURCHASE')text=shopPurchase.response(req);\n else if(tag==='REQUEST_ITEM_LIST')text=shopList(req);\n else if(tag==='REQUEST_WILD_BOSS_LEVEL_INFO')"),
        ("report({event:'local-role-wire-ready'});",
         "configurePlayableFeedback(game);report({event:'local-role-wire-ready'});"),
        ('sdkReady=true;', '''if(!offlineStore.exists()){
 const app=Java.use('android.app.ActivityThread').currentApplication();
 if(app===null)throw new Error('Application is unavailable for offline initial profile');
 const input=app.getAssets().open('offline-v6-profile.json');
 const reader=Java.use('java.io.BufferedReader').$new(Java.use('java.io.InputStreamReader').$new(input,'UTF-8'));
 let text='',line;
 try{while((line=reader.readLine())!==null){text+=line;if(text.length>8*1024*1024)throw new Error('Offline initial profile exceeds limit');}}
 finally{reader.close();}
 offlineStore.seed(text);report({event:'offline-v6-initial-profile-created'});
 }
 sdkReady=true;'''),
    ]
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError('Ambiguous playable integration point')
        source = source.replace(before, after, 1)
    return additions + '\n' + source
