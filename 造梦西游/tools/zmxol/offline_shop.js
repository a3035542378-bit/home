function offlineShopQuantity(bag,id){
 if(!bag||!Array.isArray(bag.item))throw new Error('Missing native shop bag');
 const rows=bag.item.filter(row=>row.A2===id);
 if(rows.length===0)return 0;
 if(rows.length!==1||!Number.isSafeInteger(rows[0].A4)||rows[0].A4<0)throw new Error('Invalid native shop stack');
 return rows[0].A4;
}
function offlineShopPlan(request,point,bag,ledger){
 const price=offlineShopPrices.prices[String(request.goodsid)];
 if(request.rid!==10001||request.service!==1||request.category!==0||!offlineShopPrices.enabled_material_ids.includes(request.goodsid)||!price||!Number.isInteger(request.num)||request.num<1||request.num>99)throw new Error('Unsupported offline purchase');
 if(!Number.isSafeInteger(point)||point<0)throw new Error('Unsupported shop balance');
 const cost=price.price*request.num,before=offlineShopQuantity(bag,request.goodsid);
 if(!Number.isSafeInteger(cost)||point<cost)throw new Error('Insufficient offline points');
 const row=bag.item.find(row=>row.A2===request.goodsid);
 // shortcut: 原生新堆叠不写旧实验CP字段，暂限无CP商品总量99，核实原上限后再扩展。
 if(row){const cap=row.CP===undefined?99:row.CP;if(!Number.isSafeInteger(cap)||before+request.num>cap)throw new Error('Offline item stack is full');}
 else if(!Number.isInteger(bag.bagsize)||bag.bagsize<=bag.item.length||request.num>9999999)throw new Error('Offline bag is full');
 if(offlineShopQuantity(request.savedata?.bag,request.goodsid)!==before)throw new Error('Stale offline purchase snapshot');
 if(request.savedata.point!==undefined&&request.savedata.point!==point)throw new Error('Stale offline purchase balance');
 // shortcut: 单档暂限1000笔消费记录；开放大规模商品前改为分页账本。
 if(ledger.purchases.length>=1000)throw new Error('Offline purchase ledger is full');
 return {seq:ledger.purchases.length+1,id:request.goodsid,num:request.num,cost,before,after:before+request.num,pointBefore:point,pointAfter:point-cost,priceSource:price.source};
}
function offlineShopCheckResult(plan,before,after){
 if(offlineShopQuantity(after,plan.id)!==plan.after)throw new Error('Native shop grant quantity mismatch');
 const granted=after.item.find(row=>row.A2===plan.id),old=before.item.find(row=>row.A2===plan.id);
 const expected=old?{...old,A4:plan.after}:{A2:plan.id,A4:plan.after};
 const canonical=value=>value!==null&&typeof value==='object'?(Array.isArray(value)?value.map(canonical):Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])]))):value;
 const without=bag=>({...bag,item:bag.item.filter(row=>row.A2!==plan.id)});
 if(JSON.stringify(canonical(expected))!==JSON.stringify(canonical(granted))||JSON.stringify(canonical(without(before)))!==JSON.stringify(canonical(without(after))))throw new Error('Native shop changed unrelated bag data');
}
function offlineShopCredit(state,balance){
 const desired=offlineShopPrices.initial_credit.amount,awarded=state.creditGranted?state.credit?.amount:0;
 if(!Number.isSafeInteger(desired)||desired<0||!Number.isSafeInteger(awarded)||awarded<0||!Number.isSafeInteger(balance)||balance<0)throw new Error('Invalid offline credit state');
 if(awarded>=desired)return null;
 const amount=desired-awarded,after=balance+amount;
 if(!Number.isSafeInteger(after))throw new Error('Offline credit balance exceeds limit');
 return {amount,after,total:desired};
}
function setOfflineShopPoint(player,value){
 const table=player.readPointer();
 new NativeFunction(table.add(0x60).readPointer(),'void',['pointer','int64'])(player,new Int64(String(value)));
 // 原0x2e87578链在设置点券后清零临时点券增量，避免后续ACK恢复旧余额。
 new NativeFunction(table.add(0x80).readPointer(),'void',['pointer','int'])(player,0);
}
function configureOfflineShopPurchase(game,store,runtime){
 const at=n=>game.base.add(n),pending=new Map(),responses=new Map();let active=null,inFlight=null;
 const getPlayer=new NativeFunction(at(0x30d0b74),'pointer',[]);
 const listParser=at(0x2e8ed84);
 if(listParser.readU32()!==0xd10743ff||listParser.add(4).readU32()!==0xa90473fb)throw new Error('Offline shop list parser fingerprint mismatch');
 Interceptor.attach(listParser,{onEnter(args){
  if(!store.exists()||!store.healthy())return;
  // 原购买后会重用旧列表；只将其point更新为已提交余额，防止0x2e8f1cc回滚钱包。
  try{store.shopSyncPoint(args[1]);}catch(error){store.blockLottery();report({event:'offline-shop-cached-balance-rejected',error:error.message});}
 }});
 function setPoint(value){setOfflineShopPoint(getPlayer(),value);}
 function ledger(){const state=store.shopLedger();if(state.version!==1||!Array.isArray(state.purchases)||typeof state.creditGranted!=='boolean')throw new Error('Invalid offline shop ledger');return state;}
 function credit(){
  const state=ledger(),before=Number(runtime.point()),grant=offlineShopCredit(state,before);if(grant===null)return;
  const {amount,after,total}=grant;
  setPoint(after);
  try{if(runtime.point()!==String(after))throw new Error('Native point setter mismatch');store.shopSave(null,null,String(after),{...state,creditGranted:true,credit:{amount:total,source:'OFFLINE_COMPAT'}});}
  catch(error){setPoint(before);throw error;}
  report({event:'offline-shop-initial-credit',amount});
 }
 Interceptor.attach(at(0x2ab7c78),{onEnter(args){
  this.previous=pending.get(this.threadId);pending.delete(this.threadId);
  const command=args[1].toInt32(),tag=args[4].isNull()?'':args[4].readUtf8String();
  if(command===7&&tag==='REQUEST_ITEM_LIST'){
   try{if(store.healthy()&&store.exists())credit();}catch(error){report({event:'offline-shop-credit-failed',error:error.message});}
  }
  if(command!==9||tag!=='REQUEST_PURCHASE'||!store.healthy()||!store.exists())return;
  const failure={text:'{"code":-1,"message":"Offline purchase rejected; no reward committed"}'};
  try{
   if(inFlight!==null)throw new Error('Offline purchase already in progress');
   const request=store.readRequest(args[2]);let before;
   const balance=Number(JSON.parse(store.pointResponse()).point);
   if(runtime.point()!==String(balance))throw new Error('Native and stored shop balances differ; restart required');
   runtime.snapshot(value=>{before=store.readRequest(value);});
   const plan=offlineShopPlan(request,balance,before,ledger());
   const get=new NativeFunction(at(0x3d2957c),'pointer',['pointer','pointer']);
   const source=store.shopClone(get(args[2],Memory.allocUtf8String('savedata')));
   const delivery={plan,before,source,used:false,text:JSON.stringify({code:1000,point:plan.pointAfter,offline_shop_seq:plan.seq})};
   inFlight=delivery;pending.set(this.threadId,delivery);
  }catch(error){pending.set(this.threadId,failure);report({event:'offline-shop-purchase-rejected',error:error.message});}
 },onLeave(){if(this.previous===undefined)pending.delete(this.threadId);else pending.set(this.threadId,this.previous);}});
 Interceptor.attach(at(0x2a7d980),{onEnter(args){
  const request=args[1];if(request.isNull())return;responses.delete(request.toString());
  if(!this.returnAddress.equals(at(0x2ab8c74))||!pending.has(this.threadId))return;
  const tag=request.add(0x40).readPointer();if(!tag.isNull()&&tag.readUtf8String()==='REQUEST_PURCHASE')responses.set(request.toString(),pending.get(this.threadId));
 }});
 const entry=at(0x2e8fe24);
 if(entry.readU32()!==0xd106c3ff)throw new Error('Offline shop response fingerprint mismatch');
 const original=new NativeFunction(entry,'void',['pointer','pointer']);
 const textAt=(response,offset)=>response.add(offset).readPointer().add(0x18).readPointer().readUtf8String();
 Interceptor.replace(entry,new NativeCallback(function(manager,response){
  if(response.isNull()||textAt(response,0x38)!=='REQUEST_PURCHASE'){original(manager,response);return;}
  const body=textAt(response,0x30),delivery=Array.from(responses.values()).find(value=>value.plan&&value.text===body);
  if(delivery===undefined){if(JSON.parse(body).code===1000){report({event:'offline-shop-unprepared-success-blocked'});return;}original(manager,response);return;}
  if(delivery.used||!store.healthy()){report({event:'offline-shop-replay-blocked'});return;}
  delivery.used=true;active=[];
  try{
   if(runtime.point()!==String(delivery.plan.pointBefore))throw new Error('Offline balance changed during purchase');
   original(manager,response);
   setPoint(delivery.plan.pointAfter);
   runtime.snapshot(value=>{
    offlineShopCheckResult(delivery.plan,delivery.before,store.readRequest(value));
    if(runtime.point()!==String(delivery.plan.pointAfter))throw new Error('Offline point debit mismatch');
    const state=ledger();store.shopSave(delivery.source,value,String(delivery.plan.pointAfter),{...state,purchases:[...state.purchases,delivery.plan]});
   });
   const notifications=active;active=null;
   for(const [kind,...args] of notifications)runtime.post(kind,args);
   // 原ACK通知可能恢复请求前的内存点券；通知完成后再次与已提交账本对齐。
   setPoint(delivery.plan.pointAfter);
   if(runtime.point()!==String(delivery.plan.pointAfter))throw new Error('Native point notification restored a stale balance');
   report({event:'offline-shop-purchase-committed',...delivery.plan});
  }catch(error){store.blockLottery();report({event:'offline-shop-commit-failed-restart-required',error:error.message});}
  finally{active=null;store.shopDestroy(delivery.source);inFlight=null;}
 },'void',['pointer','pointer']));
 return {response:request=>store.healthy()?responses.get(request.toString())?.text:undefined,
  defer(kind,args){if(active===null)return false;active.push([kind,...args]);return true;}};
}
