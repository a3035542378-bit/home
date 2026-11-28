import csv
import http.client
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import pytest

from ergou import admin, web, csv_export
from ergou.db import closing_db, initialize, demo


@pytest.fixture
def site(tmp_path):
    path=tmp_path/"test.sqlite"
    initialize(path)
    demo(path,("one","two"))
    with closing_db(path) as db:
        admin.user(db,"operator","phase-b-fixture-password","群管理员",["one","two"])
        service=web.server(path,0)
        thread=threading.Thread(target=service.serve_forever)
        thread.start()
        cookie=""
        def request(url,data=None):
            conn=http.client.HTTPConnection("127.0.0.1",service.server_port,timeout=8)
            try:
                conn.request("POST" if data is not None else "GET",url,
                             json.dumps(data) if data is not None else None,
                             {"Content-Type":"application/json","Cookie":cookie})
                response=conn.getresponse()
                return response.status,response.read(),response.getheader("Set-Cookie")
            finally:
                conn.close()
        try:
            status,_,header=request("/api/login",dict(name="operator",password="phase-b-fixture-password"))
            assert status==200
            cookie=header.split(";")[0]
            yield db,request
        finally:
            service.shutdown()
            service.server_close()
            thread.join()


def test_player_catches_exact_member_and_group(site):
    db,request=site
    for group,member,name in (("one","a","鲤鱼"),("one","aa","白条"),("two","a","泥鳅")):
        db.execute("INSERT INTO fishing_wallets(grp,member) VALUES(?,?)",(group,member))
        db.execute("INSERT INTO fishing_pond(grp,member,fish,grams,price) VALUES(?,?,?,900,1)",(group,member,name))
    query=urlencode(dict(name="玩家渔获",group="one",member="a"))
    status,body,_=request("/api/view?"+query)
    assert status==200
    assert [(row["成员"],row["鱼种"]) for row in json.loads(body)]==[("a","鲤鱼")]
    status,body,_=request("/api/export?"+query)
    assert status==200
    assert [row["鱼种"] for row in csv.DictReader(io.StringIO(body.decode("utf-8-sig")))]==["鲤鱼"]


def test_grants(site):
    db,request=site
    base=dict(group="one",action="发放货币",target="member",currency="鱼币",points=7,key="first",reason="测试")
    def grant(**fields):
        return request("/api/operation",base|fields)[0]
    db.execute("INSERT INTO simulation_members VALUES('two','member')")
    assert grant()==400
    assert db.execute("SELECT count(*) FROM fishing_wallets WHERE member='member'").fetchone()[0]==0
    db.execute("INSERT INTO simulation_members VALUES('one','member')")
    with ThreadPoolExecutor(4) as pool:
        assert list(pool.map(lambda _: grant(),range(8)))==[200]*8
    assert grant(points=8)==409
    db.execute("DELETE FROM simulation_members WHERE grp='one'")
    assert grant()==200
    assert grant(key="left")==400
    db.execute("INSERT INTO simulation_members VALUES('one','member')")
    with ThreadPoolExecutor(4) as pool:
        assert list(pool.map(lambda i:grant(key=str(i)),range(4)))==[200]*4
    assert grant(group="two")==200
    balances=dict(db.execute("SELECT grp,coins FROM fishing_wallets WHERE member='member'"))
    assert balances=={"one":65,"two":37}
    for fields in (dict(points=0),dict(points=1.5),dict(currency="其他")):
        assert grant(key="bad",**fields)==400
    assert grant(key="points",currency="积分")==200
    db.execute("CREATE TRIGGER fault BEFORE INSERT ON operations BEGIN SELECT RAISE(ABORT,'fixture'); END")
    assert grant(key="rollback")==503
    assert db.execute("SELECT coins FROM fishing_wallets WHERE grp='one' AND member='member'").fetchone()[0]==65
    assert grant(key="rollback2",currency="积分")==503
    assert db.execute("SELECT sum(points) FROM ledger WHERE grp='one' AND member='member'").fetchone()[0]==7
    db.execute("UPDATE account SET mode='adapter' WHERE id='sim-account'")
    assert grant(key="unknown")==400
    assert db.execute("SELECT count(*) FROM audit WHERE action='管理操作拒绝'").fetchone()[0]>=5


