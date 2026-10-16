"""桌面 Lua 的本地 ADB 重发助手；保留正式收据，追加独立调试邮件。"""
import argparse
import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile

MAILS = {
    "pet": (900000252, "_offline_mock_pet"),
    "pill": (900504100, "_offline_mock_mail"),
    "bagua": (900504200, "_offline_mock_bagua"),
}
PACKAGE = "com.zmxyol.union.uc"
SAVE = f"/data/user/0/{PACKAGE}/files/offline-save.json"


def prepare_mail(profile: dict, kind: str) -> dict:
    if kind not in MAILS:
        raise ValueError("Unsupported Mock mail kind")
    if not isinstance(profile, dict) or not all(
        isinstance(profile.get(key), dict) for key in ("roledata", "bag", "pet")
    ):
        raise ValueError("Expected an actual offline profile with roledata, bag and pet")
    mail_id, key = MAILS[kind]
    state = profile.get(key)
    if state is not None and (
        not isinstance(state, dict)
        or state.get("version") != 1
        or state.get("rid") != 10001
        or state.get("id") != mail_id
        or state.get("phase") != "committed"
    ):
        raise ValueError("Only a committed matching Mock receipt can be reset; finish pending claims first")
    result = copy.deepcopy(profile)
    debug_ids = []
    for name, receipt in profile.items():
        if not name.startswith("_offline_debug_mail_"):
            continue
        suffix = name.removeprefix("_offline_debug_mail_")
        if not suffix.isascii() or not suffix.isdecimal() or str(int(suffix)) != suffix:
            raise ValueError("Invalid debug mail identity")
        mail_id_value = int(suffix)
        if not 900600000 <= mail_id_value <= 0x7fffffff or not isinstance(receipt, dict) or receipt.get("id") != mail_id_value or receipt.get("kind") not in MAILS or receipt.get("rid") != 10001 or receipt.get("version") != 1:
            raise ValueError("Invalid debug mail receipt")
        if receipt.get("phase") != "committed":
            raise ValueError("Finish the pending debug mail before issuing another")
        debug_ids.append(mail_id_value)
    if state is None:
        return result
    if len(debug_ids) >= 4096:
        raise ValueError("Debug mail history limit reached")
    new_id = max(debug_ids, default=900599999) + 1
    if new_id > 0x7fffffff:
        raise ValueError("Debug mail ID range exhausted")
    result[f"_offline_debug_mail_{new_id}"] = {
        "version": 1, "rid": 10001, "id": new_id, "kind": kind, "phase": "requested"
    }
    assert all(result[key] == value for key, value in profile.items())
    return result


async def adb(args, *command: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        args.adb, "-s", args.serial, *command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 30)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError("ADB command timed out") from None
    if process.returncode:
        raise RuntimeError(f"ADB command failed: {command[0]}")
    return output


async def run(args) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", args.serial):
        raise ValueError("Invalid Android serial")
    if args.input and not args.dry_run:
        raise ValueError("--input is available only with --dry-run")
    if args.dry_run:
        if args.input:
            source = Path(args.input).read_bytes()
            profile = json.loads(source)
            result = prepare_mail(profile, args.kind)
            print(json.dumps({"dry_run": True, "mail_id": MAILS[args.kind][0],
                              "new_debug_mail_id": next((value["id"] for key, value in result.items() if key not in profile), None),
                              "other_fields_unchanged": all(result[k] == v for k, v in profile.items()
                                                            if k in result)}))
        else:
            print(json.dumps({"dry_run": True, "mail_id": MAILS[args.kind][0],
                              "actions": ["require root adbd", "force-stop", "backup actual save",
                                          "append unique debug mail request; preserve formal receipt", "atomic replace", "start client"]}))
        return
    if (await adb(args, "shell", "id", "-u")).strip() != b"0":
        raise RuntimeError("This helper requires an already rooted emulator adbd")
    await adb(args, "shell", "am", "force-stop", PACKAGE)
    source = await adb(args, "exec-out", "cat", SAVE)
    profile = json.loads(source)
    result = prepare_mail(profile, args.kind)
    backup_dir = Path(args.backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_dir / f"mock-resend-{args.kind}-before-{stamp}.json"
    with backup.open("xb") as handle:
        handle.write(source)
    backup.chmod(0o600)
    owner = (await adb(args, "shell", "stat", "-c", "%u:%g", SAVE)).decode().strip()
    if not re.fullmatch(r"[0-9]+:[0-9]+", owner):
        raise RuntimeError("Invalid Android save owner")
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    device_temp = f"{SAVE}.debug-{stamp}.tmp"
    with tempfile.TemporaryDirectory(prefix="zmxol-mock-mail-") as directory:
        local = Path(directory) / "offline-save.json"
        local.write_bytes(payload)
        local.chmod(0o600)
        await adb(args, "push", str(local), device_temp)
        await adb(args, "shell", "chmod", "600", device_temp)
        await adb(args, "shell", "chown", owner, device_temp)
        await adb(args, "shell", "sync")
        # 原进程已停止；若存档被其他调试者改动，保留原档并拒绝覆盖。
        if await adb(args, "exec-out", "cat", SAVE) != source:
            await adb(args, "shell", "rm", "-f", device_temp)
            raise RuntimeError("Save changed after backup; replacement refused")
        await adb(args, "shell", "mv", device_temp, SAVE)
        await adb(args, "shell", "sync")
    actual = await adb(args, "exec-out", "cat", SAVE)
    if actual != payload:
        raise RuntimeError(f"Save verification failed; preserved backup: {backup}")
    await adb(args, "shell", "am", "start", "-n", f"{PACKAGE}/org.yjmobile.zmxy.zmxy")
    print(json.dumps({"mail_id": next((value["id"] for key, value in result.items() if key not in profile), MAILS[args.kind][0]), "backup": str(backup),
                      "save_sha256": hashlib.sha256(actual).hexdigest(),
                      "status": "mail requested; claim through original mailbox"}, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--kind", choices=MAILS, required=True)
    value.add_argument("--serial", default="emulator-5576")
    value.add_argument("--adb", default="/opt/homebrew/bin/adb")
    value.add_argument("--backup-dir", default=str(Path(__file__).resolve().parents[2] / "artifacts/zmxol-offline/debug-mail"))
    value.add_argument("--dry-run", action="store_true")
    value.add_argument("--input")
    return value


if __name__ == "__main__":
    try:
        asyncio.run(run(parser().parse_args()))
    except (ValueError, RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
