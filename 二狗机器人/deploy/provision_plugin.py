"""Provision separate slot-scoped keys through the native plugin's owner CLI."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


PROFILE = Path("/var/lib/ergou/wechat")
SLOT = "ergou-listener"


def wx(*args):
    cmd = ["/opt/ergou/bin/wx", "--data-dir", str(PROFILE), "--server",
           "http://127.0.0.1:6174", "--token-file", str(PROFILE / "api-token"), "--json", *args]
    result = subprocess.run(cmd, capture_output=True, timeout=15)
    if result.returncode:
        raise RuntimeError("插件命令执行失败：" + " ".join(args[:2]))
    return json.loads(result.stdout)


def main():
    for _ in range(20):
        try:
            accounts = wx("accounts", "list")
            break
        except RuntimeError:
            time.sleep(0.5)
    else:
        raise RuntimeError("微信插件未就绪")
    rows = accounts if isinstance(accounts, list) else accounts.get("items", accounts.get("accounts"))
    if not isinstance(rows, list):
        raise ValueError("未知账号列表格式")
    if not any(row.get("id") == SLOT for row in rows):
        wx("accounts", "create", SLOT)
    for target, scopes in [(PROFILE.parent / "login/ergou-login-token", ("read", "login")),
                           (PROFILE / "ergou-read-token", ("read",)),
                           (PROFILE / "ergou-send-token", ("send",))]:
        if target.is_file() and target.stat().st_size:
            continue
        flags = [arg for scope in scopes for arg in ("--scopes", scope)]
        result = wx("tokens", "create", target.name, "--accounts", SLOT, *flags)
        token = result.get("token")
        if not isinstance(token, str) or not re.fullmatch(r"[!-~]{32,1024}", token):
            raise ValueError("插件签发凭据失败")
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
            try:
                temp.write(token.encode("ascii"))
                temp.flush()
                os.fsync(temp.fileno())
                os.link(temp.name, target)
            finally:
                os.unlink(temp.name)
    print("微信账号槽及受限令牌就绪")


if __name__ == "__main__":
    main()
