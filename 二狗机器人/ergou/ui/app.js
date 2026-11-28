"use strict";
const $=id=>document.getElementById(id);
const modules=[
  ["工作台","◉",["运行概览"]],
  ["机器人与群组","◎",["我的群组","微信扫码登录","群配置"]],
  ["智能交互","✦",["大模型配置","语音唤醒","自定义回复"]],
  ["游戏与积分","◇",["游戏目录","玩家渔获","会话","积分","积分流水"]],
  ["群运营","▤",["群组运营","成员通知","定时通知","周报","周报归档"]],
  ["运维监控","⌁",["群消息接收记录","发送任务","规则命中","运行告警","入站异常","上周采集缺口","外部服务","撤回记录"]],
  ["系统管理","⚙",["后台账号","后台权限","审计"]]
];
const pages=modules.flatMap(module=>module[2]);
function available(name){
  if(name==="成员名册")return user.role!=="只读人员";
  if(["后台权限","撤回记录","后台账号","微信扫码登录"].includes(name))return user.role==="系统管理员";
  return !["大模型配置","自定义回复"].includes(name)||["运营管理员","系统管理员"].includes(user.role);
}
function routeTo(name,group=$("group").value,replace=false){
  if((!pages.includes(name)&&!virtualPages.includes(name))||!available(name))name=pages[0];
  if(!user.groups.includes(group))group=user.groups[0]||"";
  if(configDirty && (page!==name||group!==lastGroup) && !confirm("当前表单尚未保存，放弃修改并离开？")){
    $("group").value=lastGroup;history.replaceState(null,"","#"+new URLSearchParams({page,group:lastGroup}));return;
  }
  configDirty=false;lastGroup=group;page=name;$("group").value=group;
  const hash="#"+new URLSearchParams({page:name,group});
  if(location.hash!==hash)history[replace?"replaceState":"pushState"](null,"",hash);
  $("desk").classList.remove("menuOpen");$("menuToggle").setAttribute("aria-expanded","false");
  return render();
}
function restoreRoute(){
  const params=new URLSearchParams(location.hash.slice(1));
  return routeTo(params.get("page"),params.get("group"),true);
}
window.addEventListener("popstate",()=>{if(!$("desk").hidden)restoreRoute().catch(error);});
$("menuToggle").onclick=()=>$("menuToggle").setAttribute("aria-expanded",String($("desk").classList.toggle("menuOpen")));
let configDirty=false,lastGroup="",visibleRows=[];
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
function loginView(){configDirty=false;history.replaceState(null,"",location.pathname+location.search);++revision;clearVoiceTest();$("modelForm").reset();$("voicePanel").replaceChildren();$("adminAccounts").replaceChildren();$("wechatLogin").replaceChildren();$("diagnosticBody").replaceChildren();page=pages[0];modelSettings=null;$("desk").hidden=true;$("gate").hidden=false;}
function error(e){$("message").textContent=e.message;}
function table(rows){
  const wrap=$("tableWrap");wrap.replaceChildren();
  if(!rows.length){wrap.append(el("p","本群暂无记录"));return;}
  const t=el("table",""),head=t.createTHead().insertRow(),body=t.createTBody();
  const keys=Object.keys(rows[0]), technical=new Set(["来源消息ID","发送成员ID","接入组件","跟踪号","版本"]);
  const columns=keys.filter(k=>!technical.has(k));for(const k of columns)head.append(el("th",k));
  const details=keys.some(k=>technical.has(k)||["状态","处理状态"].includes(k));if(details)head.append(el("th","详情"));
  const editable=page==="定时通知"&&user.role!=="只读人员";if(editable)head.append(el("th","操作"));
  for(const row of rows){
    const tr=body.insertRow();
    for(const k of columns){const v=row[k],date=["时间","接收时间","下次执行","结束时间","首次发现","恢复时间"].includes(k);
      tr.insertCell().textContent=date&&typeof v==="number"?diagnosticTime.format(v*1000):(["状态","处理状态"].includes(k)?stateLabels[v]||v:v)??"—";}
    if(details){const d=el("details","");d.append(el("summary","查看原始字段"));for(const k of keys.filter(k=>technical.has(k)||["状态","处理状态"].includes(k)))d.append(el("p",k+" · "+(row[k]??"—")));tr.insertCell().append(d);}
    if(editable){const btn=el("button","编辑通知");btn.onclick=()=>editSchedule(row);tr.insertCell().append(btn);}
  }
  wrap.append(t);
}
$("export").onclick=async event=>{
  event.preventDefault();const link=event.currentTarget;
  if(!link.hasAttribute("href")||link.dataset.busy)return;
  const url=link.href,name=link.download,ticket=revision;link.dataset.busy="1";
  try{
    const response=await fetch(url);
    if(!response.ok)throw Error(response.status===429?"已有导出正在进行，请稍后再试。":(await response.json()).error);
    const file=URL.createObjectURL(await response.blob()),download=el("a","");
    download.href=file;download.download=name;document.body.append(download);download.click();download.remove();
    setTimeout(()=>URL.revokeObjectURL(file),60000);
  }catch(err){if(ticket===revision)error(err);}finally{delete link.dataset.busy;}
};
function filterRecords(){
  const term=$("recordSearch").value.trim().toLowerCase();
  table(visibleRows.filter(row=>Object.values(row).some(v=>(String(v)+" "+(stateLabels[v]||"")).toLowerCase().includes(term))));
}
$("recordSearch").oninput=filterRecords;
$("newSchedule").onclick=resetSchedule;
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
let grantReady=false;
let listContext="",listOffset=0;
const timedLists=["周报归档","群消息接收记录","运行告警","会话","积分流水","发送任务","入站异常","定时通知","审计","撤回记录"];
const pagedLists=[...timedLists,"玩家渔获","积分","后台权限","规则命中"];
$("listPrev").onclick=()=>{listOffset=Math.max(0,listOffset-200);render().catch(error);};
$("listNext").onclick=()=>{listOffset+=200;render().catch(error);};
for(const id of ["rangeStart","rangeEnd","catchMember"])$(id).onchange=()=>{listOffset=0;render().catch(error);};
async function render(){
  const ticket=++revision,group=$("group").value,query=new URLSearchParams({group,name:page});
  $("message").textContent="";$("heading").textContent=page;
  grantReady=false;$("controls").hidden=true;$("grantMembers").replaceChildren();
  $("export").removeAttribute("href");$("export").removeAttribute("download");
  $("tableWrap").replaceChildren();$("metrics").replaceChildren();$("account").replaceChildren();
  clearSpeech();clearVoiceTest();
  for(const b of $("nav").querySelectorAll("button")){
    const current=b.textContent===page;b.classList.toggle("active",current);
    if(current){b.setAttribute("aria-current","page");b.closest("details").open=true;}
    else b.removeAttribute("aria-current");
  }
  $("crumb").textContent=(modules.find(module=>module[2].includes(page))||["机器人与群组"])[0]+"  /  "+page;
  sectionBar();$("groupDetail").hidden=!virtualPages.includes(page);
  visibleRows=[];
  $("overview").hidden=page!=="运行概览";$("settings").hidden=page!=="群配置";$("modelPanel").hidden=page!=="大模型配置";
  for(const field of $("config").elements)field.disabled=true;
  $("diagnosticBody").textContent=page==="运行概览"&&group?"正在读取回复诊断…":"";
  $("replyDiagnostics").hidden=!group;$("refreshDiagnostics").disabled=true;
  $("records").hidden=virtualPages.includes(page)||["运行概览","群配置","大模型配置","语音唤醒","自定义回复","成员通知","群组运营","我的群组","后台账号","微信扫码登录"].includes(page);
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
  if(virtualPages.includes(page)){await detailPage(group,ticket);return;}
  if(page==="后台账号"){await renderAdminAccounts(ticket);return;}
  if(page==="微信扫码登录"){await renderWechatLogin(ticket);return;}
  if(page==="我的群组"){
    const groups=await api("api/my-groups");if(ticket!==revision)return;
    const panel=$("myGroups"),search=el("input",""),wrap=el("div",""),table=el("table","");
    search.type="search";search.placeholder="搜索群名、群 ID、微信昵称或账号";search.setAttribute("aria-label",search.placeholder);
    wrap.className="room-scroll";table.className="room-table managed-rooms";wrap.append(table);
    const head=table.createTHead().insertRow();
    for(const label of ["群 ID","群名","微信昵称","绑定微信账号","账号状态","群状态","操作"]){
      const th=el("th",label);th.scope="col";head.append(th);
    }
    const body=table.createTBody(),pager=el("div",""),prev=el("button","上一页"),next=el("button","下一页"),summary=el("span","");
    pager.className="room-pager";pager.append(summary,prev,next);panel.append(search,wrap,pager);
    const states={STOPPED:"已停止",STARTING:"启动中",WAITING_LOGIN:"等待登录",ONLINE:"已在线",LISTENING:"监听中",
      RECONNECTING:"重新连接中",NEED_USER_ACTION:"等待人工处理",SUSPENDED:"已暂停",ERROR:"异常"};
    let current=1;
    function show(){
      const term=search.value.trim().toLowerCase();
      const matches=groups.filter(g=>[g.id,g.name,g.nickname,g.account].some(v=>v&&v.toLowerCase().includes(term)));
      const pages=Math.max(1,Math.ceil(matches.length/10));
      prev.disabled=current===1;next.disabled=current===pages;
      summary.textContent="共 "+matches.length+" 个群 · "+current+" / "+pages+" 页";
      body.replaceChildren();
      if(!matches.length){const cell=body.insertRow().insertCell();cell.colSpan=7;cell.textContent=term?"没有匹配的群":"当前账号尚未获授群权限";}
      for(const g of matches.slice((current-1)*10,current*10)){
        const row=body.insertRow();
        for(const value of [g.id.replace(/@chatroom$/,""),g.name===g.id?"—":g.name,g.nickname||"暂未获取",g.account,
          states[g.state]||"未知",g.detached?"已解绑":g.paused?"已暂停":g.joined?"已确认成员关系":"等待核对成员关系"]){
          const cell=row.insertCell();cell.textContent=value;cell.title=value;
        }
        row.cells[0].title=g.id;
        const open=el("button","管理本群");
        open.onclick=()=>routeTo("群组概览",g.id).catch(error);
        row.insertCell().append(open);
      }
    }
    search.oninput=()=>{current=1;show();};prev.onclick=()=>{current--;show();};next.onclick=()=>{current++;show();};show();
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
    $("inboxTasks").replaceChildren(jump("待处理告警 · "+data.alerts,"运行告警"),jump("发送结果未知 · "+(data.outbox.UNKNOWN||0),"发送任务"));
    $("metrics").replaceChildren();
    for(const [k,v] of Object.entries({"授权群数":reach.configured,"可服务群数":reach.serviceable,"本群入站事件":data.received,"本群发送确认":data.outbox.ACKNOWLEDGED||0,"本群结果未知":data.outbox.UNKNOWN||0,"本群等待发送":(data.outbox.PENDING||0)+(data.outbox.RETRY_WAIT||0)})){
      const card=el("div","");card.append(el("small",k),el("strong",v));$("metrics").append(card);
    }
    $("account").replaceChildren();
    Object.entries({"接入方式":data.mode==="simulation"?"本地模拟":"微信适配器","账号":data.account,"当前状态":({ONLINE:"在线",LISTENING:"监听中",STOPPED:"已停止",RECONNECTING:"重新连接中"})[data.state]||data.state,"群绑定":"v"+data.binding+(data.paused?" · 已暂停":"")}).forEach(([k,v])=>$("account").append(el("dt",k),el("dd",v)));
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
    const options=[...$("config").elements.disabled_games.options];
    $("gameCategory").replaceChildren(new Option("全部品类",""), ...[...new Set(games.map(g=>g.品类))].map(c=>new Option(c,c)));
    $("gameSearch").value="";
    function filteredGames(){
      return options.filter((opt,i)=>opt.text.includes($("gameSearch").value.trim()) &&
        (!$("gameCategory").value || games[i].品类===$("gameCategory").value));
    }
    function drawGames(){
      const visible=filteredGames();
      $("gameCount").textContent=visible.length+" 个游戏";
      $("gameChoices").replaceChildren(...visible.map(option=>{
        const label=el("label",""),box=el("input","");
        box.type="checkbox";box.checked=!option.selected;box.disabled=user.role==="只读人员";
        box.onchange=()=>{option.selected=!box.checked;};
        label.className="check";label.append(box,option.text);return label;
      }));
    }
    $("gameSearch").oninput=drawGames;$("gameCategory").onchange=drawGames;
    for(const [id,disabled] of [["enableVisible",false],["disableVisible",true]]){
      $(id).onclick=()=>{for(const opt of filteredGames())opt.selected=disabled;drawGames();};
    }
    drawGames();
    preview();for(const item of $("config").elements)item.disabled=user.role==="只读人员";
  }else{
    $("grantMembers").replaceChildren();
    grantReady=false;
    if(page==="积分流水" && user.role!=="只读人员"){
      const roster=await api("api/grant-members?"+query);if(ticket!==revision)return;
      grantReady=roster.ready;
      $("grantMembers").replaceChildren(...roster.members.map(id=>new Option(roster.labels[id]+" · "+roster.group+" · 在群",id)));
    }
    showControls();
    const context=JSON.stringify([user.name,group,page]);
    if(context!==listContext){resetSchedule();$("recordSearch").value="";listContext=context;listOffset=0;$("rangeStart").value=$("rangeEnd").value=$("catchMember").value="";}
    $("catchFilter").hidden=page!=="玩家渔获";
    if(page==="玩家渔获" && $("catchMember").value.trim()) query.set("member",$("catchMember").value.trim());
    $("listRange").hidden=!timedLists.includes(page);
    if(timedLists.includes(page)){
      for(const [field,id] of [["start","rangeStart"],["end","rangeEnd"]]){
        if($(id).value)query.set(field,String(new Date($(id).value+"+08:00").getTime()/1000));
      }
    }
    $("listPrev").hidden=$("listNext").hidden=!pagedLists.includes(page);
    $("listPrev").disabled=listOffset===0;$("listNext").disabled=true;
    $("export").href="api/export?"+query;$("export").download=page+".csv";
    $("scheduleForm").hidden=page!=="定时通知"||user.role==="只读人员";
    query.set("offset",listOffset);
    const rows=await api("api/view?"+query);
    if(ticket===revision){visibleRows=rows;filterRecords();$("listNext").disabled=rows.length<200;}
  }
}
async function boot(){
  user=await api("api/me");$("gate").hidden=true;$("desk").hidden=false;
  $("who").textContent=user.name+" · "+user.role;$("group").replaceChildren(...user.groups.map(g=>new Option(user.group_aliases[g]||g,g)));
  $("nav").replaceChildren();
  for(const [title,icon,names] of modules){
    const visible=names.filter(available);if(!visible.length)continue;
    const section=el("details",""),summary=el("summary","");
    const glyph=el("span",icon);glyph.setAttribute("aria-hidden","true");
    summary.append(glyph,el("strong",title));section.append(summary);
    for(const name of visible){
      const button=el("button",name);button.onclick=()=>routeTo(name).catch(error);section.append(button);
    }
    $("nav").append(section);
  }
  $("shortcuts").replaceChildren();
  for(const [name,label] of [["我的群组","群组管理"],["大模型配置","模型配置"],["定时通知","定时通知"],["群消息接收记录","消息记录"]]){
    if(!available(name))continue;
    const button=el("button",label);button.onclick=()=>routeTo(name).catch(error);$("shortcuts").append(button);
  }
  await restoreRoute();
}
function preview(){const f=$("config").elements;$("preview").textContent="预览 · "+f.welcome.value.replace(/\{(群|成员|nickname|时间|群规)\}/g,(_,k)=>({"群":$("group").selectedOptions[0]?.text||$("group").value,"成员":"新成员","nickname":"新成员","时间":"09:00","群规":f.rules.value})[k])+" "+f.rules_url.value;}
function showDialog(data){
  dialogSettings=data;$("toggleModel").disabled=!data.verified;$("toggleModel").textContent=data.enabled?"暂停智能对话（保留密钥）":"启用已保存的模型";
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
    if(ticket===revision){configDirty=false;showDialog(result);$("dialogResult").textContent="本群管理员名单已保存。";}
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
  $("activeModel").textContent=active.verified?"已验证 "+f.provider.selectedOptions[0].text+" · "+active.model+"，验证时间 "+new Date(active.verified*1000).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai"}):"本群尚未验证大模型";
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
  if(action==="save"||action==="test"){
    if($("verifyModel").disabled)return;
    Object.assign(data,{provider:f.provider.value,model:f.model.value,key:f.key.value.trim()});
  }
  ++modelListRequest;
  if(action==="test"){
    $("testModel").disabled=true;try{await api("api/chat-model",data);if(ticket===revision)$("modelResult").textContent="连接成功，配置未变更。";}catch(err){if(ticket===revision)$("modelResult").textContent=err.message;}finally{if(ticket===revision)$("testModel").disabled=false;}return;
  }
  f.key.value="";for(const field of f)field.disabled=true;
  $("modelResult").textContent=action==="save"?"正在测试官方接口…":"正在停用…";
  try{
    const state=await api("api/chat-model",data);
    if(ticket!==revision)return;
    showModel(state);
    const controls=await api("api/dialog-controls?"+new URLSearchParams({group:data.group}));
    if(ticket!==revision)return;
    configDirty=false;showDialog(controls);$("modelResult").textContent=action==="save"?"测试通过，模型配置已保存。":"已停用，本群密钥已移除。";
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
$("testModel").onclick=()=>saveModel("test");
$("toggleModel").onclick=async()=>{const ticket=revision;try{const r=await api("api/dialog-controls",{group:$("group").value,version:dialogSettings.version,enabled:!dialogSettings.enabled});if(ticket===revision)showDialog({...r,members:dialogSettings.members});}catch(e){if(ticket===revision)error(e);}};
$("modelForm").onsubmit=e=>{e.preventDefault();saveModel("save");};
$("disableModel").onclick=()=>{if(confirm("停用本群模型并移除已保存的密钥？"))saveModel("disable");};
for(const [k,v] of Object.entries({enabled:"启用本群",games:"游戏",polls:"投票",draws:"抽签",fishing_cards:"手绘回复卡片（钓鱼、个人档案、成就、礼物）",exhibit_board_push:"结算后发送图鉴榜（前十名及到账积分）"})){
  const label=el("label",""),box=el("input","");label.className="check";box.type="checkbox";box.name=k;label.append(box,v);$("checks").append(label);
}
$("login").onsubmit=async e=>{e.preventDefault();try{await api("api/login",Object.fromEntries(new FormData(e.target)));e.target.reset();$("loginError").textContent="";await boot();}catch(err){$("loginError").textContent=err.message;}};
$("logout").onclick=async()=>{try{await api("api/logout",{});loginView();}catch(e){error(e);}};
$("group").onchange=()=>routeTo(page).catch(error);$("refresh").onclick=()=>render().catch(error);
$("config").oninput=()=>{configDirty=true;preview();};
$("config").onsubmit=async e=>{e.preventDefault();if(e.target.elements.exhibit_board_push.disabled)return;const patch={};for(const input of e.target.elements){
  if(input.name)patch[input.name]=input.multiple?Array.from(input.selectedOptions,o=>o.value):input.type==="checkbox"?input.checked:input.type==="number"?input.valueAsNumber:input.name==="words"?input.value.split("\n").filter(Boolean):input.value;
}try{const r=await api("api/config",{group:$("group").value,version:status.version,patch});configDirty=false;await render();$("message").textContent="本群配置 v"+r.version+" 已保存，新局使用新规则。";}catch(err){error(err);}};
for(const id of ["modelForm","dialogForm","scheduleForm"])$(id).addEventListener("input",()=>{configDirty=true;});
$("scheduleForm").onsubmit=async e=>{e.preventDefault();try{
  const fields=Object.fromEntries(new FormData(e.target));
  if(fields.id){fields.id=Number(fields.id);fields.version=Number(fields.version);}else{delete fields.id;delete fields.version;}
  await api("api/schedule",{...fields,body:fields.body||"",catchup:e.target.elements.catchup.checked,group:$("group").value});configDirty=false;resetSchedule();await render();$("message").textContent="本群通知已保存，请核对列表中的微信授权状态。";
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
        if(result.game_card && !result.media?.card){
          const image=document.createElement("img");image.alt=result.body;
          image.style.maxWidth="100%";image.src=result.game_card;
          const details=document.createElement("details");
          details.append(el("summary","完整文字回执"),el("p",result.body));
          $("answer").replaceChildren(image,details);
        }else if(result.media?.type==="image"){
          const preview=el("button",result.media.card?"查看钓鱼卡片":"加载规则图片");preview.type="button";preview.className="quiet";
          preview.onclick=()=>{const img=document.createElement("img");img.alt=result.media.card?"钓鱼手记":"规则回复图片";img.style.maxWidth="100%";img.referrerPolicy="no-referrer";img.onerror=()=>img.replaceWith(document.createTextNode("图片暂不可用，请查看文字回执。"));img.src=result.media.url;preview.replaceWith(img);};
          $("answer").append(document.createElement("br"),preview);
        }
        break;}}
  }catch(err){error(err);}finally{b.disabled=false;}};
