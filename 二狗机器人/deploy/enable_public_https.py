"""Enable the console on an existing HTTPS virtual host (run as root on Linux)."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


SNIPPET = Path("/etc/nginx/snippets/ergou-public.conf")
LIMITS = Path("/etc/nginx/conf.d/ergou-public-http.conf")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    parser.add_argument("server_name")
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
