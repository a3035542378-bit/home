'use strict';
// 仅匹配已验证的 15.7.2 ARM64 库；偏移不可跨版本复用。
function report(event) {
 const writeLog=new NativeFunction(Module.getExportByName('liblog.so','__android_log_write'),'int',['int','pointer','pointer']);
 writeLog(4,Memory.allocUtf8String('ZMXOL-offline'),Memory.allocUtf8String(JSON.stringify(event)));
}
function configureOfflineSdkNetwork(){
 Java.perform(function(){
  const utility=Java.use('com.ssjj.fnsdk.core.SsjjFNUtility');
  const IOException=Java.use('java.io.IOException');
  utility.openUrlOnceWithTimeOut.overload('android.content.Context','java.lang.String','java.lang.String','com.ssjj.fnsdk.core.entity.SsjjFNParameters','java.lang.String','java.lang.String','int','int').implementation=function(){
   // 无 INTERNET 权限的 SecurityException 会使 SDK 线程崩溃；沿原 IOException 失败回调结束请求。
   report({event:'offline-sdk-network-blocked'});
   throw IOException.$new('Offline SDK network unavailable');
  };
  report({event:'offline-sdk-network-failure-ready'});
 });
}
function offlineLotteryPool(levelId){
 // shortcut: 仅重建已核实的材料与制作书牌池；其他关卡须先验证物品类型与原生入包契约。
 const pools={700002:[503031,502000,502001],700003:[502211,503031,502000,502001]};
 if(!Number.isSafeInteger(levelId)||!Object.prototype.hasOwnProperty.call(pools,levelId))throw new Error('Unsupported offline lottery level');
 return pools[levelId].map(A2=>({A2,A4:1}));
}
function offlineLotteryRemoved(levelId,removed){
 const size=offlineLotteryPool(levelId).length;
 if(!Array.isArray(removed)||removed.length>=size||removed.some(index=>!Number.isSafeInteger(index)||index<0||index>=size)||new Set(removed).size!==removed.length)throw new Error('Invalid offline lottery removed indices');
 return removed.slice().sort((left,right)=>left-right);
}
function drawOfflineLottery(levelId,removed){
 const excluded=offlineLotteryRemoved(levelId,removed),pool=offlineLotteryPool(levelId).filter((_item,index)=>!excluded.includes(index));
 // 自定离线规则：剩余候选等概率、每张数量 1；并非原服务端概率。
 return [pool[Math.floor(Math.random()*pool.length)]];
}
const offlineMockMailId=900504100;
const offlineMockBaguaMailId=900504200;
const offlineMockBattlePetMailId=900000252;
const offlineDebugMailStart=900600000;
function isOfflineDebugMailId(id){return Number.isInteger(id)&&id>=offlineDebugMailStart&&id<=0x7fffffff;}
function offlineMockMailKind(state){
 if(state.id===offlineMockMailId)return 'pill';
 if(state.id===offlineMockBaguaMailId)return 'bagua';
 if(state.id===offlineMockBattlePetMailId)return 'pet';
 if(isOfflineDebugMailId(state.id)&&['pet','pill','bagua'].includes(state.kind))return state.kind;
 throw new Error('Unknown offline Mock mail kind');
}
function offlineMockBattlePetTemplate(){
 // 明确的 Mock 测试参数：252 原表下界、原 born_skill；战斗属性由原 loader 计算。
 // petid=1 仅供未入库预览，原 BagMgr 领取时必须重新分配唯一 ID。
 return {dataid:252,level:60,petid:1,petexp:0,lifetime:100,tamestate:2,iselite:0,ferity:1,mixlevel:0,isspecialchange:0,
  basehp:150,basemp:100,basestr:10,basedef:2,hpimprove:600,mpimprove:600,strimprove:600,defimprove:200,
  comprehension:1,spiritpower:1,bonelevel:1,skill:[210000,210010,210020,210030,210040,210050],
  triones:[1,1,0,0,0,0,0,0,0],petequips:[]};
}
function validateOfflineMockMailList(request){
 if(!request||Array.isArray(request)||request.rid!==10001||request.offset!==0||!((request.type===1&&!('owner_type' in request))||(request.type===2&&(request.owner_type===1||request.owner_type===2))))throw new Error('Unsupported offline Mock mail list request');
 return request.type===2&&request.owner_type===2;
}
function validateOfflineMockMailClaim(request){
 if(!request||Array.isArray(request)||request.rid!=='10001'||!([offlineMockMailId,offlineMockBaguaMailId,offlineMockBattlePetMailId].includes(request.id)||isOfflineDebugMailId(request.id))||request.type!==37||request.mtype!==0||request.is_user!==0||request.offset!==0)throw new Error('Unsupported offline Mock mail claim request');
}
function offlineMockPetMail(state){
 if(isOfflineDebugMailId(state.id)){
  const kind=offlineMockMailKind(state),formalId=kind==='pet'?offlineMockBattlePetMailId:kind==='bagua'?offlineMockBaguaMailId:offlineMockMailId;
  const original=offlineMockPetMail({...state,id:formalId});
  return {...original,id:String(state.id),title:original.title+' [Debug '+state.id+']',desc:'独立调试重发邮件；不改正式赠品收据，非自然掉落。此邮件只能领取一次。'};
 }
 if(offlineMockMailKind(state)==='pet')return {id:String(state.id),title:'[Mock] 60级圣佛邪君验收赠品',from:'[Mock] 本地离线测试',desc:'独立新增一只60级圣佛邪君（火丸最终形态），原表基础资质下界、原生六项技能。仅供离线丹药与八卦验收，非自然培养或关卡产出；保留已有火丸，每个本地存档限领一次。',mtype:0,state:0,expired:state.expired,dateline:state.dateline,is_user:0,type:0};
 const bagua=offlineMockMailKind(state)==='bagua';
 return {id:String(state.id),title:bagua?'[Mock] 八卦乾验收赠品':'[Mock] 宠物丹药验收赠品',from:'[Mock] 本地离线测试',desc:bagua?'仅供离线八卦功能验收，非关卡自然掉落。领取一件原生生成的八卦乾，每个本地存档限领一次。':'仅供离线宠物功能验收，非关卡自然掉落。领取一颗涅槃丹（攻），每个本地存档限领一次。',mtype:0,state:0,expired:state.expired,dateline:state.dateline,is_user:0,type:0};
}
function offlineMissionTasks(profile){
 const player=profile.roledata?.player,story=profile.mire?.storytask;
 if(player?.roleid!==1||!Array.isArray(player.completeguide)||!Array.isArray(story))throw new Error('Offline mission snapshot is incomplete');
 if(story.length){
  return story.map(task=>{
   if(task===null||typeof task!=='object'||task.tid!==6000000||!Number.isInteger(task.state)||![2,3,4,5,6].includes(task.state)||!Array.isArray(task.targetprogress))throw new Error('Unsupported offline story task');
   for(const target of task.targetprogress){
    if(target===null||typeof target!=='object'||![[2,700004],[1,304],[1,305]].some(([type,id])=>target.mission_content_type===type&&target.mission_target_id===id)||!Number.isSafeInteger(target.mission_progress)||target.mission_progress<0)throw new Error('Invalid offline story task progress');
   }
   return {...task,rewards:[]};
  });
 }
 // shortcut: 首次讨伐教学开放原表首任务；后续任务及未知原服领奖契约须另行核实。
 if(!player.completeguide.includes(900023)||player.completeguide.includes(900037))throw new Error('Offline first mission is not available');
 return [{tid:6000000,state:6,targetprogress:[],rewards:[]}];
}
function validateSaveUpdate(incoming) {
 const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
 if(!object(incoming))throw new Error('Invalid offline update');
 const keys=Object.keys(incoming);
const unsupported=keys.filter(key=>!['roledata','bag','level','point','pet','mire','eggdata','interaction_data','novice_boot_task_progress','is_saved_from'].includes(key));
if(unsupported.length)throw new Error('Unsupported offline save module: '+unsupported.join(','));
if('is_saved_from' in incoming&&incoming.is_saved_from!==1)throw new Error('Invalid offline save source marker');
for(const key of keys)if(key!=='point'&&key!=='is_saved_from'&&!object(incoming[key]))throw new Error('Invalid offline module shape: '+key);
for(const name of ['eggdata','novice_boot_task_progress'])if(name in incoming&&Object.keys(incoming[name]).length)throw new Error('Unsupported nonempty offline event: '+name);
if(incoming.mire&&Object.keys(incoming.mire).some(key=>key!=='storytask'))throw new Error('Unsupported offline mire event');
if(incoming.mire&&'storytask' in incoming.mire&&!Array.isArray(incoming.mire.storytask))throw new Error('Invalid offline story task list');
if(incoming.interaction_data){
 const interaction=incoming.interaction_data;
 const unsupportedInteraction=Object.keys(interaction).filter(key=>!['get_base_item_list','fight_time','catch_pet'].includes(key));
 if(unsupportedInteraction.length)throw new Error('Unsupported offline interaction: '+unsupportedInteraction.join(','));
 if('fight_time' in interaction&&(!Number.isSafeInteger(interaction.fight_time)||interaction.fight_time<0))throw new Error('Invalid offline fight time');
 if('catch_pet' in interaction){
  const count=interaction.catch_pet,pet=incoming.pet;
  if(!Number.isInteger(count)||count<0||count>0x7fffffff)throw new Error('Invalid offline pet catch count');
  // 捕获次数是 ACK 后清零的报告；保存完整宠物快照，不按次数生成或追加宠物。
  const uint32=value=>Number.isInteger(value)&&value>=0&&value<=0xffffffff;
  if(count>0&&(!pet||!Array.isArray(pet.petinfo)||!uint32(pet.bagsize)||!uint32(pet.maxglobalpetid)))throw new Error('Offline pet catch is missing its complete pet snapshot');
 }
 if('get_base_item_list' in interaction&&!object(interaction.get_base_item_list))throw new Error('Invalid offline base item groups');
 let spirit=0;
 for(const items of Object.values(interaction.get_base_item_list||{})){
  if(!Array.isArray(items))throw new Error('Invalid offline base item list');
  for(const item of items){if(!object(item)||Object.keys(item).some(key=>!['A2','A4'].includes(key))||item.A2!==503031||!Number.isSafeInteger(item.A4)||item.A4<0)throw new Error('Unsupported offline base item');spirit+=item.A4;}
 }
 if(!Number.isSafeInteger(spirit))throw new Error('Offline reward total exceeds supported range');
 // 报告累计收入；学习技能等支出可使当前余额低于收入，不能再次发奖或比较两者大小。
 if(spirit&&(!incoming.bag||!Number.isSafeInteger(incoming.bag.spiritcount)||incoming.bag.spiritcount<0))throw new Error('Offline reward is missing its bag snapshot');
}
 return keys;
}
function createNativeSaveStore(game) {
 const at=x=>game.base.add(x);
 const fn=(offset,ret,args)=>new NativeFunction(at(offset),ret,args);
 const ctor=fn(0x3d28344,'void',['pointer','int']);
 const copy=fn(0x3d2ab7c,'void',['pointer','pointer']);
 const dtor=fn(0x3d2a33c,'void',['pointer']);
 const readerCtor=fn(0x3d23f04,'void',['pointer']);
 const readerDtor=fn(0x211e004,'void',['pointer']);
 const parse=fn(0x3d27110,'uint',['pointer','pointer','pointer','pointer','int']);
 const has=fn(0x3d295b8,'bool',['pointer','pointer']);
 const get=fn(0x3d2957c,'pointer',['pointer','pointer']);
 const member=fn(0x3d2c370,'pointer',['pointer','pointer']);
 const assign=fn(0x3d2b1d0,'pointer',['pointer','pointer']);
 const writerCtor=fn(0x3d1f05c,'void',['pointer']);
 const writeValue=fn(0x3d1f08c,'void',['pointer','pointer']);
 const writerDtor=fn(0x3d1e598,'void',['pointer']);
 const sys=(name,ret,args)=>new SystemFunction(Module.getExportByName('libc.so',name),ret,args);
 const open=sys('open','int',['pointer','int','int']);
 const read=sys('read','long',['int','pointer','ulong']);
 const write=sys('write','long',['int','pointer','ulong']);
 const close=sys('close','int',['int']);
 const sync=sys('fsync','int',['int']);
 const rename=sys('rename','int',['pointer','pointer']);
 const strlen=new NativeFunction(Module.getExportByName('libc.so','strlen'),'ulong',['pointer']);
 const path=Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files/offline-save.json');
 const temp=Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files/offline-save.json.tmp');
 const directory=Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files');
 const pointKey=Memory.allocUtf8String('point');
 const lotteryKey=Memory.allocUtf8String('_offline_lottery');
 const mockMailKey=Memory.allocUtf8String('_offline_mock_mail');
 const mockBaguaKey=Memory.allocUtf8String('_offline_mock_bagua');
 const mockBattlePetKey=Memory.allocUtf8String('_offline_mock_pet');
 const arrayElement=fn(0x3d293b8,'pointer',['pointer','uint']);
 const limit=8*1024*1024;
 let baseline=null,failed=false;
 function dump(value) {
  const writer=Memory.alloc(0x18);writerCtor(writer);
  try{writeValue(writer,value);const p=writer.add(8).readPointer(),length=p.sub(0x18).readU64().toNumber();if(length>limit)throw new Error('Offline save exceeds size limit');return p.readUtf8String(length);}
  finally{writerDtor(writer);}
 }
 function fromText(text) {
  const value=Memory.alloc(0x18),reader=Memory.alloc(0xe0),bytes=Memory.allocUtf8String(text);
  ctor(value,0);readerCtor(reader);
  try{if(!parse(reader,bytes,bytes.add(strlen(bytes).toNumber()),value,1))throw new Error('Offline save JSON is invalid');}
  catch(error){dtor(value);throw error;}
  finally{readerDtor(reader);}
  return value;
 }
 function validate(text) {
  const value=JSON.parse(text);
  if(!value||Array.isArray(value)||value.roledata?.player?.roleid!==1||!value.bag||!Number.isInteger(value.roledata?.role?.rolelv))throw new Error('Offline save is not a supported Wukong profile');
  return value;
 }
 function loadDisk() {
  const opened=open(path,0x8000|0x80000,0);
  if(opened.value<0){if(opened.errno===2)return null;throw new Error('Offline save open failed: '+opened.errno);}
  const fd=opened.value,buffer=Memory.alloc(limit+1);let length=0;
  try{
   while(length<=limit){const result=read(fd,buffer.add(length),limit+1-length),count=result.value.toNumber();if(count<0){if(result.errno===4)continue;throw new Error('Offline save read failed: '+result.errno);}if(count===0)break;length+=count;}
   if(length===0||length>limit)throw new Error('Offline save has invalid size');
   const text=buffer.readUtf8String(length);validate(text);return fromText(text);
  }finally{const result=close(fd);if(result.value!==0)report({event:'offline-save-close-failed',errno:result.errno});}
 }
 function commit(text) {
  let replaced=false;
  try{
  const bytes=Memory.allocUtf8String(text),length=strlen(bytes).toNumber();
  const opened=open(temp,0x241|0x8000|0x80000,0x180);if(opened.value<0)throw new Error('Offline temporary save open failed: '+opened.errno);
  const fd=opened.value;let written=0;
  try{
   while(written<length){const result=write(fd,bytes.add(written),length-written),count=result.value.toNumber();if(count<0){if(result.errno===4)continue;throw new Error('Offline save write failed: '+result.errno);}if(count===0)throw new Error('Offline save write made no progress');written+=count;}
   const result=sync(fd);if(result.value!==0)throw new Error('Offline save flush failed: '+result.errno);
  }finally{const result=close(fd);if(result.value!==0)throw new Error('Offline save close failed: '+result.errno);}
  const renamed=rename(temp,path);if(renamed.value!==0)throw new Error('Offline save replace failed: '+renamed.errno);replaced=true;
  const directoryFd=open(directory,0x4000|0x80000,0);if(directoryFd.value<0)throw new Error('Offline save directory open failed: '+directoryFd.errno);
  try{const result=sync(directoryFd.value);if(result.value!==0)throw new Error('Offline save directory flush failed: '+result.errno);}finally{close(directoryFd.value);}
  return length;
  }catch(error){error.offlineSaveBeforeReplace=!replaced;throw error;}
 }
 function lotteryState(){
  if(failed)throw new Error('Offline lottery storage is unavailable');
  if(baseline===null||!has(baseline,lotteryKey))return null;
  const state=JSON.parse(dump(get(baseline,lotteryKey)));
  if(!state||Array.isArray(state)||state.version!==1||!Number.isSafeInteger(state.round)||state.round<1||!['entered','offered','drawn','committed'].includes(state.phase))throw new Error('Invalid offline lottery receipt');
  offlineLotteryPool(state.levelid);
  const selected=state.phase==='drawn'||state.phase==='committed';
  const allowed=selected?['version','round','phase','levelid','removed','reward']:['version','round','phase','levelid'];
  if(Object.keys(state).some(key=>!allowed.includes(key)))throw new Error('Invalid offline lottery receipt fields');
  if(selected){
   const removed=offlineLotteryRemoved(state.levelid,state.removed),reward=state.reward;
   if(JSON.stringify(removed)!==JSON.stringify(state.removed)||!Array.isArray(reward)||reward.length!==1||!reward[0]||Object.keys(reward[0]).length!==2||reward[0].A4!==1||!offlineLotteryPool(state.levelid).some((item,index)=>!removed.includes(index)&&item.A2===reward[0].A2))throw new Error('Invalid offline lottery reward receipt');
  }
  return state;
 }
 function writeLottery(state){
  const source=fromText('{}');
  try{store.capture(source,false,state);}finally{dtor(source);}
 }
 function mailKey(id){
  if(id===offlineMockMailId)return mockMailKey;
  if(id===offlineMockBaguaMailId)return mockBaguaKey;
  if(id===offlineMockBattlePetMailId)return mockBattlePetKey;
  if(isOfflineDebugMailId(id))return Memory.allocUtf8String('_offline_debug_mail_'+id);
  throw new Error('Unknown offline Mock mail');
 }
 function validBaguaItem(item){
  return item!==null&&typeof item==='object'&&!Array.isArray(item)&&item.A2===504200&&item.A4===1&&Number.isInteger(item.A5)&&item.A5>4398&&item.A5<=0x7fffffff&&Number.isInteger(item.UNIRID)&&item.UNIRID>=0;
 }
 function validMockBattlePet(item){
  if(!item||Array.isArray(item)||!Number.isSafeInteger(item.master_unique_rid)||item.master_unique_rid<1)return false;
  const expected=offlineMockBattlePetTemplate();
  return Object.keys(expected).every(key=>JSON.stringify(item[key])===JSON.stringify(expected[key]))&&Object.keys(item).every(key=>key==='master_unique_rid'||key in expected);
 }
 function mockMailState(id=offlineMockMailId){
  if(failed)throw new Error('Offline mail storage is unavailable');
  const key=mailKey(id);if(baseline===null||!has(baseline,key))return null;
  const state=JSON.parse(dump(get(baseline,key)));
  if(!state||Array.isArray(state)||Object.keys(state).some(key=>!['version','rid','id','kind','phase','dateline','expired','reward'].includes(key))||state.version!==1||state.rid!==10001||state.id!==id||!['requested','offered','claiming','committed'].includes(state.phase))throw new Error('Invalid offline Mock mail receipt');
  const kind=offlineMockMailKind(state);
  if(!isOfflineDebugMailId(id)&&('kind' in state||state.phase==='requested'))throw new Error('Invalid formal Mock mail receipt');
  if(state.phase==='requested'){if(Object.keys(state).length!==5)throw new Error('Invalid debug mail request');return state;}
  if(!Number.isInteger(state.dateline)||state.dateline<0||!Number.isInteger(state.expired)||state.expired<state.dateline||state.expired>0x7fffffff||!Array.isArray(state.reward)||state.reward.length!==1)throw new Error('Invalid offline Mock mail attachment');
  const item=state.reward[0];
  if(kind==='pill'?(!item||Object.keys(item).length!==2||item.A2!==504100||item.A4!==1):kind==='bagua'?!validBaguaItem(item):!validMockBattlePet(item))throw new Error('Invalid offline Mock mail attachment');
  return state;
 }
 function mailReward(id){return get(get(baseline,mailKey(id)),Memory.allocUtf8String('reward'));}
 function debugMailIds(){
  if(baseline===null)return [];
  const keys=Object.keys(JSON.parse(dump(baseline))).filter(key=>key.startsWith('_offline_debug_mail_'));
  if(keys.length>4096)throw new Error('Debug mail history exceeds supported limit');
  return keys.map(key=>{
   const text=key.slice(20),id=Number(text);if(!/^[0-9]+$/.test(text)||String(id)!==text||!isOfflineDebugMailId(id))throw new Error('Invalid debug mail identity');
   mockMailState(id);return id;
  }).sort((a,b)=>a-b);
 }
 function mailRows(excluded){
  const rows=[];
  for(const id of [offlineMockMailId,offlineMockBaguaMailId,offlineMockBattlePetMailId,...debugMailIds()]){
   const state=mockMailState(id);
   if(id!==excluded&&state!==null&&state.phase!=='committed'&&state.phase!=='requested')rows.push(JSON.stringify(offlineMockPetMail(state)).slice(0,-1)+',"reward":'+dump(mailReward(id))+'}');
  }
  return '['+rows.join(',')+']';
 }
 function mockMailResponse(mails,reward){
  return store.pointResponse().slice(0,-1)+',"mails":'+mails+',"total_page_num":1,"offset":0'+(reward===undefined?'':',"reward":'+dump(reward))+'}';
 }
 function mailPhase(id,phase){
  const receipt=Memory.alloc(0x18),value=fromText(JSON.stringify(phase));copy(receipt,get(baseline,mailKey(id)));
  try{assign(member(receipt,Memory.allocUtf8String('phase')),value);return dump(receipt);}
  finally{dtor(value);dtor(receipt);}
 }
 function assertSameItem(left,right){
  const keys=Object.keys(JSON.parse(dump(left))).sort(),other=Object.keys(JSON.parse(dump(right))).sort();
  if(JSON.stringify(keys)!==JSON.stringify(other))throw new Error('Mock bagua item fields changed');
  for(const name of keys){const key=Memory.allocUtf8String(name);if(dump(get(left,key))!==dump(get(right,key)))throw new Error('Mock bagua item changed: '+name);}
 }
 function petSnapshot(value){
  const snapshot=JSON.parse(dump(value)),uint32=number=>Number.isInteger(number)&&number>=0&&number<=0xffffffff;
  if(!snapshot||Array.isArray(snapshot)||!Array.isArray(snapshot.petinfo)||!uint32(snapshot.bagsize)||!uint32(snapshot.maxglobalpetid))throw new Error('Mock pet snapshot is incomplete');
  const ids=new Set();
  for(const pet of snapshot.petinfo){if(!pet||!uint32(pet.petid)||pet.petid===0||ids.has(pet.petid))throw new Error('Mock pet snapshot has invalid identities');ids.add(pet.petid);}
  if(snapshot.petinfo.length>snapshot.bagsize)throw new Error('Mock pet bag capacity is invalid');
  return snapshot;
 }
 baseline=loadDisk();
 const store={
  exists(){return baseline!==null;},
  healthy(){return !failed;},
  text(){if(baseline===null)throw new Error('No offline save exists');return dump(baseline);},
  pointResponse(){
   if(baseline===null||!has(baseline,pointKey))throw new Error('Offline point snapshot is missing');
   return '{"code":1000,"point":'+dump(get(baseline,pointKey))+'}';
  },
  mockMailList(request){
   const eligible=validateOfflineMockMailList(request);mockMailState();
   store.pointResponse();
   if(eligible)store.ensureMockPillMail();
   return mockMailResponse(eligible?mailRows(): '[]');
  },
  mockMailKind(id){const state=mockMailState(id);if(state===null)throw new Error('Mock mail receipt is missing');return offlineMockMailKind(state);},
  debugMailRequests(){return debugMailIds().filter(id=>mockMailState(id).phase==='requested').map(id=>({id,kind:offlineMockMailKind(mockMailState(id))}));},
  ensureMockPillMail(id=offlineMockMailId){
   const previous=mockMailState(id);if(previous!==null&&previous.phase!=='requested')return;
   if(previous!==null&&offlineMockMailKind(previous)!=='pill')throw new Error('Wrong debug mail kind');
   if(previous===null&&id!==offlineMockMailId)throw new Error('Missing debug mail request');
   {
    const dateline=Math.floor(Date.now()/1000);if(dateline<0||dateline>0x7fffffff)throw new Error('Offline Mock mail date exceeds supported range');
    const state={version:1,rid:10001,id,...(isOfflineDebugMailId(id)?{kind:'pill'}:{}),phase:'offered',dateline,expired:Math.min(dateline+365*86400,0x7fffffff),reward:[{A2:504100,A4:1}]};
    const source=fromText('{}');try{store.capture(source,false,undefined,state);}finally{dtor(source);}
   }
  },
  ensureMockBaguaMail(make,id=offlineMockBaguaMailId){
   const pending=mockMailState(id);if(pending!==null&&pending.phase!=='requested')return;
   if(pending!==null&&offlineMockMailKind(pending)!=='bagua')throw new Error('Wrong debug mail kind');
   if(pending===null&&id!==offlineMockBaguaMailId)throw new Error('Missing debug mail request');
   store.pointResponse();
   const value=fromText('{"A2":504200,"A4":1}');
   try{make(value,(item,before,bag)=>{
    const reward=store.readRequest(item),previous=store.readRequest(before),snapshot=store.readRequest(bag);
    if(!validBaguaItem(reward)||!Number.isInteger(previous.maxglobalitemid)||previous.maxglobalitemid<4399||reward.A5<previous.maxglobalitemid||!Number.isInteger(snapshot.maxglobalitemid)||snapshot.maxglobalitemid<=reward.A5||snapshot.maxglobalitemid>0xffffffff)throw new Error('Mock bagua native ID reservation is invalid');
    const collision=value=>value!==null&&typeof value==='object'&&(value.A5===reward.A5||Object.values(value).some(collision));
    if(collision(previous)||collision(JSON.parse(dump(baseline))))throw new Error('Mock bagua native ID already exists');
    const keys=Object.keys(previous).sort(),afterKeys=Object.keys(snapshot).sort();
    if(JSON.stringify(keys)!==JSON.stringify(afterKeys))throw new Error('Mock bagua reservation changed bag fields');
    for(const name of keys)if(name!=='maxglobalitemid'){const key=Memory.allocUtf8String(name);if(dump(get(before,key))!==dump(get(bag,key)))throw new Error('Mock bagua reservation changed bag content');}
    const dateline=Math.floor(Date.now()/1000);if(dateline<0||dateline>0x7fffffff)throw new Error('Offline Mock mail date exceeds supported range');
    const receipt=JSON.stringify({version:1,rid:10001,id,...(isOfflineDebugMailId(id)?{kind:'bagua'}:{}),phase:'offered',dateline,expired:Math.min(dateline+365*86400,0x7fffffff)}).slice(0,-1)+',"reward":['+dump(item)+']}';
    const update=fromText('{}');try{assign(member(update,Memory.allocUtf8String('bag')),bag);store.capture(update,false,undefined,receipt);}finally{dtor(update);}
    report({event:'offline-mock-bagua-instance-prepared',itemId:reward.A5});
   });}catch(error){failed=true;throw error;}
   finally{dtor(value);}
  },
  ensureMockBattlePetMail(masterRid,make,id=offlineMockBattlePetMailId){
   const pending=mockMailState(id);if(pending!==null&&pending.phase!=='requested')return;
   if(pending!==null&&offlineMockMailKind(pending)!=='pet')throw new Error('Wrong debug mail kind');
   if(pending===null&&id!==offlineMockBattlePetMailId)throw new Error('Missing debug mail request');
   store.pointResponse();
   masterRid=masterRid();
   if(!/^[1-9][0-9]*$/.test(masterRid)||!Number.isSafeInteger(Number(masterRid)))throw new Error('Unsupported Mock pet owner identity');
   const template=offlineMockBattlePetTemplate(),value=fromText(JSON.stringify({...template,master_unique_rid:Number(masterRid)}));
   try{make(value,(pet,before,after)=>{
    if(!validMockBattlePet(store.readRequest(pet)))throw new Error('Mock pet native template is invalid');
    petSnapshot(before);petSnapshot(after);
    if(dump(before)!==dump(after))throw new Error('Mock pet preview changed the current pet bag');
    const dateline=Math.floor(Date.now()/1000);if(dateline<0||dateline>0x7fffffff)throw new Error('Offline Mock mail date exceeds supported range');
    const receipt=JSON.stringify({version:1,rid:10001,id,...(isOfflineDebugMailId(id)?{kind:'pet'}:{}),phase:'offered',dateline,expired:Math.min(dateline+365*86400,0x7fffffff)}).slice(0,-1)+',"reward":['+dump(pet)+']}';
    const source=fromText('{}');try{store.capture(source,false,undefined,receipt);}finally{dtor(source);}
   });}catch(error){failed=true;throw error;}
   finally{dtor(value);}
  },
  mockPetBefore(pet,bag){
   const snapshot=petSnapshot(pet);
   if(snapshot.petinfo.length>=snapshot.bagsize)throw new Error('Mock pet bag is full');
   const savedPet=get(baseline,Memory.allocUtf8String('pet')),savedBag=get(baseline,Memory.allocUtf8String('bag'));
   if(dump(pet)!==dump(savedPet)||dump(bag)!==dump(savedBag))throw new Error('Mock pet claim snapshot changed before delivery');
   return {pet:dump(pet),bag:dump(bag)};
  },
  verifyMockPetSnapshot(pet,bag,before,id=offlineMockBattlePetMailId){
   const snapshot=petSnapshot(pet),previous=JSON.parse(before.pet),state=mockMailState(id);
   if(state?.phase!=='claiming'||dump(bag)!==before.bag||snapshot.bagsize!==previous.bagsize||snapshot.petinfo.length!==previous.petinfo.length+1)throw new Error('Mock pet grant changed an unrelated bag or pet');
   const previousValue=fromText(before.pet),oldArray=get(previousValue,Memory.allocUtf8String('petinfo')),newArray=get(pet,Memory.allocUtf8String('petinfo'));
   try{
    const oldIds=new Set(previous.petinfo.map(item=>item.petid)),added=snapshot.petinfo.filter(item=>!oldIds.has(item.petid));
    if(added.length!==1||added[0].petid<previous.maxglobalpetid||snapshot.maxglobalpetid<=added[0].petid)throw new Error('Mock pet native ID allocation is invalid');
    for(let index=0;index<previous.petinfo.length;index++){
     const position=snapshot.petinfo.findIndex(item=>item.petid===previous.petinfo[index].petid);
     if(position<0||dump(arrayElement(oldArray,index))!==dump(arrayElement(newArray,position)))throw new Error('Mock pet grant changed an existing pet');
    }
    const expected=state.reward[0],actual=added[0],keys=Object.keys(expected).sort();
    if(JSON.stringify(keys)!==JSON.stringify(Object.keys(actual).sort())||keys.some(key=>key!=='petid'&&JSON.stringify(expected[key])!==JSON.stringify(actual[key])))throw new Error('Mock pet grant does not match its attachment');
   }finally{dtor(previousValue);}
  },
  assertSameMockItem:assertSameItem,
  verifyMockBaguaSnapshot(bag,before,id=offlineMockBaguaMailId){
   const state=mockMailState(id);if(state===null)throw new Error('Mock bagua receipt is missing');
   const snapshot=store.readRequest(bag),itemId=state.reward[0].A5;
   if(!Array.isArray(snapshot.item)||!Number.isInteger(snapshot.maxglobalitemid)||snapshot.maxglobalitemid<=itemId||snapshot.maxglobalitemid>0xffffffff)throw new Error('Mock bagua bag snapshot is incomplete');
   const indices=snapshot.item.flatMap((item,index)=>item?.A5===itemId?[index]:[]);
   const count=value=>value!==null&&typeof value==='object'?(value.A5===itemId?1:0)+Object.values(value).reduce((sum,item)=>sum+count(item),0):0;
   if(indices.length!==(before?0:1)||count(snapshot)!==indices.length)throw new Error('Mock bagua instance count is incorrect');
   if(!before)assertSameItem(arrayElement(mailReward(id),0),arrayElement(get(bag,Memory.allocUtf8String('item')),indices[0]));
  },
  prepareMockMailClaim(source,request,pet,bag){
   validateOfflineMockMailClaim(request);
   const state=mockMailState(request.id);if(state===null||!['offered','claiming'].includes(state.phase))throw new Error('Offline Mock mail is not available');
   store.pointResponse();
   // 发奖前的写入失败仅在确认主文件未变时允许原界面重试。
   try{
   // 同一次原请求的完整保存结果与领取中收据先落盘；不再调用 full builder。
   if(store.mockMailKind(request.id)==='pet'){
    if(pet===undefined||bag===undefined)throw new Error('Mock pet claim requires native pet and bag snapshots');
    const snapshot=petSnapshot(pet);if(snapshot.petinfo.length>=snapshot.bagsize)throw new Error('Mock pet bag is full');
    const complete=Memory.alloc(0x18);copy(complete,source);
    try{assign(member(complete,Memory.allocUtf8String('pet')),pet);assign(member(complete,Memory.allocUtf8String('bag')),bag);store.capture(complete,false,undefined,mailPhase(request.id,'claiming'));}
    finally{dtor(complete);}
   }else store.capture(source,false,undefined,mailPhase(request.id,'claiming'));
   }catch(error){
    if(failed&&error.offlineSaveBeforeReplace===true&&baseline!==null){
     let disk=null;
     try{disk=loadDisk();if(disk!==null&&dump(disk)===dump(baseline)){failed=false;report({event:'offline-mock-mail-storage-retryable',id:request.id});}}
     catch(checkError){report({event:'offline-mock-mail-storage-check-failed',error:checkError.message});}
     finally{if(disk!==null)dtor(disk);}
    }
    throw error;
   }
   return mockMailResponse(mailRows(request.id),mailReward(request.id));
  },
  pendingMockMail(id=offlineMockMailId){const state=mockMailState(id);return state?.phase==='claiming'?state:null;},
  commitMockMailReward(bag,pointText,id=offlineMockMailId,pet){
   const state=mockMailState(id);if(state?.phase!=='claiming')throw new Error('Offline Mock mail has no pending claim');
   const source=fromText('{}'),point=fromText(pointText);
   try{assign(member(source,Memory.allocUtf8String('bag')),bag);assign(member(source,pointKey),point);if(store.mockMailKind(id)==='pet'){if(pet===undefined)throw new Error('Mock pet commit requires its native snapshot');petSnapshot(pet);assign(member(source,Memory.allocUtf8String('pet')),pet);}store.capture(source,false,undefined,mailPhase(id,'committed'));}
   finally{dtor(point);dtor(source);}
  },
  missionResponse(source){
   store.capture(source,false);
   const pointResponse=store.pointResponse();
   const story=offlineMissionTasks(JSON.parse(dump(baseline)));
   const update=fromText(JSON.stringify({mire:{storytask:story}}));
   try{store.capture(update,false);}finally{dtor(update);}
   return pointResponse.slice(0,-1)+',"storytask":'+JSON.stringify(story)+'}';
  },
  roleResponse(){
   if(baseline===null)throw new Error('No offline save exists');
   const keys=Object.keys(JSON.parse(dump(baseline)));
   const fields=keys.filter(key=>key!=='interaction_data'&&key!=='mire'&&key!=='_offline_lottery'&&key!=='_offline_mock_mail'&&key!=='_offline_mock_bagua'&&key!=='_offline_mock_pet'&&!key.startsWith('_offline_debug_mail_')).map(key=>JSON.stringify(key)+':'+dump(get(baseline,Memory.allocUtf8String(key))));
   const mireKey=Memory.allocUtf8String('mire');
   return '{"code":1000,"rid":"10001","server":1,"service_name":"Offline 1","username":"Wukong","cur_role_id":1,"online":[],"savedata":{'+fields.join(',')+'},"mire":'+(has(baseline,mireKey)?dump(get(baseline,mireKey)):'{}')+'}';
  },
  level(){if(baseline===null)return 1;return validate(dump(baseline)).roledata.role.rolelv;},
  readRequest(source){return JSON.parse(dump(source));},
  capturePet(pet,request){
   if(!request||Array.isArray(request)||Object.keys(request).some(key=>!['rid','pet_id','state'].includes(key))||request.rid!==10001||request.state!==1||!Number.isInteger(request.pet_id)||request.pet_id<1||request.pet_id>0x7fffffff)throw new Error('Unsupported offline pet state request');
   const snapshot=store.readRequest(pet),uint32=value=>Number.isInteger(value)&&value>=0&&value<=0xffffffff;
   if(!snapshot||Array.isArray(snapshot)||!Array.isArray(snapshot.petinfo)||!uint32(snapshot.bagsize)||!uint32(snapshot.maxglobalpetid))throw new Error('Offline pet state is missing its complete snapshot');
   const ids=new Set();let target=null;
   for(const item of snapshot.petinfo){
    if(!item||Array.isArray(item)||!uint32(item.petid)||item.petid===0||ids.has(item.petid))throw new Error('Invalid offline pet snapshot identity');
    ids.add(item.petid);if(item.petid===request.pet_id)target=item;
   }
   if(target?.tamestate!==1)throw new Error('Offline pet has not entered its native battle state');
   const update=fromText('{}');
   try{assign(member(update,Memory.allocUtf8String('pet')),pet);store.capture(update,false);}
   finally{dtor(update);}
  },
  pendingLottery(){const state=lotteryState();return state?.phase==='offered'||state?.phase==='drawn'?state:null;},
  recoverLotteryReward(apply){
   let state=lotteryState();
   // 单机断点规则：未提交 cmd39 的弃牌选择未保存，按完整牌池抽一次并先持久化。
   if(state?.phase==='offered'){store.prepareLottery({levelid:state.levelid,removed:[]});state=lotteryState();}
   if(state?.phase!=='drawn')return false;
   const value=fromText(JSON.stringify(state.reward[0]));
   try{apply(value,state.reward[0]);return true;}finally{dtor(value);}
  },
  beginLottery(levelid){
   offlineLotteryPool(levelid);
   const previous=lotteryState();
   if(previous?.phase==='offered'||previous?.phase==='drawn')throw new Error('Offline lottery reward is pending');
   if(previous?.phase==='entered'&&previous.levelid===levelid)return previous.round;
   const round=(previous?.round||0)+1;if(!Number.isSafeInteger(round))throw new Error('Offline lottery round limit reached');
   writeLottery({version:1,round,phase:'entered',levelid});return round;
  },
  captureOrdinaryLeave(source,request){
   if(typeof request.result!=='boolean'||!Number.isSafeInteger(request.battleresult)||request.result!==(request.battleresult===1))throw new Error('Invalid offline leave result');
   if(!request.result){store.capture(source,false);return '{"code":1000}';}
   if(request.levelid!==700002&&request.levelid!==700003){
    // 引导与未重建牌池的关卡继续保留原通关存档；cmd39 仍严格拒绝未支持奖励。
    store.capture(source,false);return '{"code":1000}';
   }
   const pool=offlineLotteryPool(request.levelid),previous=lotteryState();
   if(!previous||previous.levelid!==request.levelid)throw new Error('Offline lottery has no entered round');
   if(!has(baseline,pointKey))throw new Error('Offline point snapshot is missing');
   if(previous.phase==='entered')store.capture(source,false,{version:1,round:previous.round,phase:'offered',levelid:request.levelid});
   else if(previous.levelid!==request.levelid)throw new Error('Offline lottery leave does not match its round');
   return '{"code":1000,"point":'+dump(get(baseline,pointKey))+',"discardcost":0,"list":'+JSON.stringify(pool)+'}';
  },
  prepareLottery(request){
   const state=lotteryState(),removed=offlineLotteryRemoved(request.levelid,request.removed);
   if(!state||state.levelid!==request.levelid||!['offered','drawn'].includes(state.phase))throw new Error('Offline lottery is not available for this round');
   if(state.phase==='offered'){
    state.phase='drawn';state.removed=removed;state.reward=drawOfflineLottery(request.levelid,removed);writeLottery(state);
   }else if(JSON.stringify(state.removed)!==JSON.stringify(removed))throw new Error('Offline lottery retry changed removed indices');
   return '{"code":1000,"reward":'+JSON.stringify(state.reward)+'}';
  },
  commitLotteryReward(bag,pointText){
   const state=lotteryState();if(state?.phase!=='drawn')throw new Error('Offline lottery has no prepared reward');
   const source=fromText('{}'),point=fromText(pointText);
   try{
    assign(member(source,Memory.allocUtf8String('bag')),bag);assign(member(source,pointKey),point);
    store.capture(source,false,{...state,phase:'committed'});
   }finally{dtor(point);dtor(source);}
  },
  blockLottery(){failed=true;},
  capture(source,isCreate,lottery,mockMail){
   if(failed)throw new Error('Offline storage previously failed; restart after resolving storage error');
   const candidate=Memory.alloc(0x18);
   if(isCreate)copy(candidate,source);
   else{if(baseline===null)throw new Error('Cannot save a partial profile without its baseline');copy(candidate,baseline);}
   try{
    if(!isCreate){
     const incoming=JSON.parse(dump(source)),keys=validateSaveUpdate(incoming);
     for(const name of keys){
      // 原客户端用此标记决定联网失败后是否退回登录，不属于角色状态。
      if(name==='eggdata'||name==='novice_boot_task_progress'||name==='is_saved_from')continue;
      const key=Memory.allocUtf8String(name);
      if(name==='mire'){
       const storyKey=Memory.allocUtf8String('storytask'),module=get(source,key);
       if(has(module,storyKey))assign(member(member(candidate,key),storyKey),get(module,storyKey));
      }else assign(member(candidate,key),get(source,key));
     }
    }
    if(isCreate&&!has(candidate,pointKey)){const zero=fromText('0');try{assign(member(candidate,pointKey),zero);}finally{dtor(zero);}}
    if(lottery!==undefined){const value=fromText(JSON.stringify(lottery));try{assign(member(candidate,lotteryKey),value);}finally{dtor(value);}}
    if(mockMail!==undefined){const text=typeof mockMail==='string'?mockMail:JSON.stringify(mockMail),value=fromText(text);try{assign(member(candidate,mailKey(JSON.parse(text).id)),value);}finally{dtor(value);}}
    const text=dump(candidate);validate(text);const length=commit(text);
    if(baseline!==null)dtor(baseline);baseline=candidate;
    report({event:'offline-save-committed',bytes:length,create:isCreate});
   }catch(error){failed=true;dtor(candidate);throw error;}
  }
 };
 return store;
}