@pytest.mark.parametrize("count",[0,199,200,201,1000])
def test_export(site,count):
    db,request=site
    db.executemany("INSERT INTO audit(at,actor,grp,action,detail) VALUES(?,'private','one',?,'private')",
                   ((i,'=中文,"字段"') for i in range(count)))
    params=dict(group="one",name="审计",start=0,end=max(1,count))
    url="/api/export?"+urlencode(params)
    status,raw,_=request(url)
    assert status==200 and raw.startswith(b"\xef\xbb\xbf")
    records=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert len(records)==count
    assert all(r["操作"]=="'=中文,\"字段\"" and r["操作人"]=="已隐藏" for r in records)
    if count>200:
        _,raw,_=request("/api/view?"+urlencode(params|dict(offset=200)))
        assert len(json.loads(raw))==min(200,count-200)
    assert request("/api/export?"+urlencode(params|dict(name="后台权限")))[0]==403
    assert request("/api/export?"+urlencode(params|dict(start=20,end=1)))[0]==400


def test_snapshot_concurrent_insert(site):
    db,_=site
    for i in range(3):
        db.execute("INSERT INTO audit(at,actor,grp,action,detail) VALUES(0,'fixture','one',?,'')",(str(i),))
    path=db.execute("PRAGMA database_list").fetchone()[2]
    db.execute("BEGIN")
    user=dict(name="ops",role="系统管理员")
    records=csv_export.rows(db,user,"one","审计",{})
    assert next(records)["操作"]=="2"
    with closing_db(path) as other:
        other.execute("INSERT INTO audit(at,actor,grp,action,detail) VALUES(0,'fixture','one','new','')")
    assert [r["操作"] for r in records if r["操作"] in ("0","1","2","new")]==["1","0"]
    db.commit()


def test_admin_boundaries(site):
    db,request=site
    db.execute("UPDATE users SET scopes='[\"one\"]' WHERE name='operator'")
    for url,body in [
        ("/api/config",dict(group="two",version=1,patch={"prefix":"其他"})),
        ("/api/operation",dict(group="two",action="发放货币")),
        ("/api/grant-members?group=two",None),
        ("/api/admin-accounts",None),
        ("/api/export?group=two",None),
    ]:
        assert request(url,body)[0]==403
    db.execute("UPDATE users SET role='只读人员' WHERE name='operator'")
    assert request("/api/operation",dict(group="one",action="发放货币"))[0]==403
    assert request("/api/grant-members?group=one")[0]==403
    db.execute("UPDATE tokens SET expires=0")
    assert request("/api/export?group=one")[0]==401


def test_departure_precedes_grant_commit(site, monkeypatch):
    from ergou import operations
    db,request=site
    db.execute("INSERT INTO simulation_members VALUES('one','departing')")
    reached_transaction=threading.Event()
    original=operations.transaction
    def observed(connection):
        reached_transaction.set()
        return original(connection)
    monkeypatch.setattr(operations,"transaction",observed)
    db.execute("BEGIN IMMEDIATE")
    db.execute("DELETE FROM simulation_members WHERE grp='one' AND member='departing'")
    fields=dict(group="one",action="发放货币",target="departing",currency="鱼币",points=1,key="race",reason="测试")
    with ThreadPoolExecutor(1) as pool:
        result=pool.submit(request,"/api/operation",fields)
        try:
            assert reached_transaction.wait(2)
        finally:
            db.commit()
        assert result.result()[0]==400
    assert db.execute("SELECT count(*) FROM fishing_wallets WHERE member='departing'").fetchone()[0]==0


