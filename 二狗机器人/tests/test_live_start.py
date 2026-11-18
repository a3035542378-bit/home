import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ergou import agent_wechat as aw
from ergou.db import closing_db, initialize
from tests.test_agent_wechat import Fixture


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path=self.temp/"empty.sqlite"
        initialize(self.path)
        self.db=self.enterContext(closing_db(self.path))
        self.api=Fixture()
        self.secret="mock"*16
        aw.link(self.db,self.api,"测试群",self.secret)

    def test_resume_reads_only_current_binding_permission(self):
        plan=lambda: aw.recovery_plan(self.db,self.api.slot)
        self.assertEqual(plan(),{"listen":True,"replies":False})
        with self.assertRaisesRegex(ValueError,"回复授权"):
            aw.replies(self.db,self.api,self.secret,"fixture")
        self.assertEqual(self.db.execute("SELECT count(*) FROM directed_groups").fetchone()[0],0)
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,45 FROM groups")
        self.assertTrue(plan()["replies"])
        def revoke(*args,**kwargs):
            self.db.execute("DELETE FROM directed_groups")
            return None
        with patch.object(aw.jobs,"claim",side_effect=revoke),patch.object(aw.time,"sleep"):
            aw.replies(self.db,self.api,self.secret,"fixture")
        self.assertFalse(plan()["replies"])
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding-1,45 FROM groups")
        self.assertFalse(plan()["replies"])
        self.db.execute("UPDATE groups SET paused=1")
        self.assertFalse(plan()["listen"])
        self.db.execute("UPDATE groups SET paused=0")
        self.db.execute("DELETE FROM node_grants")
        self.assertFalse(plan()["listen"])

    def test_plan_cli_needs_no_tokens(self):
        args=[sys.executable,"-m","ergou.agent_wechat","--db",str(self.path),
              "--private-dir",str(self.temp/"absent"),"--slot",self.api.slot,"recovery-plan"]
        self.assertEqual(json.loads(subprocess.check_output(args)),{"listen":True,"replies":False})

    @unittest.skipUnless(os.name=="nt","Windows launcher")
    def test_worker_identification(self):
        script=Path(aw.__file__).with_name("live_start.ps1")
        case=r"""
. $env:ERGOU_TEST_LAUNCHER
$db='C:\s p\robot.sqlite'
$dir='C:\s p\private'
$patterns=Get-LivePatterns $db $dir
$prefix='"C:\Python\python.exe" -m ergou.agent_wechat --db "C:\s p\robot.sqlite" --private-dir "C:\s p\private" '
if(($prefix+'listen') -notmatch $patterns.listener){exit 2}
if(($prefix+'replies --group-name "fixture group"') -notmatch $patterns.replies){exit 3}
if(($prefix+'resume-replies') -notmatch $patterns.replies){exit 4}
if(($prefix+'link --group-name fixture') -match $patterns.replies){exit 5}
if(($prefix.Replace('robot.sqlite','other.sqlite')+'listen') -match $patterns.listener){exit 6}
if('"C:\Python\python.exe" -m ergou --db "C:\s p\robot.sqlite" serve --port 8766' -notmatch $patterns.core){exit 7}
exit 0
"""
        subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","RemoteSigned","-Command",case],
                       check=True,env=os.environ|{"ERGOU_TEST_LAUNCHER":str(script)},timeout=20)

    @unittest.skipUnless(os.name=="nt","Windows launcher")
    def test_launcher_recovers_only_authorized_roles(self):
        self.db.execute("UPDATE agent_wechat_links SET slot='ergou-listener'")
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,45 FROM groups")
        self.db.execute("INSERT INTO users VALUES('fixture','unused','运营管理员','[]')")
        self.db.close()
        # Match the registered layout, with private fixture files and a disposable DB.
        root=self.temp/"Ergou"
        robot=root/"Robot"
        private=root/"WechatListener"
        robot.mkdir(parents=True)
        private.mkdir()
        dbfile=self.path.replace(robot/"ergou.sqlite")
        for name in ("ergou-read-token","ergou-node-secret","ergou-send-token"):
            (private/name).touch()
        native=root/"fixture-wx.exe"
        native.touch()
        script=Path(aw.__file__).with_name("live_start.ps1")
        case=r"""
. $env:ERGOU_TEST_LAUNCHER
$Database=$env:ERGOU_TEST_DB
$NativeExe=$env:ERGOU_TEST_NATIVE
$NoBrowser=$true
$script:starts=New-Object 'System.Collections.Generic.List[string]'
$script:already=$false
function Find-Worker([string]$pattern) { if($script:already){return 234} }
function Get-PortOwner([int]$port) { if($script:already){return 234} }
function Wait-Port([int]$port) {return 234}
function Start-Worker([string]$name,[string]$arguments){
    if($name -eq 'replies' -and $arguments -notmatch ' resume-replies$'){throw 'Reauthorization attempt'}
    $script:starts.Add($name)
    return 234
}
function Start-Process { $script:starts.Add('native') }
function Get-CimInstance { return @{ExecutablePath=$NativeExe} }
function Get-FileHash { return @{Hash=$expectedHash} }
Open-LiveDesk
if (($script:starts -join ',') -ne $env:ERGOU_TEST_EXPECTED){throw ('Unexpected worker set: '+($script:starts -join ','))}
$script:starts.Clear()
$script:already=$true
Open-LiveDesk
if($script:starts.Count){throw 'Workers duplicated.'}
"""
        env=os.environ|{"ERGOU_TEST_LAUNCHER":str(script),"ERGOU_TEST_DB":str(dbfile),
                        "ERGOU_TEST_NATIVE":str(native)}
        for expected,sql in (("core,native,listener,replies",None),
                             ("core,native,listener","DELETE FROM directed_groups"),
                             ("core","DELETE FROM node_grants")):
            with self.subTest(expected=expected):
                if sql:
                    with closing_db(dbfile) as db:
                        db.execute(sql)
                subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","RemoteSigned","-Command",case],
                               check=True,env=env|{"ERGOU_TEST_EXPECTED":expected},timeout=25,
                               stdout=subprocess.DEVNULL)
