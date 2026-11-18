"""Enable the console on an existing HTTPS virtual host (run as root on Linux)."""
import argparse
import grp
import hmac
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


SNIPPET = Path("/etc/nginx/snippets/ergou-public.conf")
LIMITS = Path("/etc/nginx/conf.d/ergou-public-http.conf")
PASSFILE = Path("/etc/nginx/ergou-public.htpasswd")
INCLUDE = f"include {SNIPPET};"


def replace(path, data, mode, gid=0):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        try:
            os.fchown(out.fileno(), 0, gid)
            os.fchmod(out.fileno(), mode)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
            os.replace(out.name, path)
        finally:
            Path(out.name).unlink(missing_ok=True)


def password_file(username=None, *, rotate=False):
    secret = sys.stdin.buffer.readline(132).rstrip(b"\r\n")
    if not re.fullmatch(rb"[ -~]{6,128}", secret):
        raise ValueError("Expected a 6–128 character access password on stdin")
    if username is not None and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
        raise ValueError("Invalid outer access username")
    cmd = ["openssl", "passwd", "-6", "-stdin"]
    saved = None
    if PASSFILE.exists():
        saved = PASSFILE.read_bytes()
        match = re.fullmatch(rb"([A-Za-z0-9_.-]{1,64}):\$6\$([./A-Za-z0-9]+)\$[./A-Za-z0-9]+\n", saved)
        if not match:
            raise ValueError("Unexpected existing access password file")
        username = username or match[1].decode("ascii")
        if not rotate:
            cmd.extend(["-salt", match[2].decode("ascii")])
    elif rotate:
        raise ValueError("No existing outer credential to rotate")
    hashed = subprocess.run(cmd, input=secret + b"\n", capture_output=True, check=True).stdout
    entry = (username or "ergou").encode("ascii") + b":" + hashed
    if saved and not rotate and not hmac.compare_digest(saved, entry):
        raise ValueError("Existing outer credential differs; password was not replaced")
    if not saved or rotate:
        replace(PASSFILE, entry, 0o640, grp.getgrnam("www-data").gr_gid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    parser.add_argument("server_name")
    parser.add_argument("--access-user", help="HTTP Basic username (defaults to the existing username)")
    parser.add_argument("--rotate-access", action="store_true", help="Replace the existing outer credential only")
    args = parser.parse_args()
    site = args.site.resolve(strict=True)
    if os.geteuid() != 0 or not site.is_relative_to("/etc/nginx"):
        parser.error("Expected root and an existing Nginx site configuration")
    subprocess.run(["nginx", "-t"], check=True)
    before = site.read_bytes()
    pattern = rb"(?m)^([ \t]*)server_name\s+" + re.escape(args.server_name.encode()) + rb";[ \t]*$"
    if len(re.findall(pattern, before)) != 1 or not re.search(rb"(?m)^\s*listen\s+443\s+ssl\b", before):
        raise ValueError("Cannot uniquely identify the HTTPS virtual host")
    after = before
    if INCLUDE.encode() not in before:
        after = re.sub(pattern, lambda m: m[0]+b"\n"+m[1]+INCLUDE.encode(), before)
    if args.rotate_access and INCLUDE.encode() not in before:
        raise ValueError("This site does not have the public console enabled")
    password_file(args.access_user, rotate=args.rotate_access)
    if args.rotate_access:
        print("Updated public HTTPS access credential")
        return
    files = {LIMITS: Path(__file__).with_name(LIMITS.name).read_bytes(),
             SNIPPET: Path(__file__).with_name(SNIPPET.name).read_bytes(),
             site: after}
    original = {}
    try:
        for path, content in files.items():
            exists = path.exists()
            old = path.read_bytes() if exists else None
            if content == old:
                continue
            mode = path.stat().st_mode & 0o777 if exists else 0o644
            gid = path.stat().st_gid if exists else 0
            original[path] = (old, mode, gid)
            replace(path, content, mode, gid)
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
    except BaseException:
        for path, (old, mode, gid) in reversed(original.items()):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                replace(path, old, mode, gid)
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        raise
    print("Ergou HTTPS access enabled")


if __name__ == "__main__":
    main()
