"use strict";

async function renderWechatLogin(ticket){
  const panel=$("wechatLogin"), card=el("article",""), stateLabel=el("p","");
  const qr=el("img",""), controls=el("div","");
  const start=el("button","获取登录二维码"), cancel=el("button","取消本次扫码");
  const refresh=el("button","刷新状态");
  for(const button of [start,cancel,refresh])button.type="button";
  refresh.className=cancel.className="quiet";
  qr.alt="机器人微信登录二维码";qr.width=220;qr.hidden=true;
  stateLabel.setAttribute("role","status");
  controls.className="actions";controls.append(refresh,cancel,start);
  card.append(el("h2","机器人微信账号"),el("p","请用要登录二狗的微信账号扫一扫，并在手机上确认登录。"),stateLabel,qr,controls);
  panel.replaceChildren(card);

  const labels={
    idle:"尚未登录",retry_start:"上次提交未取得回执，可再次点击获取二维码。",
    starting:"正在生成登录二维码…",queued:"正在排队生成登录二维码…",running:"插件正在处理登录请求…",
    resuming:"正在恢复微信连接…",authenticating:"手机已确认，正在登录…",
    awaiting_scan:"等待手机扫码",awaiting_approval:"已扫码，请在手机微信上确认登录。",
    expired:"二维码已过期，请重新获取。",cancelled:"本次扫码已取消。",
    succeeded:"微信已确认登录，正在核对连接状态。",
    rejected:"手机端已拒绝登录。",failed:"登录失败，可重新获取二维码。",
    needs_login:"微信要求重新登录。",approval_required:"请处理手机微信上的验证提示，再重新登录。",
    challenge_required:"请先在手机微信上完成验证，再重新登录。"
  };
  let state={}, timer=null, busy=false, imageKey="";
  const visible=()=>ticket===revision && card.isConnected;
  const clearQr=()=>{qr.hidden=true;qr.removeAttribute("src");imageKey="";};
  function draw(next){
    state=next;
    const active=["starting","queued","running","resuming","awaiting_scan","awaiting_approval","authenticating"].includes(state.state);
    stateLabel.textContent=state.state==="online"?"已登录 · "+state.account:labels[state.state]||"请刷新登录状态。";
    if(state.hint)stateLabel.textContent+=" "+state.hint;
    start.hidden=active||state.state==="online";
    cancel.hidden=!active||!state.attempt;
    if(active && state.generation){
      const query=new URLSearchParams({attempt:state.attempt,generation:String(state.generation)}).toString();
      if(query!==imageKey){
        imageKey=query;qr.hidden=true;
        qr.onload=()=>{if(visible()&&imageKey===query)qr.hidden=false;};
        qr.onerror=()=>{if(visible()&&imageKey===query){clearQr();stateLabel.textContent="二维码已更新或暂时不可用，正在核对…";}};
        qr.src="api/wechat-login/qr?"+query;
      }
    }else clearQr();
    if(active)timer=setTimeout(()=>{if(visible())update();},2200);
    if(state.state==="succeeded")timer=setTimeout(()=>{if(visible())update();},3500);
  }
  async function update(data){
    if(busy||!visible())return;
    clearTimeout(timer);busy=true;
    start.disabled=cancel.disabled=refresh.disabled=true;
    try{
      const next=await api("api/wechat-login",data);
      if(visible())draw(next);
    }catch(err){
      if(visible()){clearQr();stateLabel.textContent=err.message;cancel.hidden=start.hidden=true;}
    }finally{
      busy=false;start.disabled=cancel.disabled=refresh.disabled=false;
    }
  }
  start.onclick=()=>update({action:"start"});
  cancel.onclick=()=>update({action:"cancel",attempt:state.attempt});
  refresh.onclick=()=>update();
  cancel.hidden=start.hidden=true;stateLabel.textContent="正在核对微信登录状态…";
  await update();
}