function configureOfflinePetState(game,store){
 const at=offset=>game.base.add(offset);
 for(const [offset,first,second] of [[0x2bff884,0xd102c3ff,0xa90053f3],[0x2c1348c,0xd10083ff,0xa90053f3],[0x2c1ab40,0xf001dac2,0xd10443ff],[0x2ab7c78,0xd102c3ff,0xa9015bf5],[0x2a7d980,0xd100c3ff,0xa90053f3]])if(at(offset).readU32()!==first||at(offset+4).readU32()!==second)throw new Error('Pet state native entry fingerprint mismatch: '+offset.toString(16));
 const getPetManager=new NativeFunction(at(0x2c1348c),'pointer',[]),destroyValue=new NativeFunction(at(0x3d2a33c),'void',['pointer']);
 const senders=new Map(),pendingSenders=new Map(),preparedRequests=new Set();let thunk=null,serializePet=null;
 Interceptor.attach(at(0x2bff884),{
  onEnter(args){
   this.previous=senders.get(this.threadId);senders.delete(this.threadId);
   if(args[2].toInt32()===1&&!args[1].isNull()&&store.exists()&&store.healthy()&&args[0].equals(getPetManager()))senders.set(this.threadId,true);
  },
  onLeave(){if(this.previous===undefined)senders.delete(this.threadId);else senders.set(this.threadId,this.previous);}
 });
 Interceptor.attach(at(0x2ab7c78),{
  onEnter(args){
   this.previousPrepared=pendingSenders.get(this.threadId);pendingSenders.delete(this.threadId);
   if(!senders.has(this.threadId)||args[1].toInt32()!==478||args[4].isNull()||args[4].readUtf8String()!=='REQUEST_PET_SET_TAMESTATE'||!store.exists()||!store.healthy())return;
   let snapshot=null,constructed=false;
   try{
    const request=store.readRequest(args[2]);
    if(request.rid!==10001||request.state!==1)throw new Error('Unsupported offline pet state request');
    if(serializePet===null){
     thunk=Memory.alloc(Process.pageSize);if(!Memory.protect(thunk,Process.pageSize,'r-x'))throw new Error('Offline pet serializer allocation failed');
     Memory.patchCode(thunk,8,code=>{code.writeU32(0xaa0103e8);code.add(4).writeU32(0xd61f0040);});
     serializePet=new NativeFunction(thunk,'void',['pointer','pointer','pointer']);
    }
    // 出战在原 sender 前已完成；只序列化 PetMgr，不二次调用会消耗增量的 full builder。
    snapshot=Memory.alloc(0x18);serializePet(getPetManager(),snapshot,at(0x2c1ab40));constructed=true;
    store.capturePet(snapshot,request);pendingSenders.set(this.threadId,true);
    report({event:'offline-pet-state-prepared',petId:request.pet_id,state:request.state});
   }catch(error){report({event:'offline-pet-state-rejected',error:error.message});}
   finally{if(constructed)destroyValue(snapshot);}
  },
  onLeave(){if(this.previousPrepared===undefined)pendingSenders.delete(this.threadId);else pendingSenders.set(this.threadId,this.previousPrepared);}
 });
 // 普通 sender 不返回 request；在 2ab8770 的真实入队点绑定，早于 request release。
 Interceptor.attach(at(0x2a7d980),{onEnter(args){
  const request=args[1];if(request.isNull())return;
  const identity=request.toString();preparedRequests.delete(identity);
  if(!this.returnAddress.equals(at(0x2ab8c74))||!pendingSenders.has(this.threadId)||!store.healthy())return;
  const tag=request.add(0x40).readPointer();
  if(!tag.isNull()&&tag.readUtf8String()==='REQUEST_PET_SET_TAMESTATE')preparedRequests.add(identity);
 }});
 return request=>preparedRequests.has(request.toString())&&store.exists()&&store.healthy();
}

