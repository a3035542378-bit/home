"""Authenticated local credential storage for the Linux service account."""
import os
import secrets
import stat
from pathlib import Path


KEY_FILE = "credential.key"
FORMAT = b"ergou-fernet-v1\x00"


def _publish_key(directory, key):
    # Readers must always see a complete key, even if two workers provision it
    # concurrently or one exits between writing and publishing the file.
    temporary = ".credential-" + secrets.token_hex(16)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(key)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temporary, KEY_FILE, src_dir_fd=directory, dst_dir_fd=directory)
        except FileExistsError:
            pass
        os.fsync(directory)
    finally:
        os.unlink(temporary, dir_fd=directory)


def _read_key(directory):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(KEY_FILE, flags, dir_fd=directory), "rb") as key_file:
        info = os.fstat(key_file.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size != 44):
            raise ValueError("服务主密钥所有者、权限或文件长度异常")
        return key_file.read(45)


def _service_key(create, fernet):
    location = os.environ.get("ERGOU_CREDENTIAL_DIR", "")
    if not os.path.isabs(location):
        raise ValueError("请为服务设置绝对路径 ERGOU_CREDENTIAL_DIR")
    path = Path(location)
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("服务密钥目录须归运行账号所有，权限设为 0700")
        try:
            return _read_key(directory)
        except FileNotFoundError:
            if not create:
                raise ValueError("未找到服务主密钥，请恢复原密钥或重新配置供应商凭据") from None
            _publish_key(directory, fernet.generate_key())
            return _read_key(directory)
    finally:
        os.close(directory)


def protect(value, decrypt=False):
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        raise ValueError("请为运行二狗的 Python 安装 cryptography") from None
    if decrypt and not value.startswith(FORMAT):
        raise ValueError("无法在此服务器解密原有凭据，请重新配置供应商凭据")
    try:
        cipher = Fernet(_service_key(not decrypt, Fernet))
        if decrypt:
            return cipher.decrypt(value[len(FORMAT):])
        return FORMAT + cipher.encrypt(value)
    except InvalidToken:
        raise ValueError("凭据校验失败，请恢复原主密钥或重新配置供应商凭据") from None
    except OSError:
        raise ValueError("服务密钥目录不可用，请核对路径、文件权限与可用空间") from None
