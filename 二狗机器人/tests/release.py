"""Build the local delivery ZIP and verify the extracted application on Windows."""
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
TOP = ("README.md", "PLAN.md", "ACCEPTANCE.md", "API.md", "COMPONENTS.md",
       "GAMES.md", "GAME_RESULTS.csv", "BENCHMARK.json", ".python-version",
       "start.ps1", "启动二狗.cmd", "打开运营后台.cmd", "打开云端运营后台.cmd", "查看公网访问密码.cmd", "确认微信通知.cmd", "确认成员通知.cmd", "确认语音唤醒.cmd")


def build(destination):
    files = [ROOT / item for item in TOP]
    for name in ("ergou", "tests", "examples", "deploy"):
        files.extend(sorted(p for p in (ROOT / name).rglob("*")
                            if p.is_file() and "__pycache__" not in p.parts))
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            content = path.read_bytes()
            if path.suffix == ".cmd":
                content = content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            if path.suffix == ".ps1":
                content = content.decode("utf-8-sig").encode("utf-8-sig")
            archive.writestr(path.relative_to(ROOT).as_posix(), content)


def verify(destination):
    with tempfile.TemporaryDirectory(prefix="ergou-release-") as temp:
        with zipfile.ZipFile(destination) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("ZIP 文件完整性检查失败")
            archive.extractall(temp)
        def cli(*args):
            return subprocess.check_output([sys.executable, *args], cwd=temp, encoding="utf-8",
                                           env=os.environ | {"PYTHONUTF8":"1"}, timeout=90)
        cli("-m", "unittest", "discover", "-q")
        cli("-m", "ergou", "init", "--demo")
        for action in ("开始 成语接龙", "G01 意气风发", "G01 发扬光大", "G01 大功告成"):
            print(cli("-m", "ergou", "say", "二狗 " + action).strip())
        if cli("-m", "ergou", "say", "二狗 积分").strip() != "本群积分 10":
            raise RuntimeError("发布包积分检查失败")
        if os.name != "nt":
            return
        # The launcher normally creates the first user interactively.
        # Create a disposable account so this rehearsal can run unattended.
        cli("-c", "from ergou import admin,db; import secrets; c=db.connect('data/ergou.sqlite'); "
            "admin.user(c,'release-check',secrets.token_urlsafe(30),'系统管理员',[]); c.close()")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        proc = subprocess.Popen(["cmd.exe", "/d", "/c", "启动二狗.cmd", "--duration", "3"], cwd=temp,
                                env=os.environ | {"ERGOU_PORT":str(port)}, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(40):
                if proc.poll() is not None:
                    raise RuntimeError("Windows 启动入口提前退出")
                try:
                    with opener.open(f"http://127.0.0.1:{port}/", timeout=1) as resp:
                        if "二狗".encode() in resp.read():
                            print("Windows 启动入口和本机首页响应通过")
                            break
                except OSError:
                    time.sleep(.2)
            else:
                raise RuntimeError("Windows 启动入口未监听指定端口")
        finally:
            if proc.wait(timeout=20) != 0:
                raise RuntimeError("限时运行未正常退出")


if __name__ == "__main__":
    dest = ROOT / "build" / "二狗机器人-Windows本地版.zip"
    dest.parent.mkdir(exist_ok=True)
    build(dest)
    verify(dest)
    with dest.open("rb") as fh:
        sha = hashlib.file_digest(fh, "sha256").hexdigest()
    dest.with_suffix(".sha256").write_text(sha+"  "+dest.name+"\n", encoding="utf-8")
    print(dest, sha)