boot().catch(e=>{if(e.message!=="请登录")$("loginError").textContent=e.message;});

function showControls(){
  const actions={"发送任务":["确认送达","结束跟进"],"积分流水":user.role==="系统管理员"?["发放货币","调分","冲正","撤销误冲正"]:["发放货币"],"定时通知":["停用通知"],"入站异常":["重试入站"],"撤回记录":["反查内容","启用留存","关闭留存"]};
  const history=page==="积分流水" && user.role==="系统管理员";
  $("assetKinds").hidden=!history;
  $("dailyGrant").onclick=()=>choose(["发放货币"]);
  $("historyCorrection").onclick=()=>choose(["冲正","撤销误冲正","调分"]);
  function choose(names){$("controlForm").reset();$("controlForm").elements.action.replaceChildren(...names.map(k=>new Option(k,k)));selectAction();}
  const list=history?["发放货币"]:actions[page]||[];
  $("controls").hidden=!list.length||user.role==="只读人员";
  const form=$("controlForm");form.reset();form.elements.action.replaceChildren(...list.map(k=>new Option(k,k)));
  $("opResult").textContent="";selectAction();
}
function selectAction(){
  const action=$("controlForm").elements.action.value;
  const target=$("controlForm").elements.target;
  $("targetLabel").firstChild.textContent=["冲正","撤销误冲正"].includes(action)?"原积分流水编号":action==="发放货币"?"选择当前群成员":"对象编号或成员 ID";
  $("controlTitle").textContent=action==="发放货币"?"日常资产发放":["冲正","撤销误冲正","调分"].includes(action)?"积分调整与历史纠错":"管理操作";
  target.removeAttribute("list");
  if(action==="发放货币")target.setAttribute("list","grantMembers");
  const unavailable=action==="发放货币" && !grantReady;
  $("controlForm").querySelector("button").disabled=unavailable;
  $("opResult").textContent=unavailable?"当前名册无效，已请求刷新。请稍后点击刷新后再发放。":"";
  $("targetLabel").hidden=["启用留存","关闭留存"].includes(action);
  $("currencyLabel").hidden=$("amountLabel").hidden=action!=="发放货币";
  $("controlForm").elements.amount.disabled=action!=="发放货币";
  $("controlForm").elements.points.disabled=action!=="调分";
  $("pointsLabel").hidden=action!=="调分";
  $("reasonLabel").hidden=["反查内容","关闭留存"].includes(action);
}
$("controlForm").elements.action.onchange=selectAction;
let pendingGrant=null;
$("controlForm").onsubmit=async e=>{
  e.preventDefault();const f=e.target.elements, action=f.action.value, group=$("group").value;
  const submit=e.target.querySelector("button");
  if(submit.disabled)return;
  submit.disabled=true;
  try{
    let result;
    if(action==="反查内容")result=(await api("api/recall",{group,seq:Number(f.target.value)})).text;
    else if(["启用留存","关闭留存"].includes(action)){
      if(action==="启用留存"&&!f.reason.value.trim())throw Error("请先告知群成员，并填写告知记录");
      await api("api/retention",{group,notice:action==="启用留存"?f.reason.value:""});result=action+"已生效";
    }else{
      const payload={group,action:["确认送达","结束跟进"].includes(action)?"核对发送":action,
        target:f.target.value,resolution:action,points:Number(f.points.value),reason:f.reason.value};
      let key=crypto.randomUUID();
      if(action==="发放货币"){
        payload.currency=f.currency.value;
        payload.points=Number(f.amount.value);
        const signature=JSON.stringify([user.name,payload]);
        if(pendingGrant?.signature===signature)key=pendingGrant.key;
        pendingGrant={signature,key};
      }
      if(["发放货币","冲正","撤销误冲正","调分"].includes(action)){
        const detail=action==="发放货币"?payload.points+" "+payload.currency:action==="调分"?payload.points+" 积分":"依据原流水";
        if(!confirm([action,"群组 "+group,"目标 "+payload.target,detail,"原因 "+payload.reason].join("\n")))return;
      }
      result=(await api("api/operation",{...payload,key})).result;
      if(action==="发放货币")pendingGrant=null;
    }
    await render();$("opResult").textContent=result;
  }catch(err){error(err);}finally{submit.disabled=false;}
};

