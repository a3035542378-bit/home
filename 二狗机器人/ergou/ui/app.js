"use strict";
const $=id=>document.getElementById(id);
const pages=["运行概览","群消息接收记录","群配置","运行告警","游戏目录","会话","积分","积分流水","定时通知","规则命中","周报","上周采集缺口","周报归档","发送任务","入站异常","外部服务","撤回记录","后台权限","审计"];
pages.splice(3,0,"大模型配置","语音唤醒","自定义回复","成员通知","群组运营");
pages.splice(1,0,"我的群组");
pages.splice(2,0,"微信扫码登录","后台账号");
let user,status,page=pages[0],revision=0,modelSettings,dialogSettings;
let speechSequence=null, objectUrl=null, speechTicket=0;
function el(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
async function api(path,data){
  const requestRevision=revision;
  const options=data?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)}:{};
  const response=await fetch(path,options);
  const result=await response.json();
  if(!response.ok){if(response.status===401&&requestRevision===revision)loginView();throw Error(result.error);}
  return result;
}
function loginView(){++revision;clearVoiceTest();$("modelForm").reset();$("voicePanel").replaceChildren();$("adminAccounts").replaceChildren();$("wechatLogin").replaceChildren();$("diagnosticBody").replaceChildren();page=pages[0];modelSettings=null;$("desk").hidden=true;$("gate").hidden=false;}
function error(e){$("message").textContent=e.message;}
function table(rows){
  const wrap=$("tableWrap");wrap.replaceChildren();
  if(!rows.length){wrap.append(el("p","本群暂无记录"));return;}
  const t=el("table",""),head=t.createTHead().insertRow(),body=t.createTBody();
  Object.keys(rows[0]).forEach(k=>head.append(el("th",k)));
  rows.forEach(row=>{const tr=body.insertRow();Object.entries(row).forEach(([k,v])=>{
    const date=["时间","下次执行","结束时间","首次发现","恢复时间"].includes(k)&&typeof v==="number";
    tr.insertCell().textContent=date?new Date(v*1000).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai"}):v??"—";
  });});wrap.append(t);
}
const diagnosticTime=new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",dateStyle:"short",timeStyle:"medium",hour12:false});
async function loadReplyDiagnostics(group,ticket){
  const body=$("diagnosticBody"), refresh=$("refreshDiagnostics");
  refresh.disabled=true;
  try{
    const {health,records}=await api("api/reply-diagnostics?"+new URLSearchParams({group}));
    if(ticket!==revision)return;
    body.replaceChildren(el("strong",health.title),el("p",health.detail));
    if(health.mode!=="simulation"){
      const heartbeat=health.last_seen==null?"暂无":diagnosticTime.format(health.last_seen*1000);
      body.append(el("p","最近心跳（北京时间）　"+heartbeat));
    }
    if(!records.length){
      body.append(el("p",health.mode==="simulation"?"模拟发送结果可在「发送任务」中查看。":"本群暂无点名文字或群语音记录。"));
      return;
    }
    body.append(el("h3","最近点名和语音（北京时间）"));
    const list=document.createElement("ul");
    for(const record of records){
      const item=document.createElement("li");
      const times=["收到 "+diagnosticTime.format(record.received*1000),"尝试发送 "+record.attempts+" 次"];
      if(record.ack_at!=null)times.push("回执 "+diagnosticTime.format(record.ack_at*1000));
      item.append(el("strong",record.kind+" · "+record.status),el("small",times.join("　")));
      if(record.detail)item.append(el("p",record.detail));
      list.append(item);
    }
    body.append(list);
  }catch(err){
    if(ticket===revision)body.textContent="无法读取回复诊断。"+err.message;
  }finally{
    if(ticket===revision)refresh.disabled=false;
  }
}
$("refreshDiagnostics").onclick=()=>loadReplyDiagnostics($("group").value,revision);
async function render(){
  const ticket=++revision,group=$("group").value,query=new URLSearchParams({group,name:page});
  $("message").textContent="";$("heading").textContent=page;
  clearSpeech();clearVoiceTest();
  for(const b of $("nav").children)b.classList.toggle("active",b.textContent===page);
  $("overview").hidden=page!=="运行概览";$("settings").hidden=page!=="群配置";$("modelPanel").hidden=page!=="大模型配置";
  $("diagnosticBody").textContent=page==="运行概览"&&group?"正在读取回复诊断…":"";
  $("replyDiagnostics").hidden=!group;$("refreshDiagnostics").disabled=true;
  $("records").hidden=["运行概览","群配置","大模型配置","语音唤醒","自定义回复","成员通知","群组运营","我的群组","后台账号","微信扫码登录"].includes(page);
  $("adminAccounts").hidden=page!=="后台账号";$("adminAccounts").replaceChildren();
  $("wechatLogin").hidden=page!=="微信扫码登录";$("wechatLogin").replaceChildren();
  $("voicePanel").hidden=page!=="语音唤醒";$("voicePanel").replaceChildren();
  $("memberNotices").hidden=page!=="成员通知";$("memberNotices").replaceChildren();
  $("replyRulesPanel").hidden=page!=="自定义回复";$("replyRulesPanel").replaceChildren();
  $("groupTools").hidden=page!=="群组运营";$("groupTools").replaceChildren();
  dialogSettings=null;$("dialogForm").reset();$("memberChoices").replaceChildren();$("dialogState").textContent="";$("dialogResult").textContent="";
  $("modelForm").reset();modelSettings=null;$("openaiKeyHelp").hidden=true;
  $("modelForm").elements.model.replaceChildren();$("modelListStatus").textContent="";$("modelResult").textContent="";
  for(const field of $("modelForm").elements)field.disabled=true;
  $("myGroups").hidden=page!=="我的群组";$("myGroups").replaceChildren();
  if(page==="后台账号"){await renderAdminAccounts(ticket);return;}
  if(page==="微信扫码登录"){await renderWechatLogin(ticket);return;}
  if(page==="我的群组"){
    const groups=await api("api/my-groups");if(ticket!==revision)return;
    for(const g of groups){
      const card=el("article",""),open=el("button","管理本群");
      open.onclick=()=>{$("group").value=g.id;page="群组运营";render().catch(error);};
      card.append(el("h2",g.name),el("p","绑定账号："+g.account),el("p",g.detached?"已解绑":g.paused?"已暂停":g.joined?"已确认成员关系 · "+g.state:"等待核对成员关系"),open);$("myGroups").append(card);
    }
    if(!groups.length)$("myGroups").append(el("p","当前账号尚未获授群权限"));
    return;
  }
  if(!group){$("message").textContent="当前账号尚未获授群权限";return;}
  if(page==="群组运营"){await renderGroupTools(group,ticket);return;}
  if(page==="语音唤醒"){await renderVoice(group,ticket);return;}
  if(page==="成员通知"){await renderMemberNotices(group,ticket);return;}
  if(page==="自定义回复"){
    const rules=await api("api/reply-rules?"+query);
    if(ticket===revision)showReplyRules($("replyRulesPanel"),group,rules,api);
    return;
  }
  if(page==="大模型配置"){
    $("activeModel").textContent="正在读取本群配置…";
    const [result,controls]=await Promise.all([api("api/chat-model?"+query),api("api/dialog-controls?"+query)]);
    if(ticket!==revision)return;
    showModel(result);showDialog(controls);return;
  }
  const data=await api("api/status?"+query);
  if(ticket!==revision)return;status=data;
  if(page===pages[0]){
    const reach=await api("api/overview");if(ticket!==revision)return;
    $("metrics").replaceChildren();
    for(const [k,v] of Object.entries({"授权群数":reach.configured,"可服务群数":reach.serviceable,"本群入站事件":data.received,"本群发送确认":data.outbox.ACKNOWLEDGED||0,"本群结果未知":data.outbox.UNKNOWN||0,"本群等待发送":(data.outbox.PENDING||0)+(data.outbox.RETRY_WAIT||0)})){
      const card=el("div","");card.append(el("small",k),el("strong",v));$("metrics").append(card);
    }
    $("account").replaceChildren();
    Object.entries({"接入方式":data.mode==="simulation"?"本地模拟":"微信适配器","账号":data.account,"当前状态":data.state,"群绑定":"v"+data.binding+(data.paused?" · 已暂停":"")}).forEach(([k,v])=>$("account").append(el("dt",k),el("dd",v)));
    $("simCard").hidden=data.mode!=="simulation"||user.role==="只读人员";$("answer").textContent="";
    await loadReplyDiagnostics(group,ticket);
  }else if(page==="群配置"){
    const games=await api("api/view?"+new URLSearchParams({group,name:"游戏目录"}));
    if(ticket!==revision)return;
    $("config").elements.disabled_games.replaceChildren(...games.map(g=>new Option(g.游戏,g.游戏)));
    for(const elem of $("config").elements){
      if(!elem.name)continue;
      const v=data.config[elem.name];
      if(elem.multiple){for(const opt of elem.options)opt.selected=(v||[]).includes(opt.value);}
      else if(elem.type==="checkbox")elem.checked=v;else elem.value=Array.isArray(v)?v.join("\n"):(v??"");
    }
    preview();for(const item of $("config").elements)item.disabled=user.role==="只读人员";
  }else{
    showControls();
    $("export").href="api/export?"+query;$("export").download=page+".csv";
    $("scheduleForm").hidden=page!=="定时通知"||user.role==="只读人员";
    const rows=await api("api/view?"+query);if(ticket===revision)table(rows);
  }
}
async function boot(){
  user=await api("api/me");$("gate").hidden=true;$("desk").hidden=false;
  $("who").textContent=user.name+" · "+user.role;$("group").replaceChildren(...user.groups.map(g=>new Option(user.group_aliases[g]||g,g)));
  $("nav").replaceChildren();
  for(const name of pages.filter(n=>!["后台权限","撤回记录","后台账号","微信扫码登录"].includes(n)||user.role==="系统管理员")){
    if(["大模型配置","自定义回复"].includes(name)&&!["运营管理员","系统管理员"].includes(user.role))continue;
    const b=el("button",name);b.onclick=()=>{page=name;render().catch(error);};$("nav").append(b);
  }
  await render();
}
function preview(){const f=$("config").elements;$("preview").textContent="预览 · "+f.welcome.value.replace(/\{(群|成员|nickname|时间|群规)\}/g,(_,k)=>({"群":$("group").value,"成员":"新成员","nickname":"新成员","时间":"09:00","群规":f.rules.value})[k])+" "+f.rules_url.value;}
function showDialog(data){
  dialogSettings=data;
  $("dialogState").textContent="当前模式："+(data.enabled&&data.verified?"智能对话":data.verified?"本地回复（密钥已保留）":"本地回复（待验证模型）");
  $("dialogForm").elements.admins.value=data.admins.join("\n");
  $("memberChoices").replaceChildren(new Option("选择成员",""),...data.members.map(m=>new Option(m,m)));
}
$("addMember").onclick=()=>{
  const id=$("memberChoices").value,input=$("dialogForm").elements.admins;
  if(id)input.value=[...new Set([...input.value.split("\n").filter(Boolean),id])].join("\n");
};
$("dialogForm").onsubmit=async event=>{
  event.preventDefault();if(!dialogSettings)return;
  const ticket=revision,admins=event.target.elements.admins.value.split("\n").map(s=>s.trim()).filter(Boolean);
  try{
    const result=await api("api/dialog-controls",{group:$("group").value,admins,version:dialogSettings.version});
    if(ticket===revision){showDialog(result);$("dialogResult").textContent="本群管理员名单已保存。";}
  }catch(e){if(ticket===revision)$("dialogResult").textContent=e.message;}
};
let modelListRequest=0, modelListTimer=null;
function modelCatalogKey(fields){
  return fields.provider.value==="glm"?"":fields.key.value.trim();
}
function updateModelVerification(){
  const f=$("modelForm").elements;
  $("verifyModel").disabled=f.model.disabled||!f.model.value||(f.key.required&&!f.key.value.trim());
}
function resetModelList(){
  ++modelListRequest;
  clearTimeout(modelListTimer);modelListTimer=null;
  const f=$("modelForm").elements;
  f.model.replaceChildren(new Option("请选择模型",""));
  f.model.disabled=$("verifyModel").disabled=true;
  const needsKey=f.provider.value!=="glm"&&f.key.required&&!f.key.value.trim();
  $("refreshModels").disabled=needsKey;
  $("modelListStatus").textContent=needsKey?"请填写所选供应商的官方 API Key。":"";
}
async function loadModelList(){
  const f=$("modelForm").elements;
  if(!modelSettings||f.provider.disabled)return;
  const selected=f.model.value,provider=f.provider.value;
  resetModelList();
  if($("refreshModels").disabled)return;
  const ticket=revision,request=modelListRequest,group=$("group").value;
  const key=modelCatalogKey(f);
  const current=()=>ticket===revision&&request===modelListRequest&&f.provider.value===provider&&modelCatalogKey(f)===key;
  $("refreshModels").disabled=true;$("modelListStatus").textContent="正在从"+f.provider.selectedOptions[0].text+"获取模型…";
  try{
    const result=await api("api/chat-model/models",{group,provider,key});
    if(!current())return;
    for(const id of result.models)f.model.add(new Option(id,id));
    const saved=!key&&modelSettings.active.provider===provider?modelSettings.active.model:"";
    const preferred=selected||saved;
    if(result.models.includes(preferred))f.model.value=preferred;
    f.model.disabled=!result.models.length;
    updateModelVerification();
    let hint="请选择支持文字对话的模型。";
    if(provider==="glm")hint="智谱官方公布的文字模型，当前密钥的访问权限以测试结果为准。";
    $("modelListStatus").textContent=result.models.length?hint:"供应商未返回模型。";
  }catch(err){
    if(current())$("modelListStatus").textContent=err.message;
  }finally{
    if(current())$("refreshModels").disabled=false;
  }
}
function modelChoices(){
  const f=$("modelForm").elements;
  $("openaiKeyHelp").hidden=f.provider.value!=="openai";
  const reuse=modelSettings.active.provider===f.provider.value&&Boolean(modelSettings.active.verified);
  f.key.value="";f.key.required=!reuse;f.key.placeholder=reuse?"已保存，留空可沿用本供应商密钥":"填写该供应商的官方 API Key";
  f.model.value="";
  $("modelResult").textContent="";
  if(reuse||f.provider.value==="glm")loadModelList();else resetModelList();
}
function showModel(data){
  modelSettings=data;const f=$("modelForm").elements,active=data.active;
  for(const field of f)field.disabled=false;
  f.provider.replaceChildren(...data.providers.map(p=>new Option(p.name,p.id)));
  if(data.providers.some(p=>p.id===active.provider))f.provider.value=active.provider;
  modelChoices();$("disableModel").disabled=!active.verified;
  $("activeModel").textContent=active.verified?"已验证 "+f.provider.selectedOptions[0].text+" · "+active.model+"，验证时间 "+new Date(active.verified*1000).toLocaleString("zh-CN"):"本群尚未验证大模型";
}
$("modelForm").elements.provider.onchange=modelChoices;
$("modelForm").elements.key.oninput=()=>{
  if($("modelForm").elements.provider.value==="glm"){updateModelVerification();return;}
  resetModelList();
  if($("refreshModels").disabled)return;
  const ticket=revision;
  modelListTimer=setTimeout(()=>{if(ticket===revision)loadModelList();},650);
};
$("modelForm").elements.key.onchange=()=>{if(modelListTimer!==null)loadModelList();};
$("modelForm").elements.model.onchange=updateModelVerification;
$("refreshModels").onclick=loadModelList;
async function saveModel(action){
  if(!modelSettings)return;
  const ticket=revision,f=$("modelForm").elements;
  const data={group:$("group").value,version:modelSettings.active.version,action};
  if(action==="verify"){
    if($("verifyModel").disabled)return;
    Object.assign(data,{provider:f.provider.value,model:f.model.value,key:f.key.value.trim()});
  }
  ++modelListRequest;
  f.key.value="";for(const field of f)field.disabled=true;
  $("modelResult").textContent=action==="verify"?"正在测试官方接口…":"正在停用…";
  try{
    const state=await api("api/chat-model",data);
    if(ticket!==revision)return;
    showModel(state);
    const controls=await api("api/dialog-controls?"+new URLSearchParams({group:data.group}));
    if(ticket!==revision)return;
    showDialog(controls);$("modelResult").textContent=action==="verify"?"测试通过，模型配置已保存。":"已停用，本群密钥已移除。";
  }catch(err){
    if(ticket!==revision||!modelSettings)return;
    for(const field of f)field.disabled=false;
    if(f.provider.value==="glm")updateModelVerification();
    else if(f.key.required)resetModelList();
    else loadModelList();
    $("disableModel").disabled=!modelSettings.active.verified;
    $("modelResult").textContent=err.message;
  }
}
$("modelForm").onsubmit=e=>{e.preventDefault();saveModel("verify");};
$("disableModel").onclick=()=>{if(confirm("停用本群模型并移除已保存的密钥？"))saveModel("disable");};
for(const [k,v] of Object.entries({enabled:"启用本群",games:"游戏",polls:"投票",draws:"抽签"})){
  const label=el("label",""),box=el("input","");label.className="check";box.type="checkbox";box.name=k;label.append(box,v);$("checks").append(label);
}
$("login").onsubmit=async e=>{e.preventDefault();try{await api("api/login",Object.fromEntries(new FormData(e.target)));e.target.reset();$("loginError").textContent="";await boot();}catch(err){$("loginError").textContent=err.message;}};
$("logout").onclick=async()=>{try{await api("api/logout",{});loginView();}catch(e){error(e);}};
$("group").onchange=()=>render().catch(error);$("refresh").onclick=()=>render().catch(error);
$("config").oninput=preview;
$("config").onsubmit=async e=>{e.preventDefault();const patch={};for(const input of e.target.elements){
  if(input.name)patch[input.name]=input.multiple?Array.from(input.selectedOptions,o=>o.value):input.type==="checkbox"?input.checked:input.type==="number"?input.valueAsNumber:input.name==="words"?input.value.split("\n").filter(Boolean):input.value;
}try{const r=await api("api/config",{group:$("group").value,version:status.version,patch});await render();$("message").textContent="本群配置 v"+r.version+" 已保存，新局使用新规则。";}catch(err){error(err);}};
$("scheduleForm").onsubmit=async e=>{e.preventDefault();try{
  const fields=Object.fromEntries(new FormData(e.target));
  if(fields.id){fields.id=Number(fields.id);fields.version=Number(fields.version);}else{delete fields.id;delete fields.version;}
  await api("api/schedule",{...fields,body:fields.body||"",catchup:e.target.elements.catchup.checked,group:$("group").value});e.target.reset();scheduleFields();await render();
}catch(err){error(err);}};
function scheduleFields(){
  const f=$("scheduleForm").elements,kind=f.kind.value;
  $("scheduleBody").hidden=kind==="news";f.body.required=kind!=="news";
  $("scheduleBody").querySelector("span").textContent=kind==="text"?"通知内容":"天气城市";
}
$("scheduleForm").elements.kind.onchange=scheduleFields;
function clearSpeech(){
  speechTicket++;speechSequence=null;$("speechForm").reset();$("synthesize").hidden=true;$("speechResult").textContent="";
  const player=$("voicePlayer");player.pause();player.removeAttribute("src");player.hidden=true;
  if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null;}
}
$("speechForm").onsubmit=async ev=>{
  ev.preventDefault();const file=ev.target.elements.wav.files[0],group=$("group").value;
  clearSpeech();const ticket=speechTicket;
  try{
    if(!file||file.size>1940000)throw Error("请选择 60 秒以内的 WAV 录音");
    $("speechResult").textContent="正在识别…";
    const audio=await new Promise((ok,fail)=>{const reader=new FileReader();reader.onload=()=>ok(reader.result.split(",")[1]);reader.onerror=()=>fail(Error("读取录音失败"));reader.readAsDataURL(file);});
    if(ticket!==speechTicket)return;
    const result=await api("api/speech/detect",{group,audio,key:crypto.randomUUID()});
    if(ticket!==speechTicket)return;
    if(!result.addressed){$("speechResult").textContent="录音中未识别到点名，未生成回复。";return;}
    $("speechResult").textContent="已识别点名，等待二狗回复…";
    for(let i=0;i<75;i++){
      await new Promise(ok=>setTimeout(ok,400));if(ticket!==speechTicket)return;
      const reply=await api("api/simulation-result?"+new URLSearchParams({group,seq:result.seq}));
      if(ticket!==speechTicket)return;
      if(reply.body){$("speechResult").textContent=reply.body;speechSequence=result.seq;$("synthesize").hidden=false;return;}
      if(["IGNORED","CHAT","FAILED","RATE_LIMITED"].includes(reply.state))break;
    }
    $("speechResult").textContent="尚无文字回复，请在群消息记录中查看处理状态。";
  }catch(err){if(ticket===speechTicket)$("speechResult").textContent=err.message;}
};
$("synthesize").onclick=async()=>{
  const ticket=speechTicket,group=$("group").value;if(!speechSequence)return;
  $("synthesize").disabled=true;
  try{
    const result=await api("api/speech/reply",{group,seq:speechSequence});if(ticket!==speechTicket)return;
    const bytes=Uint8Array.from(atob(result.audio),c=>c.charCodeAt(0));
    if(objectUrl)URL.revokeObjectURL(objectUrl);
    objectUrl=URL.createObjectURL(new Blob([bytes],{type:result.mime}));$("voicePlayer").src=objectUrl;$("voicePlayer").hidden=false;
  }catch(err){if(ticket===speechTicket)$("speechResult").textContent=err.message;}finally{$("synthesize").disabled=false;}
};
$("simulate").onsubmit=async e=>{e.preventDefault();const group=$("group").value,b=e.target.querySelector("button");b.disabled=true;
  try{const r=await api("api/simulate",{group,text:e.target.elements.text.value,mention:e.target.elements.mention.checked,key:crypto.randomUUID()});$("answer").textContent="已入队 #"+r.seq;
    for(let i=0;i<40;i++){await new Promise(resolve=>setTimeout(resolve,300));const result=await api("api/simulation-result?"+new URLSearchParams({group,seq:r.seq}));
      if(group!==$("group").value)break;
      if(result.body||["CHAT","IGNORED","RATE_LIMITED","FAILED"].includes(result.state)){
        $("answer").textContent=result.body||result.state;
        if(result.media?.type==="image"){
          const preview=el("button","加载规则图片");preview.type="button";preview.className="quiet";
          preview.onclick=()=>{const img=document.createElement("img");img.alt="规则回复图片";img.referrerPolicy="no-referrer";img.src=result.media.url;preview.replaceWith(img);};
          $("answer").append(document.createElement("br"),preview);
        }
        break;}}
  }catch(err){error(err);}finally{b.disabled=false;}};