function configureRoleWire(game,store,isPreparedPetRequest=()=>false){
const at=x=>game.base.add(x);
const recoveryEntries=[
 [0x2fedf74,0xd12843ff,0xd101c3ff],[0x3c6b750,0xd101c3ff,0x52800001],
 [0x4ffd82c,0xa9ba7bfd,0x52800209],[0x2d41900,0xd10503ff,0xeb02001f],
 [0x4e13d28,0xd10043ff,0xa9007bf3],[0x4e13da8,0xd10043ff,0xa9007bf3],
 [0x29839d4,0xd10243ff,0x52800003],
];
for(const [offset,first,second] of recoveryEntries)if(at(offset).readU32()!==first||at(offset+4).readU32()!==second)throw new Error('Lottery recovery native entry fingerprint mismatch: '+offset.toString(16));
const localTags=new Set(['REQUEST_CREATE_ROLE','REQUEST_ROLE_DATA','REQUEST_NEW_ROLE_NAME','REQUEST_SAVE_DATA','REQUEST_LEAVE_LEVEL','REQUEST_LEVEL_LEAVE_NEW','REQUEST_LEVEL_LOTTERY','REQUEST_LOGIN_HEART_BEAT','common_net_levelmapdata','REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER','REQUEST_WILD_BOSS_LEVEL_INFO','REQUEST_GET_OPEN_GROUP_LEVELS','REQUEST_POINT','REQUEST_RECEIVE_BULLETIN','REQUEST_MISSION_LIST']);
localTags.add('REQUEST_REQUEST_MAIL_LIST_NEW');localTags.add('REQUEST_MAIL_RECIEVE_REWARD');
const prepared=new Map();
const ownRoleInfoRequests=new Set();
let leaveResponse=null,missionResponse=null,lotteryPrepared=null,lotteryDelivery=null,entryRequest=null,entryDelivered=null;
const mockMailRequests=new Map(),mockMailDeliveries=new Map(),mockMailFailures=new Map();
const saveCommands=new Map([[65,'REQUEST_CREATE_ROLE'],[4,'REQUEST_SAVE_DATA'],[38,'REQUEST_LEAVE_LEVEL'],[548,'REQUEST_LEVEL_LEAVE_NEW'],[24,'REQUEST_MISSION_LIST']]);
const assignBody=new NativeFunction(at(0x2a7da54),'void',['pointer','pointer','pointer']);
const malloc=new NativeFunction(Module.getExportByName('libc.so','malloc'),'pointer',['ulong']);
const strlen=new NativeFunction(Module.getExportByName('libc.so','strlen'),'ulong',['pointer']);
const hasMember=new NativeFunction(at(0x3d295b8),'bool',['pointer','pointer']);
const getMember=new NativeFunction(at(0x3d2957c),'pointer',['pointer','pointer']);
const savedataKey=Memory.allocUtf8String('savedata');
function tagOf(req){const p=req.add(0x40).readPointer();return p.isNull()?'':p.readUtf8String();}
function isLocalRequest(req){
 const tag=tagOf(req);
 return localTags.has(tag)||(tag==='REQUEST_ROLE_INFO_2'&&ownRoleInfoRequests.has(req.toString())&&store.exists()&&store.healthy())||(tag==='REQUEST_PET_SET_TAMESTATE'&&isPreparedPetRequest(req)&&store.exists()&&store.healthy());
}
if(at(0x2ab9290).readU32()!==0xd10483ff||at(0x2ab9294).readU32()!==0xa9036bf9)throw new Error('Mock mail request entry fingerprint mismatch');
Interceptor.attach(at(0x2ab9290),{
 onEnter(args){
  this.ownRoleInfo=false;this.mockMailResponse=null;this.mockMailFailure=null;
  const command=args[1].toInt32(),tag=args[4].isNull()?'':args[4].readUtf8String();
  if((command===552&&tag==='REQUEST_REQUEST_MAIL_LIST_NEW')||(command===14&&tag==='REQUEST_MAIL_RECIEVE_REWARD')){
   try{
    if(!this.returnAddress.equals(at(0x2af36e0)))throw new Error('Unsupported Mock mail request caller');
    let text;const request=store.readRequest(args[2]);
    if(command===552){if(validateOfflineMockMailList(request)){ensureMockBaguaMail();ensureMockBattlePetMail();for(const mail of store.debugMailRequests()){if(mail.kind==='pet')ensureMockBattlePetMail(mail.id);else if(mail.kind==='bagua')ensureMockBaguaMail(mail.id);else store.ensureMockPillMail(mail.id);}}text=store.mockMailList(request);}
    else{
     validateOfflineMockMailClaim(request);
     const failure={tag,id:request.id,text:JSON.stringify({code:-1,message:'Offline mail claim failed; no reward delivered',offline_mail_id:request.id}),failed:true};
     this.mockMailFailure=failure;
     if(mockMailDeliveries.get(request.id)?.used)throw new Error('Offline Mock mail claim was already delivered');
     if(!hasMember(args[2],savedataKey))throw new Error('Mock mail claim is missing its savedata');
     const source=getMember(args[2],savedataKey);
     const kind=store.mockMailKind(request.id);
     if(mockMailDeliveries.has(request.id))mockMailDeliveries.delete(request.id);
     text=kind==='pet'?withBagSnapshot(bag=>withPetSnapshot(pet=>store.prepareMockMailClaim(source,request,pet,bag))):store.prepareMockMailClaim(source,request);
    }
    this.mockMailResponse={tag,text,id:request.id};
   }catch(error){if(this.mockMailFailure!==null)this.mockMailResponse=this.mockMailFailure;report({event:command===552?'offline-mock-mail-list-rejected':'offline-mock-mail-claim-rejected',error:error.message});}
   return;
  }
  if(command!==168||tag!=='REQUEST_ROLE_INFO_2'||!store.exists()||!store.healthy())return;
  try{const request=store.readRequest(args[2]);this.ownRoleInfo=request.rid===10001&&Number.isFinite(request.cur_power);}
  catch(error){report({event:'offline-role-info-request-rejected',error:error.message});}
 },
 onLeave(request){
  if(request.isNull())return;
  mockMailRequests.delete(request.toString());
  if(this.mockMailResponse!==null&&(this.mockMailResponse.failed||store.healthy()))mockMailRequests.set(request.toString(),this.mockMailResponse);
  ownRoleInfoRequests.delete(request.toString());
  if(this.ownRoleInfo)ownRoleInfoRequests.add(request.toString());
 }
});
Interceptor.attach(at(0x2ab7c78),{onEnter(args){
 const command=args[1].toInt32(),tag=args[4].isNull()?'':args[4].readUtf8String();
 if(command===37&&tag==='REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER'){
  entryRequest=null;
  try{const request=store.readRequest(args[2]);offlineLotteryPool(request.levelid);entryRequest=request.levelid;}
  catch(error){report({event:'offline-lottery-entry-not-prepared',error:error.message});}
  return;
 }
 if(command===39&&tag==='REQUEST_LEVEL_LOTTERY'){
  lotteryPrepared=null;
  try{lotteryPrepared=store.prepareLottery(store.readRequest(args[2]));}
  catch(error){report({event:'offline-lottery-request-rejected',error:error.message});}
  return;
 }
 if(saveCommands.get(command)!==tag)return;
 try{
  if(command===38)leaveResponse=null;
  if(command===24)missionResponse=null;
  if(hasMember(args[2],savedataKey)){
   if(command===38)leaveResponse=store.captureOrdinaryLeave(getMember(args[2],savedataKey),store.readRequest(args[2]));
   else if(command===24)missionResponse=store.missionResponse(getMember(args[2],savedataKey));
   else store.capture(getMember(args[2],savedataKey),command===65);
  }
  else if(command===38)throw new Error('Ordinary leave is missing its savedata');
  else if(command===24)throw new Error('Mission list is missing its savedata');
  else if(!store.exists()||command===65||command===4)throw new Error('Request is missing its savedata');
  prepared.set(tag,true);report({event:'offline-save-request-prepared',tag});
 }catch(error){prepared.set(tag,false);report({event:'offline-save-request-failed',tag,error:error.message});}
}});
Interceptor.attach(at(0x2ab75d8),{onEnter(args){
 const raw=args[2],req=raw.add(0x18).readPointer(),tag=tagOf(req);if(!isLocalRequest(req))return;
 let text;
 if(Array.from(saveCommands.values()).includes(tag)&&(!store.healthy()||prepared.get(tag)!==true)){report({event:'local-response-blocked-uncommitted-save',tag});return;}
 if(tag==='REQUEST_WILD_BOSS_LEVEL_INFO')text='{"code":1000,"wild_boss_info":{}}';
 else if(tag==='REQUEST_GET_OPEN_GROUP_LEVELS')text='{"code":1000,"levels":[]}';
 else if(tag==='REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER'){text='{"code":1000,"state":0}';entryDelivered=entryRequest;}
 else if(tag==='common_net_levelmapdata')text='{"code":1000}';
 else if(tag==='REQUEST_CREATE_ROLE')text='{"code":1000,"rid":"10001"}';
 else if(tag==='REQUEST_LEAVE_LEVEL')text=leaveResponse;
 else if(tag==='REQUEST_MISSION_LIST')text=missionResponse;
 else if(tag==='REQUEST_REQUEST_MAIL_LIST_NEW'){
  const preparedMail=mockMailRequests.get(req.toString());
  if(!store.healthy()||preparedMail?.tag!==tag){report({event:'offline-mock-mail-list-blocked'});return;}
  text=preparedMail.text;
 }
 else if(tag==='REQUEST_MAIL_RECIEVE_REWARD'){
  const preparedMail=mockMailRequests.get(req.toString());
  if(preparedMail?.tag===tag&&preparedMail.failed){text=preparedMail.text;mockMailFailures.set(preparedMail.id,{text,used:false});}
  else{
  if(!store.healthy()||preparedMail?.tag!==tag||mockMailDeliveries.has(preparedMail.id)){report({event:'offline-mock-mail-response-blocked'});return;}
  text=preparedMail.text;mockMailFailures.delete(preparedMail.id);mockMailDeliveries.set(preparedMail.id,{text,id:preparedMail.id,used:false,committed:false});
  }
 }
 else if(tag==='REQUEST_LEVEL_LOTTERY'){
  if(!store.healthy()||lotteryPrepared===null||lotteryDelivery!==null){report({event:'offline-lottery-response-blocked'});return;}
  text=lotteryPrepared;lotteryDelivery={text,used:false};
 }
 else if(tag==='REQUEST_LOGIN_HEART_BEAT'||tag==='REQUEST_SAVE_DATA'||tag==='REQUEST_LEVEL_LEAVE_NEW')text='{"code":1000}';
 else if(tag==='REQUEST_NEW_ROLE_NAME')text='{"code":1000,"name":"Wukong"}';
 else if(tag==='REQUEST_RECEIVE_BULLETIN')text='{"code":1000,"message":""}';
 else if(tag==='REQUEST_ROLE_INFO_2')text='{"code":1000}';
 else if(tag==='REQUEST_PET_SET_TAMESTATE')text='{"code":1000}';
 else if(tag==='REQUEST_POINT'){
  if(!store.exists()){report({event:'point-response-blocked-no-savedata'});return;}
  text=store.pointResponse();
 }
 else{
  if(!store.exists()){report({event:'role-response-blocked-no-savedata'});return;}
  text=store.roleResponse();
 }
 const bytes=Memory.allocUtf8String(text),length=strlen(bytes).toNumber();assignBody(raw.add(0x28),bytes,bytes.add(length));
 raw.add(0x20).writeU8(1);raw.add(0x58).writeS64(200);report({event:'local-role-response',tag,bytes:length});
}});
const originalEnter=new NativeFunction(at(0x29839d4),'void',['pointer','int','int']);
Interceptor.replace(at(0x29839d4),new NativeCallback(function(manager,levelid,aux){
 const delivered=entryDelivered!==null&&entryDelivered===levelid;
 if(delivered){entryDelivered=null;entryRequest=null;}
 try{
  const pending=store.exists()?store.pendingLottery():null;
  if(pending){report({event:'offline-lottery-entry-blocked-pending',phase:pending.phase,levelid:pending.levelid,round:pending.round});return;}
  if(delivered){store.beginLottery(levelid);lotteryPrepared=null;lotteryDelivery=null;report({event:'offline-lottery-round-entered',levelid});}
 }catch(error){store.blockLottery();report({event:'offline-lottery-entry-save-failed',error:error.message});return;}
 originalEnter(manager,levelid,aux);
},'void',['pointer','int','int']));
Interceptor.attach(at(0x2a97c18),{onEnter(args){if(isLocalRequest(args[1]))args[4]=ptr(0);}});
const decoderAddress=at(0x3085f80);
const originalDecoder=new NativeFunction(decoderAddress,'void',['pointer','pointer','ulong','pointer','pointer','uint']);
Interceptor.replace(decoderAddress,new NativeCallback(function(key,src,srcLen,out,outLen,flags){
 const caller=this.returnAddress;
 if((caller.equals(at(0x2a8062c))||caller.equals(at(0x2a8082c)))&&isLocalRequest(this.context.x21)){
  const length=srcLen.toNumber();if(length>8*1024*1024)throw new Error('Local response exceeds limit');
  const buffer=malloc(length+1);if(buffer.isNull())throw new Error('Local response allocation failed');
  Memory.copy(buffer,src,length);buffer.add(length).writeU8(0);out.writePointer(buffer);if(!outLen.isNull())outLen.writeU64(length);
  report({event:'local-default-response-plaintext',bytes:length});return;
 }
 originalDecoder(key,src,srcLen,out,outLen,flags);
},'void',['pointer','pointer','ulong','pointer','pointer','uint']));
const lotteryHandler=at(0x29b9468),bagSerializer=at(0x2d4053c);
if(lotteryHandler.readU32()!==0xd10743ff||lotteryHandler.add(4).readU32()!==0xd10183ff||bagSerializer.readU32()!==0xd10dc3ff||bagSerializer.add(4).readU32()!==0xb001d1a1)throw new Error('Lottery native entry fingerprint mismatch');
const originalLottery=new NativeFunction(lotteryHandler,'void',['pointer','pointer']);
const getCenter=new NativeFunction(at(0x4e5f094),'pointer',[]);
const removeObserver=new NativeFunction(at(0x4e5f9c4),'void',['pointer','pointer','pointer']);
const post3=new NativeFunction(at(0x4e5f714),'void',['pointer','pointer','pointer']);
const post2=new NativeFunction(at(0x4e5f908),'void',['pointer','pointer']);
const getBag=new NativeFunction(at(0x2d1f964),'pointer',[]),getPlayer=new NativeFunction(at(0x30d0b74),'pointer',[]);
const getPetManager=new NativeFunction(at(0x2c1348c),'pointer',[]);
const destroyValue=new NativeFunction(at(0x3d2a33c),'void',['pointer']);
let activeLottery=null,activeMockMail=null,bagThunk=null,serializeBag=null;
function withBagSnapshot(use){
 if(serializeBag===null){
  bagThunk=Memory.alloc(Process.pageSize);if(!Memory.protect(bagThunk,Process.pageSize,'r-x'))throw new Error('Offline bag serializer allocation failed');
  Memory.patchCode(bagThunk,8,code=>{code.writeU32(0xaa0103e8);code.add(4).writeU32(0xd61f0040);});
  serializeBag=new NativeFunction(bagThunk,'void',['pointer','pointer','pointer']);
 }
 const bag=Memory.alloc(0x18);let constructed=false;
 try{serializeBag(getBag(),bag,bagSerializer);constructed=true;return use(bag);}
 finally{if(constructed)destroyValue(bag);}
}
function withPetSnapshot(use){
 if(serializeBag===null)throw new Error('Mock pet serializer is not initialized');
 const pet=Memory.alloc(0x18);let constructed=false;
 try{serializeBag(getPetManager(),pet,at(0x2c1ab40));constructed=true;return use(pet);}
 finally{if(constructed)destroyValue(pet);}
}
function currentPoint(){
 const player=getPlayer(),getPoint=new NativeFunction(player.readPointer().add(0x58).readPointer(),'int64',['pointer']);
 return getPoint(player).toString();
}
function rewardQuantity(bag,id){
 let quantity;
 if(id===503031)quantity=bag.spiritcount;
 else{
  if(!Array.isArray(bag.item))throw new Error('Offline recovery item snapshot is missing');
  quantity=0;
  for(const item of bag.item)if(item?.A2===id){
   if(!Number.isSafeInteger(item.A4)||item.A4<0)throw new Error('Invalid offline recovery item count');
   quantity+=item.A4;
  }
 }
 if(!Number.isSafeInteger(quantity)||quantity<0)throw new Error('Invalid offline recovery quantity');
 return quantity;
}
const itemFactory=new NativeFunction(at(0x3c6b750),'pointer',['pointer']);
const itemCast=new NativeFunction(at(0x4ffd82c),'pointer',['pointer','pointer','pointer','long']);
const retainItem=new NativeFunction(at(0x4e13d28),'void',['pointer']),releaseItem=new NativeFunction(at(0x4e13da8),'void',['pointer']);
const addItem=new NativeFunction(at(0x2d41900),'bool',['pointer','pointer','pointer','uint8','uint8','uint8']);
Interceptor.attach(at(0x2fedf74),{
 onEnter(){this.restoreLottery=this.returnAddress.equals(at(0x2ff7130));},
 onLeave(result){
  if(!this.restoreLottery||(result.toUInt32()&0xff)===0)return;
  try{
   const pending=store.pendingLottery();if(pending===null)return;
   store.recoverLotteryReward((value,reward)=>{
    const before=withBagSnapshot(bag=>rewardQuantity(store.readRequest(bag),reward.A2)),point=currentPoint();
    if(!Number.isSafeInteger(before+1))throw new Error('Offline recovery quantity exceeds supported range');
    const object=itemFactory(value);if(object.isNull())throw new Error('Offline recovery item factory failed');
    retainItem(object);
    try{
     const sourceType=at(0x67784d0).readPointer(),itemType=at(0x677f968).readPointer();
     if(sourceType.isNull()||itemType.isNull())throw new Error('Offline recovery item type metadata is missing');
     const item=itemCast(object,sourceType,itemType,0);
     if(item.isNull())throw new Error('Offline recovery item type is unsupported');
     const bag=getBag();if(!addItem(bag,item,bag,0,1,0))throw new Error('Offline recovery item was not accepted');
     withBagSnapshot(snapshot=>{
      const afterPoint=currentPoint();
      if(rewardQuantity(store.readRequest(snapshot),reward.A2)!==before+1||afterPoint!==point)throw new Error('Offline recovery snapshot does not match its reward');
      store.commitLotteryReward(snapshot,afterPoint);
     });
    }finally{releaseItem(object);}
   });
   report({event:'offline-lottery-recovered',levelid:pending.levelid,round:pending.round,phase:pending.phase});
  }catch(error){store.blockLottery();result.replace(ptr(0));report({event:'offline-lottery-recovery-failed',error:error.message});}
 }
});
const responseString=(response,offset)=>response.add(offset).readPointer().add(0x18).readPointer().readUtf8String();
Interceptor.replace(at(0x4e5f714),new NativeCallback(function(center,name,response){
 if(activeLottery!==null&&this.returnAddress.equals(at(0x29b9720))&&name.readUtf8String()==='REQUEST_DATA_HANDLED'){activeLottery.push([3,center,name,response]);return;}
 post3(center,name,response);
},'void',['pointer','pointer','pointer']));
Interceptor.replace(at(0x4e5f908),new NativeCallback(function(center,name){
 if(activeLottery!==null&&this.returnAddress.equals(at(0x29b9734))&&name.readUtf8String()==='GO_ON'){activeLottery.push([2,center,name]);return;}
 if(activeMockMail!==null&&this.returnAddress.equals(at(0x2afbe30))&&name.readUtf8String()==='GO_ON'){if(activeMockMail.committed)activeMockMail.notifications.push([center,name]);return;}
 post2(center,name);
},'void',['pointer','pointer']));
Interceptor.replace(lotteryHandler,new NativeCallback(function(manager,response){
 if(responseString(response,0x38)!=='REQUEST_LEVEL_LOTTERY'){originalLottery(manager,response);return;}
 if(!store.healthy()||lotteryDelivery===null||responseString(response,0x30)!==lotteryDelivery.text){report({event:'offline-lottery-native-response-rejected'});return;}
 if(lotteryDelivery.used){
  if(!lotteryDelivery.committed){report({event:'offline-lottery-native-response-in-progress'});return;}
  const center=getCenter();removeObserver(center,manager,Memory.allocUtf8String('REQUEST_DATA_GOTTEN'));
  post3(center,Memory.allocUtf8String('REQUEST_DATA_HANDLED'),response);post2(center,Memory.allocUtf8String('GO_ON'));
  report({event:'offline-lottery-native-replay-blocked'});return;
 }
 lotteryDelivery.used=true;activeLottery=[];
 try{
  originalLottery(manager,response);
  if(activeLottery.length!==2||activeLottery[0][0]!==3||activeLottery[1][0]!==2)throw new Error('Offline lottery handler did not finish');
  withBagSnapshot(bag=>store.commitLotteryReward(bag,currentPoint()));
  lotteryDelivery.committed=true;
  const notifications=activeLottery;activeLottery=null;
  for(const [kind,...args] of notifications){if(kind===3)post3(...args);else post2(...args);}
  report({event:'offline-lottery-reward-committed'});
 }catch(error){store.blockLottery();report({event:'offline-lottery-commit-failed',error:error.message});}
 finally{activeLottery=null;}
},'void',['pointer','pointer']));
const mockMailHandler=at(0x2afba4c),mockMailAck=at(0x2fe924c),mockMailClear=at(0x2fea720);
for(const [entry,first,second] of [[mockMailHandler,0xd10703ff,0xd10183ff],[mockMailAck,0xd100c3ff,0xa9015bf5],[mockMailClear,0xd10143ff,0xa90053f3]])if(entry.readU32()!==first||entry.add(4).readU32()!==second)throw new Error('Mock mail native entry fingerprint mismatch');
for(const [offset,first,second] of [[0x3c85cac,0xd10443ff,0x6d04a7e8],[0x3d293b8,0xd101c3ff,0xa90053f3]])if(at(offset).readU32()!==first||at(offset+4).readU32()!==second)throw new Error('Mock bagua native entry fingerprint mismatch');
for(const [offset,first,second] of [[0x3c93dd4,0xd10183ff,0xd2800101],[0x3a0c618,0xd10cc3ff,0xb0016b42],[0x2c1ab40,0xf001dac2,0xd10443ff],[0x2c1348c,0xd10083ff,0xa90053f3],[0x2fecd6c,0xd10083ff,0xa90053f3],[0x2fe19a4,0xd10103ff,0xd0012141],[0x2fe1a98,0xd10143ff,0xa90053f3]])if(at(offset).readU32()!==first||at(offset+4).readU32()!==second)throw new Error('Mock pet native entry fingerprint mismatch');
function withMockBaguaItem(value,use){
 const object=itemFactory(value);if(object.isNull())throw new Error('Mock bagua native factory failed');
 retainItem(object);const output=Memory.alloc(0x18);let constructed=false;
 try{
  const item=itemCast(object,at(0x67784d0).readPointer(),at(0x677f968).readPointer(),0);
  if(item.isNull()||!item.readPointer().add(0xb8).readPointer().equals(at(0x3c85cac)))throw new Error('Mock bagua native item type is unsupported');
  serializeBag(item,output,at(0x3c85cac));constructed=true;return use(output);
 }finally{if(constructed)destroyValue(output);releaseItem(object);}
}
function ensureMockBaguaMail(id=offlineMockBaguaMailId){
 store.ensureMockBaguaMail((value,save)=>withBagSnapshot(before=>{
  const point=currentPoint();
  withMockBaguaItem(value,item=>withMockBaguaItem(item,restored=>{
   store.assertSameMockItem(item,restored);
   withBagSnapshot(bag=>{if(currentPoint()!==point)throw new Error('Mock bagua factory changed points');save(item,before,bag);});
  }));
 }),id);
}
function withMockBattlePet(value,use){
 const object=itemFactory(value);if(object.isNull())throw new Error('Mock pet native factory failed');
 retainItem(object);const output=Memory.alloc(0x18);let constructed=false;
 try{
  const item=itemCast(object,at(0x67784d0).readPointer(),at(0x67776e0).readPointer(),0);
  if(item.isNull()||!item.readPointer().equals(at(0x65d2160)))throw new Error('Mock pet reward type is unsupported');
  const unwrap=new NativeFunction(at(0x3c93dd4),'pointer',['pointer']),pet=unwrap(item);
  if(pet.isNull()||!pet.readPointer().add(0x1a58).readPointer().equals(at(0x3a0c618)))throw new Error('Mock pet serializer type is unsupported');
  const stage=new NativeFunction(pet.readPointer().add(0x1800).readPointer(),'uint',['pointer']);
  if(stage(pet)!==5)throw new Error('Mock pet is not its native final form');
  serializeBag(pet,output,at(0x3a0c618));constructed=true;return use(output);
 }finally{if(constructed)destroyValue(output);releaseItem(object);}
}
function ensureMockBattlePetMail(id=offlineMockBattlePetMailId){
 store.ensureMockBattlePetMail(()=>{
  // 原 Pet 初始化使用 SaveMgr 的角色/区服 ID；Player v+0x98 返回 Role 指针。
  const manager=new NativeFunction(at(0x2fecd6c),'pointer',[])();if(manager.isNull())throw new Error('Unsupported Mock pet owner identity');
  const roleId=new NativeFunction(at(0x2fe19a4),'int',['pointer'])(manager),serviceId=new NativeFunction(at(0x2fe1a98),'int',['pointer'])(manager);
  if(roleId<1||roleId>=100000000||serviceId<0)throw new Error('Unsupported Mock pet owner identity');
  return String(serviceId*100000000+roleId);
 },(value,save)=>withBagSnapshot(()=>withPetSnapshot(before=>{
  const point=currentPoint();
  withMockBattlePet(value,pet=>withMockBattlePet(pet,restored=>{
   store.assertSameMockItem(pet,restored);
   withPetSnapshot(after=>{if(currentPoint()!==point)throw new Error('Mock pet preview changed points');save(pet,before,after);});
  }));
 })),id);
}
const originalMockMail=new NativeFunction(mockMailHandler,'void',['pointer','pointer']);
const originalMockMailAck=new NativeFunction(mockMailAck,'void',['pointer','pointer']);
const originalMockMailClear=new NativeFunction(mockMailClear,'void',['pointer']);
Interceptor.replace(mockMailAck,new NativeCallback(function(manager,root){
 const active=activeMockMail;
 if(active===null||!this.returnAddress.equals(at(0x2afc4fc))){originalMockMailAck(manager,root);return;}
 active.ackCount++;
 try{
  if(active.ackCount!==1||!store.healthy())throw new Error('Mock mail ACK is not available');
  // 原入包已完成、原 ACK 尚未执行；成功落盘后才允许 ACK 和清 dirty。
  withBagSnapshot(snapshot=>{
   const point=currentPoint();
   if(store.mockMailKind(active.id)==='pet'){
    if(point!==active.point)throw new Error('Mock mail changed points');
    withPetSnapshot(pet=>{store.verifyMockPetSnapshot(pet,snapshot,active.before,active.id);store.commitMockMailReward(snapshot,point,active.id,pet);});
    return;
   }
   if(store.mockMailKind(active.id)==='bagua')store.verifyMockBaguaSnapshot(snapshot,false,active.id);
   else if(rewardQuantity(store.readRequest(snapshot),504100)!==active.before+1)throw new Error('Mock mail snapshot does not match its attachment');
   if(point!==active.point)throw new Error('Mock mail changed points');
   store.commitMockMailReward(snapshot,point,active.id);
  });
  active.committed=true;active.delivery.committed=true;
  originalMockMailAck(manager,root);
 }catch(error){store.blockLottery();report({event:'offline-mock-mail-commit-failed',error:error.message});}
},'void',['pointer','pointer']));
Interceptor.replace(mockMailClear,new NativeCallback(function(manager){
 const active=activeMockMail;
 if(active===null||!this.returnAddress.equals(at(0x2afc504))){originalMockMailClear(manager);return;}
 active.clearCount++;
 if(!active.committed||!store.healthy())return;
 try{if(active.clearCount!==1)throw new Error('Mock mail clear was repeated');originalMockMailClear(manager);}
 catch(error){store.blockLottery();report({event:'offline-mock-mail-clear-failed',error:error.message});}
},'void',['pointer']));
Interceptor.replace(mockMailHandler,new NativeCallback(function(manager,response){
 if(response.isNull()||responseString(response,0x38)!=='REQUEST_MAIL_RECIEVE_REWARD'){originalMockMail(manager,response);return;}
 if(!response.readPointer().equals(at(0x6045ea0))){report({event:'offline-mock-mail-response-rejected'});return;}
 const getMailId=new NativeFunction(response.readPointer().add(0x70).readPointer(),'pointer',['pointer']);
 const id=getMailId(response).toInt32(),mockMailDelivery=mockMailDeliveries.get(id),failure=mockMailFailures.get(id);
 if(failure!==undefined&&responseString(response,0x30)===failure.text){
  if(!failure.used){failure.used=true;const center=getCenter();removeObserver(center,manager,Memory.allocUtf8String('REQUEST_DATA_GOTTEN'));post2(center,Memory.allocUtf8String('GO_ON'));report({event:'offline-mock-mail-failure-finished',id,retryable:store.healthy()});}
  return;
 }
 if(!store.healthy()){report({event:'offline-mock-mail-response-rejected'});return;}
 if(mockMailDelivery===undefined||responseString(response,0x30)!==mockMailDelivery.text){report({event:'offline-mock-mail-id-rejected'});return;}
 if(mockMailDelivery.used){
  if(!mockMailDelivery.committed){report({event:'offline-mock-mail-response-in-progress'});return;}
  const center=getCenter();removeObserver(center,manager,Memory.allocUtf8String('REQUEST_DATA_GOTTEN'));post2(center,Memory.allocUtf8String('GO_ON'));
  report({event:'offline-mock-mail-replay-blocked'});return;
 }
 mockMailDelivery.used=true;
 try{
  if(store.pendingMockMail(id)===null)throw new Error('Mock mail has no pending receipt');
  const before=withBagSnapshot(snapshot=>store.mockMailKind(id)==='pet'?withPetSnapshot(pet=>store.mockPetBefore(pet,snapshot)):store.mockMailKind(id)==='bagua'?store.verifyMockBaguaSnapshot(snapshot,true,id):rewardQuantity(store.readRequest(snapshot),504100));
  if(store.mockMailKind(id)==='pill'&&!Number.isSafeInteger(before+1))throw new Error('Mock mail quantity exceeds supported range');
  const active={id,delivery:mockMailDelivery,before,point:currentPoint(),committed:false,ackCount:0,clearCount:0,notifications:[]};activeMockMail=active;
  originalMockMail(manager,response);
  if(!store.healthy()||!active.committed||active.ackCount!==1||active.clearCount!==1||active.notifications.length!==1)throw new Error('Mock mail handler did not finish');
  activeMockMail=null;
  for(const args of active.notifications)post2(...args);
  report({event:'offline-mock-mail-reward-committed',id});
 }catch(error){store.blockLottery();report({event:'offline-mock-mail-reward-failed',error:error.message});}
 finally{activeMockMail=null;}
},'void',['pointer','pointer']));
report({event:'local-role-wire-ready'});
}
function configureFirstLevelVictorySaveMask(game){
 const entry=game.base.add(0x2996e2c),caller=game.base.add(0x4b92bf8);
 if(entry.readU32()!==0xd10283ff||entry.add(4).readU32()!==0xa90473fb)throw new Error('Level leave entry fingerprint mismatch');
 Interceptor.attach(entry,{onEnter(args){
  if(!this.returnAddress.equals(caller)||args[1].toInt32()!==700002||args[2].toInt32()!==1||args[3].toInt32()!==0)return;
  // 首次普通胜利的引导分支清掉了这三位；恢复后仍由同一次原 builder 生成快照。
  const mask=args[4].toUInt32();args[4]=ptr((mask|0x0b)>>>0);
  report({event:'offline-first-victory-save-mask',before:mask,after:args[4].toUInt32()});
 }});
}
function configureOfflineArtifactPreview(game){
 const entry=game.base.add(0x307c294),callers=[0x1f829d0,0x1f808f8].map(offset=>game.base.add(offset));
 if(entry.readU32()!==0xd10083ff||entry.add(4).readU32()!==0xa90053f3)throw new Error('Artifact preview native entry fingerprint mismatch');
 // shortcut: 509100 原资源缺失，仅此默认预览用同族动画；取得原资源后删除回退。
 const fallback=Memory.allocUtf8String('skeleton/artifact_armor/509135.skel');
 Interceptor.attach(entry,{onEnter(args){
  if(!callers.some(caller=>this.returnAddress.equals(caller))||args[0].isNull()||args[0].readUtf8String()!=='skeleton/artifact_armor/509100.skel')return;
  args[0]=fallback;
  report({event:'offline-artifact-preview-fallback',missing:509100,preview:509135});
 }});
}
function configureOfflineVoidIntro(game){
 const at=offset=>game.base.add(offset),caller=at(0x48a8cc8),missing=at(0x67b82a0),attempted=new Set();
 try{
  for(const [offset,first,second] of [[0x296e5c0,0xd102c3ff,0xa90053f3],[0x296d95c,0xd10143ff,0xa90053f3],[0x298a290,0xd11143ff,0xd10183ff],[0x48a8cc4,0x9783163f,0x53001c00]]){
   if(at(offset).readU32()!==first||at(offset+4).readU32()!==second)throw new Error('Void intro native fingerprint mismatch: '+offset.toString(16));
  }
 }catch(error){report({event:'offline-void-intro-failed',stage:'configure',error:error.message});throw error;}
 const query=new NativeFunction(at(0x296d95c),'pointer',['pointer','int']);
 const initialize=new NativeFunction(at(0x298a290),'void',['pointer']);
 Interceptor.attach(at(0x296e5c0),{onEnter(args){
  if(!this.returnAddress.equals(caller)||args[1].toInt32()!==100048)return;
  try{
   const manager=args[0],singleton=at(0x67b8298).readPointer();
   if(manager.isNull()||singleton.isNull()||!manager.equals(singleton))throw new Error('Void intro LevelManager does not match the existing singleton');
   const current=query(manager,100048);
   if(current.isNull())throw new Error('Void intro query returned null');
   // 原构造器会重置次数；已有 key（含空 vector/零次数）必须保留，只在原 GL 点击路径补缺。
   if(!current.equals(missing)||attempted.has(manager.toString()))return;
   attempted.add(manager.toString());
   initialize(manager);
   const restored=query(manager,100048);
   if(restored.isNull()||restored.equals(missing))throw new Error('Void intro initialization did not create the missing activity');
   report({event:'offline-void-intro-initialized',map:100048});
  }catch(error){report({event:'offline-void-intro-failed',stage:'entry',error:error.message});}
 }});
}
let configured=false;
function configure(game){
if(configured)return;
configured=true;
configureFirstLevelVictorySaveMask(game);
const emptyOnlineBranch=game.base.add(0x2ebbf98);
if(emptyOnlineBranch.readU32()!==0x35002000)throw new Error('Empty online list branch fingerprint mismatch');
Memory.patchCode(emptyOnlineBranch,4,code=>code.writeU32(0x14000100));
report({event:'offline-empty-online-list-preserved'});
configureOfflineArtifactPreview(game);
configureOfflineVoidIntro(game);
const offlineStore=createNativeSaveStore(game);
const isPreparedPetRequest=configureOfflinePetState(game,offlineStore);
configureRoleWire(game,offlineStore,isPreparedPetRequest);
const memoryCheckPoint=game.base.add(0x2d7bf2c);
if(memoryCheckPoint.readU32()!==0xb4000080)throw new Error('Memory check branch fingerprint mismatch');
Memory.patchCode(memoryCheckPoint,4,code=>code.writeU32(0xd503201f));
report({event:'missing-optional-animation-preload-skipped'});
let pendingLogin=false,sdkReady=false,localLoginDone=false,selectionPending=null;
Interceptor.replace(game.base.add(0x3d39390),new NativeCallback(function(){
 pendingLogin=true;
 Java.perform(function(){const helper=Java.use('org.yjmobile.lib.YJMobileJNIHelper');helper.setHummingbirdSDKLogined(true);helper.setSDKUserID('offline-local');helper.setSDKUserName('Offline');helper.setSDKExt('{}');sdkReady=true;});
 report({event:'local-login-requested'});
},'void',[]));
const at=offset=>game.base.add(offset);
const getLogin=new NativeFunction(at(0x2eba2b8),'pointer',[]);
const valueCtor=new NativeFunction(at(0x3d28344),'void',['pointer','int']);
const valueDtor=new NativeFunction(at(0x3d2a33c),'void',['pointer']);
const readerCtor=new NativeFunction(at(0x3d23f04),'void',['pointer']);
const readerDtor=new NativeFunction(at(0x211e004),'void',['pointer']);
const parse=new NativeFunction(at(0x3d27110),'uint',['pointer','pointer','pointer','pointer','int']);
const login=new NativeFunction(at(0x2ec147c),'void',['pointer','pointer']);
const closeLogin=new NativeFunction(at(0x4abcabc),'void',['pointer','int','int','pointer']);
const showCreate=new NativeFunction(at(0x4ab9c4c),'void',['pointer','pointer']);
const setName=new NativeFunction(at(0x4a92630),'void',['pointer','pointer']);
const selectWheel=new NativeFunction(at(0x4aa8dfc),'void',['pointer','int']);
const highlightItem=new NativeFunction(at(0x4aa95ac),'void',['pointer','bool']);
const childByTag=new NativeFunction(at(0x4e0c030),'pointer',['pointer','int']);
const actionCount=new NativeFunction(game.getExportByName('_ZN7cocos2d6CCNode22numberOfRunningActionsEv'),'uint',['pointer']);
const localName=Memory.allocUtf8String('Wukong');
const loginResponse=JSON.stringify({services:[{service:1,unique_id:1,name:'Offline 1',roleids:[],isnew:1,createtime:0,starttime:0}],rolelist:{},lastdata:{},create_role_count:0});
const loginData=Memory.allocUtf8String(loginResponse);
Interceptor.attach(game.getExportByName('_ZN7cocos2d10CCDirector9drawSceneEv'),{onEnter(){
 if(selectionPending!==null){
  const {layer,time}=selectionPending;const wheel=layer.add(0x228).readPointer(),container=wheel.add(0x1c8).readPointer();
  if(Date.now()-time>1500&&wheel.add(0x218).readU8()===0&&actionCount(container)===0&&actionCount(wheel)===0){
   const item=childByTag(container,1001);if(item.isNull())throw new Error('Wukong wheel item is missing');
   selectionPending=null;highlightItem(item,1);selectWheel(wheel,1);
   report({event:'wukong-wheel-selected',roleId:layer.add(0x238).readU32()});
  }
 }
 if(!pendingLogin||!sdkReady||localLoginDone)return;
 const global=at(0x67b85d0).readPointer();if(global.isNull())return;
 const scene=global.add(0x270).readPointer();
 if(scene.isNull()||!scene.readPointer().equals(at(0x66f50e0)))return;
 if(scene.add(0x300).readPointer().isNull()||scene.add(0x2f8).readPointer().isNull())return;
 localLoginDone=true;pendingLogin=false;
 const reader=Memory.alloc(0xe0),root=Memory.alloc(0x18);
 reader.writeByteArray(new Uint8Array(0xe0));root.writeByteArray(new Uint8Array(0x18));
 valueCtor(root,0);readerCtor(reader);
 try{
  if(!parse(reader,loginData,loginData.add(loginResponse.length),root,1))throw new Error('Local login JSON failed to parse');
  const manager=getLogin();login(manager,root);closeLogin(scene,0,0,ptr(0));
  if(offlineStore.exists()){
   const restore=new NativeFunction(at(0x2eb5a4c),'void',['pointer','pointer','int','pointer','int','pointer','int']);
   restore(manager,Memory.allocUtf8String('10001'),1,Memory.allocUtf8String('Offline 1'),1,localName,offlineStore.level());
   report({event:'offline-role-restore-requested'});
  }else{
   showCreate(scene,ptr(0));const layer=scene.add(0x300).readPointer();setName(layer,localName);selectionPending={layer,time:Date.now()};
   report({event:'local-create-ui-ready',roleId:layer.add(0x238).readU32(),selectedServer:!manager.add(0x130).readPointer().isNull()});
  }
 }finally{valueDtor(root);readerDtor(reader);}
}});

Interceptor.replace(game.base.add(0x2f89d9c), new NativeCallback(function(){report({event:'mtp-init-isolated'});return 0;},'int',['pointer']));
Interceptor.replace(game.base.add(0x68b2700),Module.getExportByName('libc.so','fclose'));
Process.setExceptionHandler(function(details){
 const mod=Process.findModuleByAddress(details.address);
 report({event:'native-exception',type:details.type,module:mod?mod.name:null,offset:mod?details.address.sub(mod.base).toString():details.address.toString()});
 return false;
});
const localUrl=Memory.allocUtf8String('http://127.0.0.1:1/android/index.php');
const localUpdate=Memory.allocUtf8String('{}');
const resourceText='{"code":1000}';
const localResource=Memory.allocUtf8String(resourceText);
Interceptor.attach(game.base.add(0x2ab75d8),{
 onEnter(args){
  const req=args[2].add(0x18).readPointer();
  const tagPointer=req.add(0x40).readPointer();
  const tag=tagPointer.isNull()?'':tagPointer.readUtf8String();
  const delegate=req.add(0x90).readPointer();
  const manager=game.base.add(0x67b9398).readPointer();
  const resourceManager=game.base.add(0x67b9ef8).readPointer();
  if(!tag.startsWith('REQUEST_CHAT_'))report({event:'http-response',tag,success:args[2].add(0x20).readU8()});
  if((tag==='REQUEST_APP_CHECK_UPDATE' && delegate.equals(manager.add(0x20))) || (tag==='REQUEST_UPDATE_RESOURCE' && delegate.equals(resourceManager.add(0x28)))){args[2].add(0x20).writeU8(1);args[2].add(0x58).writeS64(200);report({event:'local-update-http-success'});}
 }
});
Interceptor.attach(game.base.add(0x2a97c18),{
 onEnter(args){if(this.returnAddress.equals(game.base.add(0x2b82e78)) || this.returnAddress.equals(game.base.add(0x2c99580))){args[4]=ptr(0);report({event:'local-update-plaintext'});}}
});
Interceptor.attach(game.base.add(0x4ecacb4),{
 onEnter(args){if(args[1].toInt32()===10002){args[2]=localUrl;}}
});
Interceptor.attach(game.base.add(0x2b80d88),{onEnter(){report({event:'update-callback-enter'});}});
Interceptor.attach(game.base.add(0x3d27110),{
 onEnter(args){const caller=this.returnAddress.sub(game.base).toUInt32();if(caller>=0x2b70000&&caller<0x2b90000)report({event:'update-json-reader',caller});if(this.returnAddress.equals(game.base.add(0x2b80df4))){args[1]=localUpdate;args[2]=localUpdate.add(2);report({event:'local-update-response'});}
  if(this.returnAddress.equals(game.base.add(0x2c99264))){args[1]=localResource;args[2]=localResource.add(resourceText.length);report({event:'local-resource-response'});}}
});
report({event:'native-update-ready',pid:Process.id,base:game.base.toString()});

}
if(typeof Java!=='undefined')configureOfflineSdkNetwork();
const game=Process.findModuleByName('libgame.so');
if(game)configure(game);
else Interceptor.attach(Module.getExportByName(null,'android_dlopen_ext'),{
 onEnter(args){this.name=args[0].isNull()?'':args[0].readUtf8String().split('/').pop();},
 onLeave(){
  if(this.name==='libtersafe2.so'){
    const tss=Process.getModuleByName(this.name);
    const point=tss.base.add(0x1940f4);
    const expected=(0x94000000 | (((0xb47a4-0x1940f4)/4)&0x3ffffff))>>>0;
    if(point.readU32()!==expected)throw new Error('tss branch fingerprint mismatch');
    Memory.patchCode(point,4,code=>code.writeU32(0xd503201f));
    report({event:'tss-background-start-isolated'});
  }
  if(this.name==='libgame.so')configure(Process.getModuleByName(this.name));
 }
});
