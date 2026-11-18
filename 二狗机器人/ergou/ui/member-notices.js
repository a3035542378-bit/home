"use strict";

async function renderMemberNotices(group,ticket){
  const panel=document.getElementById("memberNotices");
  panel.replaceChildren();
  const state=await api("api/member-notices?"+new URLSearchParams({group}));
  if(ticket!==revision)return;
  const canEdit=["系统管理员","运营管理员"].includes(user.role);
  const refresh=el("button","刷新状态");
  refresh.type="button";refresh.className="quiet";
  refresh.onclick=()=>render().catch(error);
  panel.append(refresh);
  for(const item of state.items){
    const card=el("article","");
    const status=el("p","当前状态："+item.status);
    card.append(el("h2",item.label),status);
    if(state.native&&item.enabled){
      card.append(el("p",item.baseline_ready?"已核实本项成员基线":"等待核实本项成员基线"));
    }
    if(state.native&&item.requested&&!item.enabled&&item.status==="等待本机确认"){
      card.append(el("p","请在本机打开「确认成员通知.cmd」，核对本群和「"+item.label+"」后单独确认。"));
    }
    if(canEdit&&(item.supported||item.requested)){
      const label=item.requested?(item.status==="等待本机确认"?"取消开启申请":"关闭"):
                  state.native?"申请开启":"开启";
      const button=el("button",label);button.type="button";
      button.setAttribute("aria-label",label+item.label);
      button.onclick=async()=>{
        button.disabled=true;
        try{
          await api("api/member-notices",{group,kind:item.kind,enabled:!item.requested,version:item.version});
          if(ticket===revision)await render();
        }catch(e){
          if(ticket===revision){status.textContent=e.message;button.disabled=false;}
        }
      };
      card.append(button);
    }
    panel.append(card);
  }
  if(state.native){
    if(state.observed){
      const when=new Date(state.observed*1000).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai"});
      panel.append(el("p","最近一次完整名册核对："+when+"（北京时间）"));
    }
    panel.append(el("p","首次同步和重连时建立成员基线。后续核实成员名单发生变化时，才按已生效的开关发送文字通知。"));
  }
}
