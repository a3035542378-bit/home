// 独立包能力分类与商城列表；购买由独立原子事务适配器处理。
function offlineCapability(tag){
 const local=['REQUEST_PURCHASE','REQUEST_ITEM_LIST','REQUEST_CREATE_ROLE','REQUEST_ROLE_DATA','REQUEST_NEW_ROLE_NAME','REQUEST_SAVE_DATA','REQUEST_LEAVE_LEVEL','REQUEST_LEVEL_LEAVE_NEW','REQUEST_LEVEL_LOTTERY','REQUEST_LOGIN_HEART_BEAT','common_net_levelmapdata','REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER','REQUEST_WILD_BOSS_LEVEL_INFO','REQUEST_GET_OPEN_GROUP_LEVELS','REQUEST_POINT','REQUEST_RECEIVE_BULLETIN','REQUEST_MISSION_LIST','REQUEST_REQUEST_MAIL_LIST_NEW','REQUEST_MAIL_RECIEVE_REWARD','REQUEST_ROLE_INFO_2','REQUEST_PET_SET_TAMESTATE','REQUEST_APP_CHECK_UPDATE','REQUEST_UPDATE_RESOURCE'];
 return local.includes(tag)?'OFFLINE_COMPAT':'UNSUPPORTED';
}
function configurePlayableFeedback(game){
 for(const offset of [0x5209e90,0x520d4b0])if(game.base.add(offset).readUtf8String()!=='离线请求未完成，请返回并检查存档')throw new Error('Offline APK notice patch is missing');
 Interceptor.attach(game.base.add(0x2ab75d8),{onEnter(args){
  const raw=args[2];if(raw.isNull())return;
  const req=raw.add(0x18).readPointer();if(req.isNull())return;
  const name=req.add(0x40).readPointer();if(name.isNull())return;
  const tag=name.readUtf8String();
  if(!tag.startsWith('REQUEST_CHAT_'))report({event:'offline-capability',tag,mode:offlineCapability(tag)});
 }});
 report({event:'offline-playable-feedback-ready'});
}

function offlineShopListResponse(request, pointResponse){
 if(request===null||typeof request!=='object'||Array.isArray(request)||request.rid!==10001||Object.keys(request).some(key=>key!=='rid'))throw new Error('Unsupported offline shop list request');
 // shortcut: 只展示已核资源/原生入包的白名单，其他候选验收后再上架。
 const goods=offlineShopPrices.enabled_material_ids.map(id=>({id,price:{A2:offlineShopPrices.currency,A4:offlineShopPrices.prices[String(id)].price},num:1,category:0,goods_unique_mark:'offline-preview-'+id}));
 return pointResponse.slice(0,-1)+',"item":'+JSON.stringify(goods)+',"stone":[],"petitem":[],"fashion":[],"hotsale":'+JSON.stringify(goods)+'}';
}
function configureOfflineShopList(game,store){
 const pending=new Map(),responses=new Map(),at=offset=>game.base.add(offset);
 Interceptor.attach(at(0x2ab7c78),{
  onEnter(args){
   this.previous=pending.get(this.threadId);pending.delete(this.threadId);
   if(args[1].toInt32()!==7||args[4].isNull()||args[4].readUtf8String()!=='REQUEST_ITEM_LIST'||!store.exists()||!store.healthy())return;
   try{pending.set(this.threadId,offlineShopListResponse(store.readRequest(args[2]),store.pointResponse()));}
   catch(error){report({event:'offline-shop-list-rejected',error:error.message});}
  },
  onLeave(){if(this.previous===undefined)pending.delete(this.threadId);else pending.set(this.threadId,this.previous);}
 });
 Interceptor.attach(at(0x2a7d980),{onEnter(args){
  const request=args[1];if(request.isNull())return;
  responses.delete(request.toString());
  if(!this.returnAddress.equals(at(0x2ab8c74))||!pending.has(this.threadId))return;
  const tag=request.add(0x40).readPointer();
  if(!tag.isNull()&&tag.readUtf8String()==='REQUEST_ITEM_LIST')responses.set(request.toString(),pending.get(this.threadId));
 }});
 return request=>store.exists()&&store.healthy()?responses.get(request.toString()):undefined;
}
