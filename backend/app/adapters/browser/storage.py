import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from app.adapters.browser.exceptions import BrowserStorageError
from app.adapters.browser.schemas import account_key


class StorageProvider(Protocol):
    async def load(self, account_id: int) -> dict | None: ...
    async def save(self, account_id: int, state: dict) -> None: ...
    async def delete(self, account_id: int) -> None: ...


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise BrowserStorageError()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def atomic_private_write(path, data):
    directory = private_directory(path.parent)
    if path.is_symlink():
        raise BrowserStorageError()
    fd, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class EncryptedFileStorage:
    def __init__(self, directory, key):
        self.directory, self.key = Path(directory), key

    def _cipher(self):
        try:
            return Fernet(self.key.get_secret_value().encode())
        except (ValueError, TypeError):
            raise BrowserStorageError() from None

    def _path(self, account_id):
        return self.directory / (account_key(account_id) + ".state.enc")

    async def load(self, account_id):
        path = self._path(account_id)
        def read():
            try:
                if not path.exists():
                    return None
                if self.directory.is_symlink() or path.is_symlink():
                    raise BrowserStorageError()
                envelope = json.loads(self._cipher().decrypt(path.read_bytes()))
                if not isinstance(envelope, dict) or type(envelope.get("account_id")) is not int or envelope.get("account_id") != account_id or not isinstance(envelope.get("state"), dict):
                    raise BrowserStorageError()
                return envelope["state"]
            except (OSError, InvalidToken, ValueError, TypeError):
                raise BrowserStorageError() from None
        return await asyncio.to_thread(read)

    async def save(self, account_id, state):
        path = self._path(account_id)
        def write():
            try:
                if not isinstance(state, dict):
                    raise BrowserStorageError()
                data = json.dumps({"account_id": account_id, "state": state}).encode()
                atomic_private_write(path, self._cipher().encrypt(data))
            except (OSError, ValueError, TypeError):
                raise BrowserStorageError() from None
        await asyncio.to_thread(write)

    async def delete(self, account_id):
        path = self._path(account_id)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError:
            raise BrowserStorageError() from None
