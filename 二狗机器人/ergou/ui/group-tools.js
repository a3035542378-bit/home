"use strict";

async function renderGroupTools(group,ticket){
  const panel=document.getElementById("groupTools");
  panel.replaceChildren();
  const result=await api("api/group-tools?"+new URLSearchParams({group}));
  if(ticket!==revision)return;
  const canEdit=["运营管理员","系统管理员"].includes(user.role);
  function append(parent,tag,content){
    const node=document.createElement(tag);
    if(content!==undefined)node.textContent=content;
    parent.append(node);
    return node;
  }
  function card(title){
    const article=append(panel,"article");
    append(article,"h2",title);
    return article;
  }
  function makeTable(parent,headers,rows){
    if(!rows.length){append(parent,"p","暂无记录");return;}
    const t=append(parent,"table"),h=t.createTHead().insertRow(),b=t.createTBody();
    for(const heading of headers)append(h,"th",heading);
    for(const values of rows){
      const row=b.insertRow();
      for(const value of values){
        if(value instanceof Node)row.insertCell().append(value);
        else row.insertCell().textContent=value??"—";
      }
    }
  }
  function button(name,callback){
    const node=document.createElement("button");
    node.textContent=name;node.type="button";node.onclick=callback;
    return node;
  }
  function input(parent,label,type="text"){
    const node=append(append(parent,"label",label),"input");node.type=type;
    return node;
  }
  let sending=false;
  async function change(data){
    if(sending||ticket!==revision)return;
    sending=true;
    try{
      await api("api/group-tools",{group,version:result.version,...data});
      if(ticket!==revision)return;
      if(data.action==="alias"){
        const option=Array.from(document.getElementById("group").options).find(o=>o.value===group);
        if(option)option.textContent=data.alias.trim()||group;
      }
      await render();
    }catch(err){if(ticket===revision)error(err);}
    finally{sending=false;}
  }
  const profile=card("群组管理");
  append(profile,"p","微信稳定群 ID："+group);
  if(canEdit){
    const f=append(profile,"form");f.className="inline";
    const alias=input(f,"工作台群昵称");alias.value=result.alias;alias.maxLength=50;
    append(f,"button","保存昵称");
    f.onsubmit=e=>{e.preventDefault();change({action:"alias",alias:alias.value});};
    if(!result.detached)profile.append(button("解除本群绑定",()=>{
      if(confirm("解除 "+(result.alias||group)+"（"+group+"）的机器人绑定？该群将停止采集、回复及定时任务，进行中的游戏会结束。")){
        change({action:"detach",binding:result.binding,confirm:group});
      }
    }));
  }else if(result.alias)append(profile,"p","群昵称："+result.alias);
  if(result.detached)append(profile,"p","已解除绑定");

  const stats=card("近七天群消息（北京时间）");
  makeTable(stats,["日期","收到消息","已处理","活跃成员"],result.daily.map(d=>[d.day,d.received,d.processed,d.users]));
  makeTable(card("今日热门触发词 TOP 10"),["规则触发词","命中次数"],result.keywords.map(k=>[k.keyword,k.hits]));

  const catalog=card("积分兑换规则");
  if(canEdit){
    const f=append(catalog,"form");f.className="inline";
    const name=input(f,"奖励名称"),price=input(f,"所需积分","number");
    name.required=true;name.maxLength=40;price.required=true;price.min=1;price.max=1000000;
    append(f,"button","保存奖励");
    f.onsubmit=e=>{e.preventDefault();change({action:"offer",name:name.value,price:price.valueAsNumber});};
  }
  makeTable(catalog,canEdit?["奖励","所需积分","操作"]:["奖励","所需积分"],result.offers.map(r=>{
    const cells=[r.name,r.price];
    if(canEdit)cells.push(button("下架",()=>change({action:"removeOffer",name:r.name})));
    return cells;
  }));
  const date=stamp=>new Date(stamp*1000).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai"});
  makeTable(card("积分兑换单"),["编号","成员","奖励","积分","申请时间","履约"],result.orders.map(o=>
    [o.id,o.member,o.name,o.price,date(o.created),o.refunded?"积分已冲正":o.fulfilled?date(o.fulfilled):
      (canEdit?button("确认已发放",()=>{
        if(confirm("确认已为该成员发放「"+o.name+"」？"))change({action:"fulfill",id:o.id});
      }):"待发放")]));
  makeTable(card("最近处理错误"),["时间","来源","编号","状态"],result.errors.map(e=>[date(e.at),e.kind,e.id,e.detail]));
}
