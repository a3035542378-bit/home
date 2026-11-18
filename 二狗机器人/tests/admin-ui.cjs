"use strict";
// Run with NODE_PATH pointing to playwright, and ERGOU_PYTHON / ERGOU_BROWSER if needed.
// The Python fixture owns its temporary database and shuts down when stdin closes.
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { randomUUID } = require("node:crypto");
const { existsSync } = require("node:fs");
const path = require("node:path");
const { createInterface } = require("node:readline");
const { chromium } = require("playwright");

const fixture = `
import io,json,sys,tempfile,threading,wave
from pathlib import Path
from ergou import admin,db,models,speech,web
from ergou.__main__ import worker
mount=sys.argv[1]
original=web.Handler.route
def mounted_route(self, connection):
    if not self.path.startswith(mount):
        return self.respond(404,{"error":"outside test mount"})
    self.path="/"+self.path[len(mount):]
    return original(self, connection)
web.Handler.route=mounted_route
with tempfile.TemporaryDirectory(prefix="ergou-ui-") as folder:
    path=Path(folder)/"ui.sqlite"
    db.initialize(path)
    rooms=("ui-room","ui-room-z")
    db.demo(path,rooms)
    with db.closing_db(path) as connection:
        password=json.loads(sys.stdin.readline())
        admin.user(connection,"ui-ops",password,"运营管理员",rooms)
        admin.user(connection,"ui-reader",password,"只读人员",rooms)
        admin.user(connection,"ui-owner",password,"系统管理员",[])
        # A previously verified model is the UI fixture. This server only runs local command handling.
        connection.execute("INSERT INTO chat_models VALUES('ui-room',1,'deepseek','deepseek-flash',?,1)",(b'fixture',))
    def model_fixture(provider,model,key,messages):
        if provider=="openai" and model=="gpt-ui-found" and key=="ui-openai-key" and len(messages)==1:
            return "OK"
        raise ValueError("测试供应商配置不匹配")
    models.complete=model_fixture
    def openai_model_fixture(key):
        if key=="ui-empty":return []
        if key=="ui-openai-key":return ["gpt-ui-found"]
        raise ValueError("测试密钥验证失败")
    models.openai_model_ids=openai_model_fixture
    def baidu_fixture(host,route,body,key,limit):
        if key=="ui-failure":
            raise ValueError("百度语音识别鉴权失败")
        if host=="vop.baidu.com":
            transcript="今天吃什么" if body["len"]==32000 else "二狗，二狗，语音测试。"
            return "application/json",json.dumps({"err_no":0,"result":[transcript]}).encode()
        if host!="aip.baidubce.com":
            raise AssertionError(host)
        audio=io.BytesIO()
        with wave.open(audio,"wb") as wav:
            wav.setparams((1,2,16000,0,"NONE","not compressed"))
            wav.writeframes(bytes(3200))
        return "audio/wav",audio.getvalue()
    speech._post=baidu_fixture
    server=web.server(path,0)
    stop=threading.Event()
    web_thread=threading.Thread(target=server.serve_forever)
    business=threading.Thread(target=worker,args=(path,stop,"business"))
    business.start()
    web_thread.start()
    print(server.server_port,flush=True)
    sys.stdin.read()
    server.shutdown()
    web_thread.join()
    server.server_close()
    stop.set()
    business.join()
`;

