import http.cookiejar
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from ergou import admin,bridge,jobs,operations,plugins,queries,retention,web
from ergou.db import connect,demo,initialize
from ergou.engine import receive,step


class Integration(unittest.TestCase):
    def test_scoped_currency_grants(self):
        data=dict(action="发放货币",currency="鱼币",target="new-member",points=2000,key="grant-1",reason="活动奖励")
        grant=lambda user,group,fields: operations.act(self.db,user,group,fields)
        operator=dict(name="ops",role="运营管理员",scopes='["one"]')
        with self.assertRaises(PermissionError):
            grant(operator,"two",data)
        with self.assertRaises(PermissionError):
            grant(dict(operator,role="只读人员"),"one",data)
        self.db.execute("INSERT INTO simulation_members VALUES(?,?)", ("one","new-member"))
        result=grant(operator,"one",data)
        self.assertEqual(result,grant(operator,"one",data))
        self.assertEqual(self.db.execute("SELECT coins FROM fishing_wallets WHERE grp='one' AND member='new-member'").fetchone()[0],2030)
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            grant(operator,"one",dict(data,currency="积分"))
        for change in (dict(currency="水晶"),dict(currency="金币"),dict(points=-1),dict(points=True),dict(points=0)):
            with self.assertRaises(ValueError):
                grant(operator,"one",dict(data,key="invalid",**change))
        grant(operator,"one",dict(data,key="grant-2",currency="积分"))
        self.assertEqual(self.db.execute("SELECT SUM(points) FROM ledger WHERE grp='one' AND member='new-member'").fetchone()[0],2000)
        self.assertEqual(self.db.execute("SELECT count(*) FROM audit WHERE action='发放货币'").fetchone()[0],2)

    def test_weekly_participation_and_archive(self):
        from ergou import reports
        from ergou.db import window
        end=window("周榜",time.time())
        start=end-reports.WEEK
        for i,(member,cmd) in enumerate((("a","开始 成语接龙"),("b","加入 G01"),
                                         ("b","退出 G01"),("b","加入 G01"),("a","结束 G01"))):
            receive(self.db,"sim-account","one",member,str(i),{"text":"二狗 "+cmd},now=start+30+i)
            step(self.db)
        first=int(start//60)
        self.db.executemany("INSERT INTO observation VALUES('one',?)",[(first,),(first+2,)])
        result=reports.weekly(self.db,"one",end)
        self.assertEqual((2,2,1,2,2),(result["参与人次"],result["参与人数"],result["取消局数"],
                                     result["在线采样分钟"],result["缺口段数"]))
        jobs.cleanup(self.db,end+9*3600)
        self.assertEqual(2,reports.archive(self.db,"one")[0]["参与人次"])

    def test_scoped_monitor_and_alert_recovery(self):
        from ergou.monitor import overview, sample_alerts
        now = time.time()
        reader = {"role":"只读人员","scopes":'["one"]'}
        self.assertEqual({"configured":1,"serviceable":1},overview(self.db,reader))
        self.db.execute("UPDATE groups SET paused=1 WHERE id='two'")
        sample_alerts(self.db,now)
        sample_alerts(self.db,now+60)
        self.assertEqual([],admin.view(self.db,reader,"one","运行告警"))
        self.assertEqual({"configured":2,"serviceable":1},overview(self.db,self.admin))
        self.db.execute("UPDATE groups SET paused=0 WHERE id='two'")
        sample_alerts(self.db,now+120)
        alerts=admin.view(self.db,self.admin,"two","运行告警")
        self.assertEqual(1,len(alerts))
        self.assertEqual(("已恢复",now,now+120),(alerts[0]["状态"],alerts[0]["首次发现"],alerts[0]["恢复时间"]))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/"db"
        initialize(self.path);demo(self.path,("one","two"));self.db=connect(self.path)
        self.admin=dict(name="admin",role="系统管理员",scopes="[]")
    def tearDown(self):
        self.db.close();self.temp.cleanup()

    def test_bridge_auth_and_binding(self):
        key="a"*40
        bridge.enroll(self.db,"real-id","authorized",key)
        hb=dict(state="ONLINE",actual_account="wrong",groups=["authorized","other"],adapter_version="test-1",capabilities=dict(stable_ids=True,send=True,receive=True))
        self.assertEqual("NEED_USER_ACTION",bridge.endpoint(self.db,"heartbeat",key,hb)["state"])
        hb["actual_account"]="real-id"
        bridge.endpoint(self.db,"heartbeat",key,hb)
        event=dict(group_id="other",sender_id="u",source_message_id="01",payload={"text":"二狗 帮助"})
        with self.assertRaises(ValueError):bridge.endpoint(self.db,"event",key,event)
        event["group_id"]="authorized"
        seq=bridge.endpoint(self.db,"event",key,event)
        self.assertEqual(seq,bridge.endpoint(self.db,"event",key,event))
        step(self.db)
        task=bridge.endpoint(self.db,"claim",key,{})["task"]
        self.assertIn("二狗菜单",task["body"])
        ack=dict(task=task["id"],attempt=task["attempt"],state="ACKNOWLEDGED")
        self.assertTrue(bridge.endpoint(self.db,"result",key,ack)["updated"])
        self.assertFalse(bridge.endpoint(self.db,"result",key,ack)["updated"])
        jobs.tick(self.db,time.time()+40)
        self.assertEqual("RECONNECTING",self.db.execute("SELECT state FROM account WHERE id='real-id'").fetchone()[0])

    def test_plugin_versions_and_isolation(self):
        src=Path("examples/letter.json")
        plugins.install(self.db,src)
        def send(i,s):
            receive(self.db,"sim-account","one","p",str(i),{"text":"二狗 "+s});step(self.db)
        send(1,"开始 街角信差");send(2,"G01 取信")
        m=json.loads(src.read_text(encoding="utf-8"));m["version"]="2"
        m["states"]["携信"]["去西街"]="错门"
        m["states"]["携信"]["去南街"]="收件处"
        tmp=self.path.parent/"update.json";tmp.write_text(json.dumps(m),encoding="utf-8")
        plugins.install(self.db,tmp)
        for i,cmd in enumerate(("去西街","签收","交回执"),3):send(i,"G01 "+cmd)
        self.assertEqual("FINISHED",self.db.execute("SELECT state FROM games").fetchone()[0])
        with self.assertRaisesRegex(ValueError,"超时"):
            plugins.move(m,{"node":"邮局"},"取信",timeout=0.00001)
        m["start"]="missing";tmp.write_text(json.dumps(m),encoding="utf-8")
        with self.assertRaises(ValueError):plugins.install(self.db,tmp)
        self.assertEqual("2",plugins.active(self.db)["街角信差"]["version"])
        plugins.install(self.db,src)
        self.assertEqual("1.0",plugins.active(self.db)["街角信差"]["version"])

    def test_recall_ttl_lru(self):
        cache=retention.RecallCache(2,100)
        cache.put("a","a",10);cache.put("b","b",11);cache.get("a",12);cache.put("c","c",13)
        self.assertIsNone(cache.get("b",14));self.assertIsNone(cache.get("a",86410))
        retention.configure(self.db,self.admin,"one","模拟群已告知")
        receive(self.db,"sim-account","one","u","original",{"text":"example"});step(self.db)
        seq=receive(self.db,"sim-account","one","u","deleted",{"original_source":"original"},kind="revoke");step(self.db)
        self.assertEqual("example",retention.read(self.db,self.admin,"one",seq)["text"])
        retention.configure(self.db,self.admin,"one","")
        self.assertFalse(retention.read(self.db,self.admin,"one",seq)["available"])

    def test_adjustment_idempotence(self):
        self.db.execute("INSERT OR IGNORE INTO simulation_members VALUES('one','u')")
        op=dict(action="调分",target="u",points=7,key="k",reason="人工校对")
        for _ in range(2):operations.act(self.db,self.admin,"one",op)
        reverse=dict(action="冲正",target=1,key="r",reason="误记")
        operations.act(self.db,self.admin,"one",reverse)
        with self.assertRaises(ValueError):operations.act(self.db,self.admin,"one",reverse|dict(key="r2"))
        self.assertEqual(0,self.db.execute("SELECT SUM(points) FROM ledger").fetchone()[0])

    def test_domestic_carrier(self):
        sent={}
        def fake(url,fields,deadline):
            self.assertEqual(url,queries.KDN);sent.update(fields)
            return {"Success":True,"State":"3","Traces":[{"AcceptStation":"private address"}]}
        with patch.dict(os.environ,{"ERGOU_KDN_ID":"id","ERGOU_KDN_KEY":"private"}):
            self.assertIn("已签收",queries.lookup("快递","圆通 123456",fake))
        self.assertEqual("1002",sent["RequestType"])
        self.assertEqual({"ShipperCode":"YTO","LogisticCode":"123456"},json.loads(sent["RequestData"]))

    def test_http_auth_scope_and_logout(self):
        admin.user(self.db,"group-admin","password-fixture-123","群管理员",["one"])
        http=web.server(self.path,0)
        thread=threading.Thread(target=http.serve_forever);thread.start()
        client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor())
        def req(path,body=None):
            r=urllib.request.Request(f"http://127.0.0.1:{http.server_port}"+path,data=json.dumps(body).encode() if body is not None else None,headers={"Content-Type":"application/json"})
            with client.open(r,timeout=4) as response:return response.read()
        try:
            self.assertIn(b"app.js",req("/"))
            with self.assertRaises(urllib.error.HTTPError) as err:req("/api/me")
            self.assertEqual(401,err.exception.code)
            with self.assertRaises(urllib.error.HTTPError) as err:req("/api/reply-diagnostics?group=one")
            self.assertEqual(401,err.exception.code)
            req("/api/login",dict(name="group-admin",password="password-fixture-123"))
            self.assertEqual(["one"],json.loads(req("/api/me"))["groups"])
            diagnostics=json.loads(req("/api/reply-diagnostics?group=one"))
            self.assertEqual(diagnostics["health"]["mode"],"simulation")
            self.assertEqual(diagnostics["records"],[])
            for route in ("/api/status?group=two","/api/export?group=two","/api/view?group=two","/api/reply-diagnostics?group=two"):
                with self.assertRaises(urllib.error.HTTPError) as err:req(route)
                self.assertEqual(403,err.exception.code)
            req("/api/config",dict(group="one",version=1,patch={"prefix":"小狗"}))
            req("/api/logout",{})
            with self.assertRaises(urllib.error.HTTPError):req("/api/me")
        finally:http.shutdown();http.server_close();thread.join()