def test_historical_repair(site):
    from ergou import operations
    db,request=site
    base=dict(group="one",target="operator",action="发放货币",currency="积分",points=10,key="orig",reason="fixture")
    assert request("/api/operation",base)[0]==200
    origin=db.execute("SELECT id FROM ledger WHERE event='orig'").fetchone()[0]
    db.execute("DELETE FROM simulation_members WHERE member='operator'")
    rev=base|dict(action="冲正",target=str(origin),key="reverse")
    assert request("/api/operation",rev)[0]==403
    db.execute("UPDATE users SET role='系统管理员'")
    assert request("/api/operation",rev|dict(group="two"))[0]==400
    assert request("/api/operation",rev)[0]==200
    row=db.execute("SELECT id FROM ledger WHERE kind='冲正'").fetchone()[0]
    restore=rev|dict(action="撤销误冲正",target=str(row),key="restore")
    assert request("/api/operation",restore)[0]==200
    assert request("/api/operation",restore)[0]==200
    assert request("/api/operation",restore|dict(key="other",target="00"+str(row)))[0]==400
    assert db.execute("SELECT sum(points),count(*) FROM ledger WHERE member='operator'").fetchone()[:]==(10,3)


def test_cancelled_download_releases_export_slot(site,monkeypatch):
    import http.client
    db,request=site
    url="/api/export?"+urlencode(dict(group="one",name="审计"))
    files=[]
    def disconnected(source,destination,chunk_size):
        files.append(source)
        raise ConnectionResetError()
    with monkeypatch.context() as fixture:
        fixture.setattr(web.shutil,"copyfileobj",disconnected)
        with pytest.raises(http.client.IncompleteRead):
            request(url)
    assert request(url)[0]==200
    assert files[0].closed
    assert db.execute("SELECT count(*) FROM audit WHERE action='导出中断'").fetchone()[0]==1


def test_export_failure_cleans_temp_and_snapshot(site,monkeypatch):
    db,_=site
    files=[]
    original=csv_export.TemporaryFile
    def track(**options):
        file=original(**options)
        files.append(file)
        return file
    def interrupted(*args):
        yield {"演练":"第一行"}
        raise OSError("临时盘写失败")
    monkeypatch.setattr(csv_export,"TemporaryFile",track)
    monkeypatch.setattr(csv_export,"rows",interrupted)
    with pytest.raises(OSError):
        csv_export.prepare(db,dict(role="系统管理员"),"one","审计",{})
    assert not db.in_transaction and files[0].closed


def test_busy_export_leaves_message_api_available(site,monkeypatch):
    _,request=site
    started,finish=threading.Event(),threading.Event()
    original=csv_export.prepare
    def delayed(*args):
        started.set()
        assert finish.wait(4)
        return original(*args)
    monkeypatch.setattr(csv_export,"prepare",delayed)
    with ThreadPoolExecutor(1) as pool:
        url="/api/export?"+urlencode(dict(group="one",name="审计"))
        pending=pool.submit(request,url)
        try:
            assert started.wait(2)
            assert request(url)[0]==429
            assert request("/api/simulate",dict(group="one",key="during-export",text="二狗积分"))[0]==202
        finally:
            finish.set()
        assert pending.result()[0]==200


def test_assets_include_wallet_without_points_and_stay_scoped(site):
    db,request=site
    db.execute("INSERT INTO fishing_wallets(grp,member,coins) VALUES('one','silent',42)")
    db.execute("INSERT INTO fishing_wallets(grp,member,coins) VALUES('two','outside',98)")
    code,raw,_=request("/api/view?"+urlencode(dict(group="one",name="积分")))
    assert code==200
    rows=json.loads(raw)
    assert {"成员":"silent","积分":0,"已建钱包鱼币":42} in rows
    assert all(row["成员"]!="outside" for row in rows)