async function run(mount) {
  const python = process.env.ERGOU_PYTHON || "python";
  const backend = spawn(python, ["-c", fixture, mount], {
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, PYTHONUTF8: "1", ERGOU_BAIDU_SPEECH_KEY: "", ERGOU_BAIDU_SPEECH_TOKEN: "" },
    windowsHide: true, stdio: ["pipe", "pipe", "inherit"],
  });
  const exited = new Promise((resolve,reject) => {
    backend.on("exit", code => code === 0 ? resolve() : reject(Error("UI fixture exit " + code)));
    backend.on("error", reject);
  });
  const lines = createInterface({ input: backend.stdout });
  const portReady = new Promise(resolve => lines.once("line", line => resolve(Number(line))));
  const password = randomUUID();
  backend.stdin.write(JSON.stringify(password) + "\n");
  let browser;
  try {
    const port = await Promise.race([portReady, exited.then(() => { throw Error("Fixture stopped early"); })]);
    const executablePath = process.env.ERGOU_BROWSER || [
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
      "C:/Program Files/Google/Chrome/Application/chrome.exe",
    ].find(existsSync);
    browser = await chromium.launch({ executablePath, headless: true });
    const page = await browser.newPage();
    const jsErrors = [];
    page.on("pageerror", e => jsErrors.push(e.message));
    page.setDefaultTimeout(7000);
    const nav = name => page.locator("#nav").getByRole("button", { name, exact: true }).click();
    const waitText = (selector, text) => page.locator(selector).filter({ hasText: text }).waitFor();
    async function say(text, mention, expected) {
      await page.locator("#simulate input[name=text]").fill(text);
      await page.locator("#simulate input[name=mention]").setChecked(mention);
      await page.locator("#simulate button").click();
      await waitText("#answer", expected);
    }
    await page.goto("http://127.0.0.1:" + port + mount);
    await page.getByLabel("管理员账号").fill("ui-ops");
    await page.getByLabel("密码", {exact:true}).fill(password);
    await page.locator("#login button").click();
    await say("二狗积分", false, "本群积分");
    await nav("成员通知");
    await page.getByRole("button",{name:"关闭新人入群欢迎",exact:true}).click();
    await page.getByRole("button",{name:"开启退群提醒",exact:true}).click();
    await nav("群组运营"); await nav("成员通知");
    await page.getByRole("button",{name:"开启新人入群欢迎",exact:true}).waitFor();
    await page.getByRole("button",{name:"关闭退群提醒",exact:true}).waitFor();
    await nav("大模型配置");
    await waitText("#dialogState","当前模式：智能对话");
    const modelForm=page.locator("#modelForm");
    const provider=modelForm.getByLabel("官方供应商"),modelKey=modelForm.getByLabel("官方 API Key");
    const keyLink=modelForm.getByRole("link",{name:"管理 OpenAI API Key"});
    assert.equal(await keyLink.count(),0);
    await modelKey.fill("ui-unused-deepseek-key");
    await provider.selectOption("openai");
    await keyLink.waitFor();
    assert.equal(await keyLink.getAttribute("href"),"https://platform.openai.com/api-keys");
    assert.equal(await modelKey.inputValue(),"");
    assert.equal(await modelKey.evaluate(input=>input.required),true);
    const verifyModel=modelForm.getByRole("button",{name:"测试并启用"});
    const modelList=modelForm.getByLabel("可用模型");
    assert.equal(await modelForm.getByLabel("模型 ID").isVisible(),false);
    assert.equal(await verifyModel.isDisabled(),true);
    await modelKey.fill("ui-bad-key");await modelKey.press("Tab");
    await waitText("#openaiModelsStatus","测试密钥验证失败");
    assert.equal(await verifyModel.isDisabled(),true);
    await modelKey.fill("ui-empty");await modelKey.press("Tab");
    await waitText("#openaiModelsStatus","未返回模型");
    await modelKey.fill("ui-openai-key");
    await modelKey.press("Tab");
    await modelList.selectOption("gpt-ui-found");
    assert.equal(await verifyModel.isEnabled(),true);
    await modelKey.fill("ui-other");
    assert.equal(await verifyModel.isDisabled(),true);
    assert.equal(await modelList.locator("option").count(),1);
    let received,release,responded;
    const pending=new Promise(resolve=>{received=resolve});
    const resume=new Promise(resolve=>{release=resolve});
    const completed=new Promise(resolve=>{responded=resolve});
    const delayed=async route=>{
      received();await resume;
      await route.fulfill({json:{models:["gpt-stale"]}});responded();
    };
    await page.route("**/api/chat-model/models",delayed);
    await modelKey.press("Tab");await pending;
    await provider.selectOption("deepseek");
    release();await completed;
    await page.unroute("**/api/chat-model/models",delayed);
    assert.equal(await modelList.isVisible(),false);
    assert.equal(await modelList.locator('option[value="gpt-stale"]').count(),0);
    await provider.selectOption("openai");
    await modelKey.fill("ui-openai-key");await modelKey.press("Tab");
    await modelList.selectOption("gpt-ui-found");
    await verifyModel.click();
    await waitText("#modelResult","测试通过");
    await waitText("#activeModel","OpenAI");
    await page.waitForFunction(()=>document.querySelector('[name="openaiModel"]').value==="gpt-ui-found");
    const refreshed=page.waitForResponse(response=>response.url().endsWith("/api/chat-model/models")&&response.status()===200);
    await modelForm.getByRole("button",{name:"刷新模型列表"}).click();
    await refreshed;
    await page.waitForFunction(()=>document.querySelector('[name="openaiModel"]').value==="gpt-ui-found");
    assert.equal(await modelKey.inputValue(),"");
    assert.equal(await modelKey.evaluate(input=>input.required),false);
    await provider.selectOption("deepseek");
    assert.equal(await keyLink.count(),0);
    assert.equal(await modelKey.evaluate(input=>input.required),true);
    await page.locator("#memberChoices").selectOption("ui-ui-ops");
    await page.locator("#addMember").click();
    await page.locator("#dialogForm button[type=submit], #dialogForm button:not([type])").click();
    await waitText("#dialogResult","管理员名单已保存");
    await nav("运行概览");
    await say("关闭智能对话", true, "关闭");
    await nav("大模型配置");
    await waitText("#dialogState","本地回复（密钥已保留）");

    await nav("自定义回复");
    const rules=page.locator("#replyRulesPanel");
    await rules.getByRole("button",{name:"添加规则"}).click();
    await rules.locator("[name=keyword]").fill("界面验收");
    await rules.locator("[name=content]").fill("本地命中成功");
    await rules.getByRole("button",{name:"保存本群规则"}).click();
    await waitText("#replyRulesPanel","已生效");
    await nav("运行概览");
    await say("二狗界面验收", false, "本地命中成功");
    await nav("自定义回复");
    await rules.getByRole("button",{name:"移除"}).click();
    await rules.getByRole("button",{name:"保存本群规则"}).click();
    await waitText("#replyRulesPanel","已生效");
    await nav("群组运营");
    await page.getByLabel("工作台群昵称").fill("界面测试群");
    await page.getByRole("button",{name:"保存昵称"}).click();
    await page.waitForFunction(() => document.querySelector("#group").selectedOptions[0].text==="界面测试群");
    await page.getByLabel("奖励名称").fill("选片权");
    await page.getByLabel("所需积分").fill("2");
    await page.getByRole("button",{name:"保存奖励"}).click();
    await waitText("#groupTools td","选片权");
    await waitText("#groupTools td","界面验收");
    await nav("运行概览");
    await say("开启智能对话", true, "已开启");
    await nav("大模型配置");
    await waitText("#dialogState","当前模式：智能对话");
    await nav("语音唤醒");
    const voice=page.locator("#voicePanel");
    const secret=voice.getByLabel("百度官方凭据",{exact:true});
    const testVoice=voice.getByRole("button",{name:"测试并启用",exact:true});
    const activateVoice=voice.getByRole("button",{name:"确认启用本群凭据",exact:true});
    const voiceState=async(group="ui-room")=>(await page.request.get(new URL("api/voice-policy?group="+group,page.url()).href)).json();
    await secret.fill("ui-candidate");
    await testVoice.click();
    await waitText("#voicePanel dd","二狗，二狗，语音测试。");
    await page.waitForFunction(()=>document.querySelector("#voicePanel audio")?.readyState>=1);
    assert.equal(await voice.locator("audio").evaluate(async audio=>{
      await audio.play();audio.pause();return audio.duration;
    }),0.1);
    assert.equal((await voiceState()).credential_verified,false);
    await secret.fill("ui-candidate-edited");
    assert.equal(await activateVoice.count(),0);
    await testVoice.click();await activateVoice.waitFor();
    await page.locator("#group").selectOption("ui-room-z");
    await voice.getByText("尚未配置",{exact:true}).waitFor();
    assert.equal(await activateVoice.count(),0);
    assert.equal((await voiceState()).credential_verified,false);
    await page.locator("#group").selectOption("ui-room");
    await secret.fill("ui-candidate");
    await testVoice.click();await activateVoice.click();
    await voice.getByText(/上次验证通过/).waitFor();
    assert.equal((await voiceState()).credential_verified,true);
    const version=(await voiceState()).version;
    await voice.getByLabel("凭据类型").selectOption("key");
    await secret.fill("ui-failure");
    await testVoice.click();await waitText("#voicePanel [role=status]","百度语音识别鉴权失败");
    assert.equal((await voiceState()).version,version);
    await voice.getByLabel("凭据类型").selectOption("current");
    await voice.getByLabel("测试录音").selectOption("upload");
    const wav=Buffer.alloc(44+32000);
    wav.write("RIFF");wav.writeUInt32LE(wav.length-8,4);wav.write("WAVEfmt ",8);
    wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);
    wav.writeUInt32LE(16000,24);wav.writeUInt32LE(32000,28);wav.writeUInt16LE(2,32);
    wav.writeUInt16LE(16,34);wav.write("data",36);wav.writeUInt32LE(32000,40);
    await voice.locator("input[type=file]").setInputFiles({name:"test.wav",mimeType:"audio/wav",buffer:wav});
    await testVoice.click();await waitText("#voicePanel dd","今天吃什么");
    assert.equal(await activateVoice.count(),0);
    assert.equal((await voiceState()).version,version);
    await page.locator("#logout").click();
    await page.getByLabel("管理员账号").fill("ui-reader");
    await page.getByLabel("密码",{exact:true}).fill(password);
    await page.locator("#login button").click();
    await nav("语音唤醒");await voice.getByText(/上次验证通过/).waitFor();
    assert.equal(await testVoice.count(),0);
    assert.equal(await page.locator("#nav").getByRole("button",{name:"后台账号"}).count(),0);
    await page.locator("#logout").click();
    await page.getByLabel("管理员账号").fill("ui-owner");
    await page.getByLabel("密码",{exact:true}).fill(password);
    await page.locator("#login button").click();
    await nav("积分流水");
    await page.waitForFunction(()=>document.querySelector("#export").download==="积分流水.csv");
    const exportURL=await page.locator("#export").evaluate(link=>link.href);
    assert.equal(new URL(exportURL).pathname,mount+"api/export");
    assert.equal((await page.request.get(exportURL)).status(),200);
    await page.route("**/api/wechat-login",route=>route.fulfill({
      json:{state:"awaiting_scan",attempt:"demo",generation:1}
    }));
    await page.route("**/api/wechat-login/qr?**",route=>route.fulfill({contentType:"image/png",
      body:Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Jc5sAAAAASUVORK5CYII=","base64")
    }));
    await nav("微信扫码登录");
    const qr=page.getByAltText("机器人微信登录二维码");
    await qr.waitFor();
    assert.equal(new URL(await qr.evaluate(img=>img.src)).pathname,mount+"api/wechat-login/qr");
    await nav("后台账号");
    const accounts=page.locator("#adminAccounts");
    await accounts.getByLabel("账号名").fill("ui-new");
    await accounts.getByLabel(/登录密码/).fill(password);
    await accounts.getByLabel("角色").selectOption("只读人员");
    await accounts.getByLabel("ui-room-z",{exact:true}).check();
    await accounts.getByRole("button",{name:"创建账号"}).click();
    await accounts.getByRole("cell",{name:"ui-new",exact:true}).waitFor();
    assert.equal(await accounts.getByLabel(/登录密码/).inputValue(),"");
    await page.locator("#logout").click();
    await page.getByLabel("管理员账号").fill("ui-new");
    await page.getByLabel("密码",{exact:true}).fill(password);
    await page.locator("#login button").click();
    await page.locator("#desk").waitFor();
    assert.deepEqual(await page.locator("#group option").allTextContents(),["ui-room-z"]);
    assert.deepEqual(jsErrors,[]);
    console.log("PASS Chromium: console mount "+mount+", CSV export and WeChat QR");
    console.log("PASS Chromium: system administrator created a scoped read-only login through the account form");
    console.log("PASS Chromium: OpenAI key link, model discovery, empty/error responses, credential isolation and verified activation");
    console.log("PASS Chromium: sample/uploaded voice, audio playback, two-step activation, failed replacement, scope and read-only role");
    console.log("PASS Chromium: independent membership switches, scoped admin selection, @ switch, local rules, group alias, redemptions and keyword stats");
  } finally {
    if (browser) await browser.close();
    backend.stdin.end();
    await exited;
    lines.close();
  }
}
(async () => {
  await run("/");
  await run("/ergou/");
})().catch(e => { console.error(e); process.exitCode=1; });
