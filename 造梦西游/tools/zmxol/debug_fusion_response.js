function assertDebugFusionCanPrepare(receipt){
 if(receipt!==null)throw new Error('Existing fusion receipt: '+receipt?.phase+'; reload before any retry');
}
function assertDebugFusionResponse(state,value){
 if(!state.response||state.used||debugFusionCanonical(value)!==debugFusionCanonical(JSON.parse(state.response)))throw new Error('Unprepared/repeated fusion response');
}
function validateDebugFusionSources(req,before){
 const expected={rid:10001,main_pet:{type_id:221,global_id:4405},auxiliary_pet:{type_id:229,global_id:4406},is_common_fusion:1};
 if(debugFusionCanonical(req)!==debugFusionCanonical(expected))throw new Error('Unsupported isolated fusion request');
 const ids=before.pet.petinfo.map(x=>x.petid);
 if(ids.length!==new Set(ids).size||ids.includes(4407)||before.true_spirit_bag.list.length)throw new Error('Invalid isolated fusion source identities');
 for(const [id,type,level] of [[4405,221,75],[4406,229,60]]){
  const pet=before.pet.petinfo.find(x=>x.petid===id);
  if(!pet||pet.dataid!==type||pet.level<level||pet.tamestate!==2)throw new Error('Invalid isolated fusion source pet');
 }
 if(before.materials.length!==2||before.materials[0].A2!==503345||before.materials[1].A2!==503346||before.materials.some(x=>!Number.isInteger(x.A4)||x.A4<0)||before.materials[0].A4<2||before.materials[1].A4<6)throw new Error('Insufficient native fusion materials');
}
function validateDebugSpiritBag(bag){
 const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
 const uint=v=>Number.isInteger(v)&&v>=0&&v<=0x7fffffff;
 if(!object(bag)||Object.keys(bag).sort().join(',')!=='bagsize,list,maxspiritid'||!Array.isArray(bag.list)||!uint(bag.bagsize)||bag.bagsize<1||bag.bagsize>4096||bag.list.length>bag.bagsize||!uint(bag.maxspiritid))throw new Error('Invalid independent true spirit bag');
 const fields='exp level skill iselite triones globalid opbasehp opbasemp spiritid basepetid bonelevel hpimprove mpimprove opbasedef opbasestr petequips tamestate defimprove mastername strimprove spiritpower talentskill opskilllevel passiveskill comprehension sageskilllevel opsageskilllevel sageskillposition tabooextraskilllevel'.split(' ').sort().join(',');
 const arrays=new Set(['skill','triones','petequips','talentskill','passiveskill','sageskillposition']),maps=new Set(['opskilllevel','sageskilllevel','opsageskilllevel','tabooextraskilllevel']),ids=new Set();
 for(const spirit of bag.list){
  if(!object(spirit)||Object.keys(spirit).sort().join(',')!==fields||!uint(spirit.globalid)||spirit.globalid===0||spirit.globalid>bag.maxspiritid||ids.has(spirit.globalid)||!Number.isInteger(spirit.spiritid)||spirit.spiritid<9000||spirit.spiritid>9045||!Number.isInteger(spirit.level)||spirit.level<1||spirit.level>1000)throw new Error('Invalid true spirit identity');
  ids.add(spirit.globalid);
  for(const [key,value] of Object.entries(spirit)){
   if(key==='mastername'){if(typeof value!=='string'||value.length>128)throw new Error('Invalid spirit owner name');}
   else if(arrays.has(key)){if(!Array.isArray(value))throw new Error('Invalid spirit array: '+key);}
   else if(maps.has(key)){if(value!==null&&!object(value))throw new Error('Invalid spirit skill levels: '+key);}
   else if(typeof value!=='number'||!Number.isFinite(value))throw new Error('Invalid spirit scalar: '+key);
  }
  if(spirit.triones.length!==9||spirit.triones.some(v=>!uint(v))||spirit.skill.some(v=>!uint(v)||v===0)||spirit.petequips.length||spirit.passiveskill.length||spirit.talentskill.length||spirit.sageskillposition.length)throw new Error('Unsupported experimental spirit equipment or inherited skills');
 }
 return bag;
}
let debugFusion=null;
function debugFusionCanonical(value){return JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);}
function configureDebugFusion(game,store){
 const at=n=>game.base.add(n),fn=(n,r,a)=>new NativeFunction(at(n),r,a);
 const response=RESPONSE_JSON;
 const singleton=fn(0x3aad200,'pointer',[]),factory=fn(0x3aad6d4,'pointer',['pointer','pointer','pointer','pointer']);
 const ctor=fn(0x3d28344,'void',['pointer','int']),destroy=fn(0x3d2a33c,'void',['pointer']);
 const readerCtor=fn(0x3d23f04,'void',['pointer']),readerDtor=fn(0x211e004,'void',['pointer']);
 const parse=fn(0x3d27110,'uint',['pointer','pointer','pointer','pointer','int']);
 const getPets=fn(0x2c1348c,'pointer',[]),getBag=fn(0x2d1f964,'pointer',[]);
 const count=fn(0x4e153bc,'uint',['pointer']),objectAt=fn(0x4e168bc,'pointer',['pointer','uint']);
 const retain=fn(0x4e13d28,'void',['pointer']),release=fn(0x4e13da8,'void',['pointer']);
 const thunk=Memory.alloc(Process.pageSize);Memory.protect(thunk,Process.pageSize,'r-x');
 Memory.patchCode(thunk,8,p=>{p.writeU32(0xaa0103e8);p.add(4).writeU32(0xd61f0040);});
 const serialize=new NativeFunction(thunk,'void',['pointer','pointer','pointer']);
 function withJson(value,callback){const text=JSON.stringify(value),data=Memory.allocUtf8String(text),out=Memory.alloc(0x18),reader=Memory.alloc(0xe0);ctor(out,0);readerCtor(reader);try{if(!parse(reader,data,data.add(text.length),out,1))throw new Error('Fusion JSON parse failed');return callback(out);}finally{destroy(out);readerDtor(reader);}}
 function snapshot(object,offset){if(thunk.isNull())throw new Error('Serializer thunk unavailable');const out=Memory.alloc(0x18);serialize(object,out,at(offset));try{const text=store.readRequestText(out),value=JSON.parse(text);if(offset===0x2d4053c||offset===0x2c1ab40)Object.defineProperty(value,'_DEBUG_ONLY_raw',{value:text});return value;}finally{destroy(out);}}
 function spirits(){const array=getPets().add(0x298),list=[];for(let i=0;i<count(array);i++)list.push(snapshot(objectAt(array,i),0x3a67b30));return validateDebugSpiritBag({list,bagsize:fn(0x2bf9930,'uint',['pointer'])(getPets()),maxspiritid:Math.max(0,...list.map(x=>x.globalid))});}
 function materials(){
  const find=fn(0x2d22be0,'pointer',['pointer','pointer','int','uint8']),init=fn(0x3d304c8,'void',['pointer','ulong','pointer']),check=fn(0x3d301a4,'void',['pointer','ulong','pointer','pointer']),rows=[];
  for(const id of [503345,503346]){
   const key=Memory.alloc(12);key.writeU32(id);key.add(8).writeU16(0);init(key,4,key);key.add(4).writeU32(id);check(key.add(4),4,key.add(8),ptr(0));
   const item=find(getBag(),key,-1,1);
   const quantity=item.isNull()?0:new NativeFunction(item.readPointer().add(0xe0).readPointer(),'uint',['pointer'])(item);
   rows.push({A2:id,A4:quantity});
  }
  return rows;
 }
 function restoreMaterials(receipt){
  if(receipt!==null&&(receipt.version!==1||receipt.mode!=='DEBUG_ONLY_FIXED_COMPAT_9001'||!['prepared','committed'].includes(receipt.phase)))throw new Error('Ambiguous fusion recovery receipt');
  const desired=receipt?.phase==='committed'?receipt.after?.materials:receipt?.before?.materials;
  if(receipt===null)return;
  if(!Array.isArray(desired)||desired.length!==2||desired[0].A2!==503345||desired[1].A2!==503346)throw new Error('Missing fusion material recovery snapshot');
  const current=materials(),make=fn(0x3c6b750,'pointer',['pointer']),cast=fn(0x4ffd82c,'pointer',['pointer','pointer','pointer','long']),add=fn(0x2d41900,'bool',['pointer','pointer','pointer','uint8','uint8','uint8']);
  for(const row of desired){
   if(![503345,503346].includes(row.A2)||!Number.isInteger(row.A4)||row.A4<0||row.A4>100)throw new Error('Invalid isolated material receipt');
   const existing=current.find(x=>x.A2===row.A2);
   if(existing.A4===row.A4)continue;
   if(existing.A4!==0)throw new Error('Ambiguous native material restore');
   if(row.A4===0)continue;
   withJson(row,value=>{const object=make(value);if(object.isNull())throw new Error('Native material restore factory failed');retain(object);try{const item=cast(object,at(0x67784d0).readPointer(),at(0x677f968).readPointer(),0);if(item.isNull()||!add(getBag(),item,getBag(),0,1,0))throw new Error('Native material restore failed');}finally{release(object);}});
  }
  if(debugFusionCanonical(materials())!==debugFusionCanonical(desired))throw new Error('Native material restore mismatch');
  report({event:'DEBUG_ONLY-native-materials-restored',materials:materials()});
 }

 function full(){return {bag:snapshot(getBag(),0x2d4053c),pet:snapshot(getPets(),0x2c1ab40),true_spirit_bag:spirits(),materials:materials()};}
 debugFusion={response:null,used:false,receipt:null,thunk};
 Interceptor.attach(at(0x2c16994),{onEnter(){
  try{
   debugFusion.response=null;
   const activation=Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files/DEBUG_ONLY_enable_fixed_fusion');
   if(new NativeFunction(Module.getExportByName('libc.so','access'),'int',['pointer','int'])(activation,0)!==0)throw new Error('Explicit fixed-result test activation required');
   if(!store.healthy())throw new Error('Fusion storage unavailable');
   const old=store.debugFusionState();assertDebugFusionCanPrepare(old);
   const wire=store.readRequest(this.context.x2),req=Object.fromEntries(['rid','main_pet','auxiliary_pet','is_common_fusion'].map(k=>[k,wire[k]]));
   if(['directed_material','evolution_material','green_type','is_use_sheep'].some(k=>k in wire))throw new Error('Unsupported optional fusion inputs');
   report({event:'DEBUG_ONLY-fusion-request-save-modules',modules:Object.keys(wire.savedata||{})});
   const before=full();validateDebugFusionSources(req,before);
   withJson(response.target,value=>{const object=factory(singleton(),value,ptr(0),ptr(0));if(object.isNull())throw new Error('Original factory rejected fusion result');retain(object);try{const actual=snapshot(object,0x3a67b30);report({event:'DEBUG_ONLY-fusion-factory-preflight',actual});if(actual.spiritid!==9001||actual.globalid!==4407||actual.skill.length!==4)throw new Error('Factory identity/skills round trip failed');}finally{release(object);}});
   debugFusion.receipt={version:1,mode:'DEBUG_ONLY_FIXED_COMPAT_9001',phase:'prepared',request:req,response,before};
   store.debugFusionSave(before,debugFusion.receipt);
   debugFusion.response=JSON.stringify(response);
   report({event:'DEBUG_ONLY-fusion-response-prepared',mode:debugFusion.receipt.mode});
  }catch(error){report({event:'DEBUG_ONLY-fusion-prepare-blocked',error:error.message});}
 }});
 Interceptor.attach(at(0x2c181fc),{onEnter(args){this.accepted=false;try{const value=store.readRequest(args[1]);assertDebugFusionResponse(debugFusion,value);debugFusion.used=true;this.accepted=true;report({event:'DEBUG_ONLY-original-fusion-consumer-enter'});}catch(error){report({event:'DEBUG_ONLY-fusion-consumer-rejected',error:error.message});args[1]=withJson({},value=>{const out=Memory.alloc(0x18);new NativeFunction(at(0x3d2ab7c),'void',['pointer','pointer'])(out,value);return out;});this.empty=args[1];}},onLeave(result){if(this.empty)destroy(this.empty);if(!this.accepted)return;try{const after=full();report({event:'DEBUG_ONLY-original-fusion-after',result:result.toInt32(),after});if(result.toInt32()!==1||after.true_spirit_bag.list.length!==1||after.true_spirit_bag.list[0].globalid!==4407||after.pet.petinfo.some(x=>[4405,4406].includes(x.petid))||after.materials[0].A4!==debugFusion.receipt.before.materials[0].A4-2||after.materials[1].A4!==debugFusion.receipt.before.materials[1].A4-6)throw new Error('Native fusion snapshot mismatch');const preserved=debugFusion.receipt.before.pet.petinfo.filter(x=>![4405,4406].includes(x.petid));if(debugFusionCanonical(preserved)!==debugFusionCanonical(after.pet.petinfo)||debugFusionCanonical(debugFusion.receipt.before.bag)!==debugFusionCanonical(after.bag))throw new Error('Fusion changed unrelated native assets');store.debugFusionSave(after,{...debugFusion.receipt,phase:'committed',after});report({event:'DEBUG_ONLY-fusion-committed'});}catch(error){store.blockLottery();result.replace(0);debugFusion.response=null;report({event:'DEBUG_ONLY-fusion-commit-blocked',error:error.message});}}});
 if(at(0x2bfe9fc).readU32()!==0xd63f00c0)throw new Error('Spirit state sender fingerprint mismatch');
 Interceptor.attach(at(0x2bfe9fc),{onEnter(){const req=store.readRequest(this.context.x2);report({event:'DEBUG_ONLY-original-spirit-state-request',command:469,fields:Object.fromEntries(['rid','global_id','state'].filter(k=>k in req).map(k=>[k,req[k]]))});}});
 const replayMarker=Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files/DEBUG_ONLY_replay_fusion_response');
 const access=new NativeFunction(Module.getExportByName('libc.so','access'),'int',['pointer','int']);
 const unlink=new NativeFunction(Module.getExportByName('libc.so','unlink'),'int',['pointer']);
 let lastReplayCheck=0;
 Interceptor.attach(game.getExportByName('_ZN7cocos2d10CCDirector9drawSceneEv'),{onEnter(){
  if(Date.now()-lastReplayCheck<500)return;lastReplayCheck=Date.now();
  if(access(replayMarker,0)!==0)return;
  const global=at(0x67b85d0).readPointer();if(global.isNull())return;
  const scene=global.add(0x270).readPointer();if(scene.isNull()||!scene.readPointer().equals(at(0x67086e0)))return;
  if(unlink(replayMarker)!==0)throw new Error('Replay marker could not be consumed');
  try{
   const receipt=store.debugFusionState();if(receipt?.phase!=='committed')throw new Error('Committed fusion required for replay audit');
   const before=full();
   let guarded;try{assertDebugFusionResponse(debugFusion,receipt.response);throw new Error('Replay guard unexpectedly accepted');}catch(error){if(error.message!=='Unprepared/repeated fusion response')throw error;guarded={};}
   // 诊断先过同一守卫，避免 NativeFunction 调用抑制 hook 时触碰已消费的主宠。
   withJson(guarded,value=>fn(0x2c181fc,'uint',['pointer','pointer'])(getPets(),value));
   const after=full();
   if(debugFusionCanonical(before)!==debugFusionCanonical(after))throw new Error('Replay changed native assets');
   report({event:'DEBUG_ONLY-duplicate-fusion-response-unchanged',ids:after.true_spirit_bag.list.map(x=>x.globalid),materials:after.materials});
  }catch(error){report({event:'DEBUG_ONLY-replay-audit-failed',error:error.message});}
 }});

 Interceptor.attach(at(0x2bfca74),{onLeave(result){try{restoreMaterials(store.debugFusionState());report({event:'DEBUG_ONLY-original-spirit-load',result:result.toInt32(),bag:spirits()});const b=getBag(),v=b.readPointer();report({event:'DEBUG_ONLY-bag-vtable',offset:v.sub(game.base).toString(),getter:v.add(0x1d8).readPointer().sub(game.base).toString(),setter:v.add(0x1e0).readPointer().sub(game.base).toString()});}catch(error){store.blockLottery();result.replace(0);report({event:'DEBUG_ONLY-spirit-load-blocked',error:error.message});}}});
 report({event:'DEBUG_ONLY-fusion-compat-ready',mode:'DEBUG_ONLY_FIXED_COMPAT_9001'});
}
