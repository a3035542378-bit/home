"use strict";

let disposeVoiceTest=null;
function clearVoiceTest(){
  if(disposeVoiceTest)disposeVoiceTest();
  disposeVoiceTest=null;
}

async function voiceRecording(file){
  if(!file){
    const response=await fetch("voice-sample.wav");
    if(!response.ok)throw Error("示例录音暂时无法读取，请重试或上传录音。");
    file=await response.blob();
  }
  if(!file.size||file.size>60*16000*2+8192)throw Error("请选择 60 秒以内的 16 kHz 单声道 PCM WAV 录音。");
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>resolve(reader.result.split(",")[1]);
    reader.onerror=()=>reject(Error("读取测试录音失败。"));
    reader.readAsDataURL(file);
  });
}

function voiceTestForm(card,group,revisionAtOpen,state,change,refresh){
  const form=el("form","");
  form.className="voice-test";form.autocomplete="off";
  const kind=el("select","");
  if(state.credential_source!=="missing")kind.append(new Option("复测当前凭据","current"));
  kind.append(new Option("API Key","key"),new Option("Access Token","token"));
  const kindLabel=el("label","凭据类型");kindLabel.append(kind);
  const secret=el("input","");
  secret.type="password";secret.maxLength=4096;secret.autocomplete="new-password";secret.spellcheck=false;
  const secretLabel=el("label","百度官方凭据");secretLabel.append(secret);
  const source=el("select","");
  source.append(new Option("示例录音 · 二狗二狗，语音测试","sample"),new Option("上传 WAV 录音","upload"));
  const sourceLabel=el("label","测试录音");sourceLabel.append(source);
  const file=el("input","");
  file.type="file";file.accept=".wav,audio/wav,audio/x-wav";
  const fileLabel=el("label","选择录音文件");fileLabel.append(file,el("small","16 kHz、16 位、单声道 PCM WAV，最长 60 秒。请以“二狗二狗”开头并说出指令。"));
  function fields(){
    secretLabel.hidden=kind.value==="current";
    secret.required=!secretLabel.hidden;
    if(secretLabel.hidden)secret.value="";
    fileLabel.hidden=source.value==="sample";
    file.required=!fileLabel.hidden;
    if(fileLabel.hidden)file.value="";
  }
  fields();
  const test=el("button","测试并启用");test.type="submit";
  const notice=el("p","");notice.setAttribute("role","status");
  const preview=el("div","");preview.className="voice-preview";preview.hidden=true;
  const details=el("dl","");
  const transcript=el("dd",""),reply=el("dd",""),replyTitle=el("dt","合成回复");
  details.append(el("dt","识别文字"),transcript,replyTitle,reply);
  const player=el("audio","");player.controls=true;player.preload="metadata";
  player.setAttribute("aria-label","试听合成回复");
  const activate=el("button","确认启用本群凭据");activate.type="button";
  preview.append(details,player,activate);
  form.append(kindLabel,secretLabel,sourceLabel,fileLabel,
    el("p","测试会将所选录音交给百度识别，并合成一条供试听的回复。确认启用后，已授权的群聊才会使用本次测试的凭据。"),test,notice,preview);
  card.append(form);

  let run=0,proof=null,objectUrl=null,expiry=null,testing=false,activating=false;
  function invalidate(){
    ++run;proof=null;
    clearTimeout(expiry);
    if(objectUrl){
      player.pause();player.removeAttribute("src");player.load();
      URL.revokeObjectURL(objectUrl);objectUrl=null;
    }
    transcript.textContent="";reply.textContent="";notice.textContent="";
    preview.hidden=true;activate.hidden=true;
  }
  disposeVoiceTest=()=>{
    invalidate();
    secret.value="";file.value="";
  };
  kind.onchange=source.onchange=()=>{fields();invalidate();};
  secret.oninput=file.onchange=invalidate;
  form.onsubmit=async event=>{
    event.preventDefault();
    if(testing||activating||revision!==revisionAtOpen)return;
    invalidate();
    const attempt=run;
    const current=()=>revision===revisionAtOpen&&attempt===run;
    testing=true;test.disabled=true;notice.textContent="正在识别录音并合成试听回复…";
    try{
      if(source.value==="upload"&&!file.files[0])throw Error("请选择测试录音文件。");
      const audio=await voiceRecording(source.value==="upload"?file.files[0]:null);
      if(!current())return;
      const candidate={group,version:state.version,audio};
      if(kind.value!=="current"){
        candidate.kind=kind.value;candidate.secret=secret.value.trim();
        if(!candidate.secret)throw Error("请填写百度官方凭据。");
      }
      const output=await api("api/voice-policy/test",candidate);
      if(!current())return;
      transcript.textContent=output.transcript;
      preview.hidden=false;
      const passed=Boolean(output.ticket&&output.reply&&output.audio&&output.mime==="audio/wav");
      player.hidden=replyTitle.hidden=reply.hidden=!passed;
      if(!passed){
        notice.textContent=output.error||"请用“二狗二狗”开头并说出指令，再测试一次。";
        return;
      }
      const bytes=Uint8Array.from(atob(output.audio),c=>c.charCodeAt(0));
      objectUrl=URL.createObjectURL(new Blob([bytes],{type:"audio/wav"}));
      player.src=objectUrl;reply.textContent=output.reply;
      proof=output.ticket;activate.hidden=false;
      notice.textContent="识别与合成测试通过，可试听回复后确认启用。";
      expiry=setTimeout(()=>{
        if(!current()||activating)return;
        invalidate();notice.textContent="本次测试已过期，请重新测试。";
      },600000);
    }catch(err){
      if(current()){
        invalidate();notice.textContent=err.message;
        if(err.message.includes("CONFLICT"))refresh.hidden=false;
      }
    }finally{
      testing=false;test.disabled=activating;
    }
  };
  player.onerror=()=>{
    if(!objectUrl||player.getAttribute("src")!==objectUrl||!player.error)return;
    invalidate();notice.textContent="浏览器无法播放合成回复，请重新测试。";
  };
  activate.onclick=async()=>{
    if(!proof||activating||revision!==revisionAtOpen)return;
    activating=true;
    for(const control of form.elements)control.disabled=true;
    const confirmed=await change({action:"activate",ticket:proof});
    if(revision!==revisionAtOpen)return;
    activating=false;
    for(const control of form.elements)control.disabled=false;
    if(!confirmed)invalidate();
  };
}

