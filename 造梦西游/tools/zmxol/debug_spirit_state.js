 function validateSpiritStateTransition(request,before,after){
  if(before.roledata?.player?.roleid!==1||request.rid!==10001||!Number.isInteger(request.global_id)||request.global_id<=0||![1,2].includes(request.state))throw new Error('Unsupported spirit state request');
  const old=before.true_spirit_bag,next=after.true_spirit_bag;
  validateDebugSpiritBag(old);validateDebugSpiritBag(next);
  if(!old.list.some(x=>x.globalid===request.global_id))throw new Error('Unknown spirit instance');
  const expected=JSON.parse(JSON.stringify({pet:before.pet,true_spirit_bag:old}));
  for(const row of [...expected.pet.petinfo,...expected.true_spirit_bag.list]){
   if(![1,2].includes(row.tamestate))throw new Error('Unsupported native tame state');
   if(row.globalid===request.global_id&&'spiritid' in row)row.tamestate=request.state;
   else if(request.state===1&&row.tamestate===1)row.tamestate=2;
  }
  if(debugFusionCanonical(expected)!==debugFusionCanonical({pet:after.pet,true_spirit_bag:next}))throw new Error('Native state transition changed unrelated fields');
 }
 const stateThreads=new Set(),stateRequests=new Set();
 if(at(0x33174c8).readU32()!==0xd102c3ff)throw new Error('Original armor skill factory fingerprint mismatch');
 Interceptor.attach(at(0x33174c8),{onEnter(args){this.skill=args[1].toInt32();},onLeave(result){report({event:'DEBUG_ONLY-original-armor-skill-factory',skill:this.skill,created:!result.isNull()});}});
 Interceptor.attach(at(0x2bfca74),{onEnter(){
  const files=new NativeFunction(game.getExportByName('_ZN7cocos2d11CCFileUtils15sharedFileUtilsEv'),'pointer',[])();
  new NativeFunction(game.getExportByName('_ZN7cocos2d11CCFileUtils13addSearchPathEPKc'),'void',['pointer','pointer'])(files,Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files/DEBUG_ONLY-assets/'));
 }});
 debugFusion.preparedState=req=>stateRequests.has(req.toString());
 for(const sender of [0x2ab7c78,0x2ab9290])Interceptor.attach(at(sender),{onEnter(args){
  this.stateRequest=args[1].toInt32()===469&&!args[4].isNull()&&args[4].readUtf8String()==='REQUEST_BEAST_SET_TAMESTATE';
  if(!this.stateRequest)return;stateThreads.delete(this.threadId);
  try{
   if(!store.healthy()||store.debugFusionState()?.phase!=='committed')throw new Error('Committed isolated fusion required');
   const wire=store.readRequest(args[2]),request=Object.fromEntries(['rid','global_id','state'].map(k=>[k,wire[k]]));
   const before=JSON.parse(store.roleResponse()).savedata,after=full();
   validateSpiritStateTransition(request,before,after);
   // 原UI先完成内存状态变更；持久化成功后才允许原版ACK进入响应链。
   store.debugSpiritStateSave(after);stateThreads.add(this.threadId);
   report({event:'DEBUG_ONLY-spirit-state-committed',request,spirits:after.true_spirit_bag.list.map(x=>({id:x.globalid,state:x.tamestate})),pets:after.pet.petinfo.map(x=>({id:x.petid,state:x.tamestate}))});
  }catch(error){store.blockLottery();report({event:'DEBUG_ONLY-spirit-state-blocked',error:error.message});}
 },onLeave(){if(this.stateRequest)stateThreads.delete(this.threadId);}});
 Interceptor.attach(at(0x2a7d980),{onEnter(args){
  const req=args[1];if(req.isNull())return;
  stateRequests.delete(req.toString());
  if(!this.returnAddress.equals(at(0x2ab8c74))||!stateThreads.has(this.threadId)||!store.healthy())return;
  const tag=req.add(0x40).readPointer();
  if(!tag.isNull()&&tag.readUtf8String()==='REQUEST_BEAST_SET_TAMESTATE')stateRequests.add(req.toString());
 }});

