import importlib.util
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from ergou import linux_credentials, models


@unittest.skipUnless(importlib.util.find_spec("cryptography"), "optional on Windows")
class EnvelopeTests(unittest.TestCase):
    def test_authenticated_encryption_and_platform_mismatch(self):
        from cryptography.fernet import Fernet
        with patch.object(linux_credentials, "_service_key", return_value=Fernet.generate_key()):
            value = b"fictional-provider-credential"
            encrypted = linux_credentials.protect(value)
            self.assertNotIn(value, encrypted)
            self.assertNotEqual(encrypted, linux_credentials.protect(value))
            self.assertEqual(linux_credentials.protect(encrypted, True), value)
            with self.assertRaisesRegex(ValueError, "校验失败"):
                linux_credentials.protect(encrypted[:-9] + b"modified", True)
            with self.assertRaisesRegex(ValueError, "原有凭据"):
                linux_credentials.protect(b"foreign-key-format", True)


@unittest.skipUnless(sys.platform == "linux", "Linux service key permissions")
class LinuxStorageTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "keys"
        self.enterContext(patch.dict(os.environ, {"ERGOU_CREDENTIAL_DIR": str(self.path)}))

    def test_concurrent_first_use_publishes_one_durable_private_key(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            plaintext = [f"fake-{i}".encode() for i in range(32)]
            encrypted = list(executor.map(models.protect, plaintext))
        self.assertEqual([models.protect(token, True) for token in encrypted], plaintext)
        key_file = self.path / linux_credentials.KEY_FILE
        self.assertEqual(list(self.path.iterdir()), [key_file])
        self.assertEqual(key_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)
        key_file.unlink()
        with self.assertRaisesRegex(models.ModelError, "未找到服务主密钥"):
            models.protect(encrypted[0], True)
        self.assertFalse(key_file.exists())

    def test_unsafe_permissions_and_symlinks_fail_closed(self):
        encrypted = models.protect(b"synthetic")
        key_file = self.path / linux_credentials.KEY_FILE
        self.path.chmod(0o755)
        with self.assertRaisesRegex(models.ModelError, "目录"):
            models.protect(b"fixture")
        self.path.chmod(0o700)
        key_file.chmod(0o640)
        with self.assertRaisesRegex(models.ModelError, "权限"):
            models.protect(encrypted, True)
        key_file.chmod(0o600)
        key_file.rename(self.path / "saved")
        key_file.symlink_to(self.path / "saved")
        with self.assertRaises(models.ModelError):
            models.protect(encrypted, True)