boot().catch(e=>{if(e.message!=="请登录")$("loginError").textContent=e.message;});

function showControls(){
  const actions={"发送任务":["确认送达","结束跟进"],"积分流水":["调分","冲正"],"定时通知":["停用通知"],"入站异常":["重试入站"],"撤回记录":["反查内容","启用留存","关闭留存"]};
  const list=actions[page]||[];
  $("controls").hidden=!list.length||user.role==="只读人员";
  const form=$("controlForm");form.reset();form.elements.action.replaceChildren(...list.map(k=>new Option(k,k)));
  $("opResult").textContent="";selectAction();
}
function selectAction(){
  const action=$("controlForm").elements.action.value;
  $("targetLabel").hidden=["启用留存","关闭留存"].includes(action);
  $("pointsLabel").hidden=action!=="调分";
  $("reasonLabel").hidden=["反查内容","关闭留存"].includes(action);
}
$("controlForm").elements.action.onchange=selectAction;
$("controlForm").onsubmit=async e=>{
  e.preventDefault();const f=e.target.elements, action=f.action.value, group=$("group").value;
  try{
    let result;
    if(action==="反查内容")result=(await api("api/recall",{group,seq:Number(f.target.value)})).text;
    else if(["启用留存","关闭留存"].includes(action)){
      if(action==="启用留存"&&!f.reason.value.trim())throw Error("请先告知群成员，并填写告知记录");
      await api("api/retention",{group,notice:action==="启用留存"?f.reason.value:""});result=action+"已生效";
    }else{
      result=(await api("api/operation",{group,action:["确认送达","结束跟进"].includes(action)?"核对发送":action,
        target:f.target.value,resolution:action,points:Number(f.points.value),key:crypto.randomUUID(),reason:f.reason.value})).result;
    }
    await render();$("opResult").textContent=result;
  }catch(err){error(err);}
};