async function renderVoice(group,ticket){
  const panel=document.getElementById("voicePanel");
  clearVoiceTest();panel.replaceChildren();
  const state=await api("api/voice-policy?"+new URLSearchParams({group}));
  if(ticket!==revision)return;
  const canEdit=["运营管理员","系统管理员"].includes(user.role);
  const settingsCard=el("article","");
  const result=el("p","");result.setAttribute("role","status");
  settingsCard.append(el("h2","微信群语音唤醒"),el("p",state.status));
  if(state.native){
    settingsCard.append(el("p","开启后，本群收到的 60 秒以内的新语音会上传到百度识别。以“二狗二狗”开头的内容会按本群的聊天设置处理，回答由百度合成，再发回本群。"));
    if(state.requested&&!state.approved){
      settingsCard.append(el("p","请在本机打开「确认语音唤醒.cmd」，核对群和语音处理范围后确认。"));
    }
  }
  panel.append(settingsCard);
  let saving=false;
  const refresh=el("button","重新读取本群配置");
  refresh.type="button";refresh.className="quiet";refresh.hidden=true;
  refresh.onclick=()=>render().catch(error);
  async function change(data){
    if(saving||ticket!==revision)return false;
    saving=true;result.textContent="";refresh.hidden=true;
    try{
      await api("api/voice-policy",{group,version:state.version,...data});
      if(ticket===revision)await render();
      return true;
    }catch(err){
      if(ticket===revision){result.textContent=err.message;refresh.hidden=false;}
      return false;
    }finally{saving=false;}
  }
  if(canEdit&&(state.native||state.requested)){
    const label=state.requested?(state.approved?"关闭语音唤醒":"取消开启申请"):"申请开启语音唤醒";
    const button=el("button",label);button.type="button";
    button.onclick=()=>change({action:"switch",enabled:!state.requested});
    settingsCard.append(button);
  }
  const creds=el("article","");
  const sources={group:"本群保存的凭据",environment:"服务环境凭据",missing:"尚未配置"};
  creds.append(el("h2","百度语音凭据"),el("p",sources[state.credential_source]));
  if(state.credential_source!=="missing"){
    const verified=state.credential_verified&&state.verified_at;
    creds.append(el("p",verified?"上次验证通过 · "+new Date(state.verified_at*1000).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai"}):"当前凭据待验证。"));
  }
  if(canEdit){
    voiceTestForm(creds,group,ticket,state,change,refresh);
    if(state.credential_source==="group"){
      const clear=el("button","移除本群凭据");
      clear.type="button";clear.className="quiet";
      clear.onclick=()=>{
        if(confirm("移除本群百度语音凭据？"))change({action:"clear"});
      };
      creds.append(clear);
    }
  }
  panel.append(creds,result,refresh);
}
