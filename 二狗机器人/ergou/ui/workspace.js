"use strict";
const groupSections={"群组概览":"群组概览","成员名册":"成员管理","大模型配置":"智能交互","游戏目录":"游戏娱乐","群组运营":"群运营","积分":"成员资产","群消息接收记录":"运行记录"};
const groupLinks={"游戏目录":["群配置","会话"],"群组运营":["群配置","成员通知","定时通知","周报","周报归档"],"积分":["积分流水"],"群消息接收记录":["运行告警","规则命中","发送任务","入站异常"],"大模型配置":["语音唤醒","自定义回复"]};
const virtualPages=["群组概览","成员名册"];
const stateLabels={PENDING:"待处理",SENDING:"发送中",ACKNOWLEDGED:"已确认发送",UNKNOWN:"发送结果未知",DONE:"处理完成",CHAT:"对话处理",REJECTED:"已拒绝",FAILED:"失败",RATE_LIMITED:"已限流",RETRY_WAIT:"等待重试",CANCELLED:"已取消",EXPIRED:"已过期"};
function jump(label,name){
  const b=el("button",label);b.type="button";b.className="quiet";b.onclick=()=>routeTo(name).catch(error);return b;
}
function sectionBar(){
  const panel=$("groupTabs");panel.replaceChildren();
  panel.hidden=!$("group").value||["运行概览","我的群组","微信扫码登录","后台账号","后台权限","审计"].includes(page);
  if(panel.hidden)return;
  for(const [key,title] of Object.entries(groupSections)){
    if(!available(key))continue;
    const b=jump(title,key);if(page===key)b.setAttribute("aria-current","page");panel.append(b);
  }
  const links=groupLinks[page]?.filter(available)||[];
  if(links.length){const sub=el("div","");sub.className="sectionLinks";for(const name of links)sub.append(jump(name,name));panel.append(sub);}
}
async function detailPage(group,ticket){
  const panel=$("groupDetail");panel.replaceChildren(el("p","正在读取本群资料…"));
  if(page==="群组概览"){
    const st=await api("api/status?"+new URLSearchParams({group}));if(ticket!==revision)return;
    const card=el("article",""),grid=el("div","");grid.className="groupFacts";
    card.append(el("h2",user.group_aliases[group]||group),grid);
    for(const [label,value] of [["绑定账号",st.account],["接入方式",st.mode==="simulation"?"本地模拟":"微信适配器"],["群组开关",st.paused||!st.config.enabled?"已暂停":"已启用"],["本群累计入站",st.received],["待处理告警",st.alerts]]){
      const fact=el("div","");fact.append(el("small",label),el("strong",value));grid.append(fact);
    }
    card.append(jump("配置本群","群配置"),jump("查看运行记录","群消息接收记录"));
    panel.replaceChildren(card);return;
  }
  const roster=await api("api/grant-members?"+new URLSearchParams({group}));if(ticket!==revision)return;
  const card=el("article",""),search=el("input",""),list=el("ul","");
  card.append(el("h2","本群成员名册"),el("p",roster.ready?"本次核验时可用 · "+roster.members.length+" 位成员":"当前名册无效，已请求刷新；暂不可新发放。"),jump("刷新名册",page));
  if(roster.ready){
    search.type="search";search.placeholder="搜索昵称或成员 ID";search.setAttribute("aria-label",search.placeholder);card.append(search,list);
    const update=()=>{const matches=roster.members.filter(id=>(id+" "+roster.labels[id]).toLowerCase().includes(search.value.trim().toLowerCase()));
      list.replaceChildren(...matches.slice(0,100).map(id=>el("li",roster.labels[id]+" · "+id)));
      if(matches.length>100)list.append(el("li","显示前100位，请输入关键词缩小范围"));if(!matches.length)list.append(el("li","没有匹配成员"));};
    search.oninput=update;update();
  }
  panel.replaceChildren(card);
}
function resetSchedule(){
  $("scheduleForm").reset();$("scheduleForm").elements.id.value="";$("scheduleForm").elements.version.value="";
  $("scheduleMode").textContent="新建通知";scheduleFields();
}
function editSchedule(row){
  const f=$("scheduleForm").elements;
  const bjInput=v=>v?new Date((v+28800)*1000).toISOString().slice(0,16):"";
  f.id.value=row.编号;f.version.value=row.版本;f.time.value=bjInput(row.下次执行);f.until.value=bjInput(row.结束时间);
  f.kind.value=({"天气":"weather","香港要闻":"news","天气与香港要闻":"weather_news"})[row.类型]||"text";
  f.body.value=row.内容;f.period.value=row.周期;f.catchup.checked=!!row.补发;
  $("scheduleMode").textContent="编辑通知 · "+row.类型+"（保存后需按规则重新确认）";scheduleFields();f.time.focus();
}
