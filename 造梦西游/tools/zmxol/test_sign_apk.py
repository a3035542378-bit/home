import asyncio
import datetime
import json
import hashlib
import struct
import zipfile
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from apk_patch import locate_methods


JDK = Path("/opt/homebrew/opt/openjdk/bin")
JAR = Path("/opt/homebrew/opt/jadx/libexec/lib/jadx-1.5.5-all.jar")
SOURCE_APK = Path("/Users/baize/Downloads/造梦西游OL.apk (1).1")


async def run(*arguments):
    process = await asyncio.create_subprocess_exec(*map(str, arguments), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    return process.returncode, stdout, stderr


@pytest.fixture(scope="module")
def signer(tmp_path_factory):
    if not (JDK / "javac").is_file() or not JAR.is_file() or not SOURCE_APK.is_file():
        pytest.skip("Local signer runtime or source manifest unavailable")
    directory = tmp_path_factory.mktemp("apk-signer")
    status, _, error = asyncio.run(run(JDK / "javac", "-cp", JAR, "-d", directory, Path(__file__).with_name("SignApk.java"), Path(__file__).with_name("PatchAce.java")))
    assert status == 0, error.decode()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic APK Test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256())
    private_key = directory / "key.der"
    private_key.touch(mode=0o600)
    private_key.write_bytes(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    certificate_path = directory / "certificate.der"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.DER))
    unsigned = directory / "input.apk"
    with zipfile.ZipFile(SOURCE_APK) as source, zipfile.ZipFile(unsigned, "w") as output:
        output.writestr("AndroidManifest.xml", source.read("AndroidManifest.xml"))
        output.writestr("assets/fixture.txt", b"synthetic-test-data")
    return directory, unsigned, private_key, certificate_path


def test_signer_verifies_all_enabled_schemes_and_preserves_assets(signer, tmp_path):
    directory, unsigned, key, certificate = signer
    original = unsigned.read_bytes()
    target = tmp_path / "signed.apk"
    status, stdout, stderr = asyncio.run(run(JDK / "java", "-cp", f"{directory}:{JAR}", "SignApk", unsigned, target, key, certificate))
    assert status == 0, stderr.decode()
    assert json.loads(stdout) == {"verified": True, "v1": True, "v2": True, "v3": True}
    assert unsigned.read_bytes() == original
    with zipfile.ZipFile(target) as signed:
        assert signed.testzip() is None
        assert signed.read("assets/fixture.txt") == b"synthetic-test-data"


def test_signer_refuses_to_overwrite_an_existing_file(signer, tmp_path):
    directory, unsigned, key, certificate = signer
    target = tmp_path / "existing.apk"
    target.write_bytes(b"preserve-this-file")
    status, _, _ = asyncio.run(run(JDK / "java", "-cp", f"{directory}:{JAR}", "SignApk", unsigned, target, key, certificate))
    assert status != 0
    assert target.read_bytes() == b"preserve-this-file"


def test_ace_experiment_keeps_parent_context_initialization(signer, tmp_path):
    directory, _, _, _ = signer
    original_path = tmp_path / "original.dex"
    with zipfile.ZipFile(SOURCE_APK) as source:
        original = source.read("classes.dex")
        original_path.write_bytes(original)
    target = tmp_path / "modified.dex"
    status, stdout, stderr = asyncio.run(run(JDK / "java", "-cp", f"{directory}:{JAR}", "PatchAce", original_path, target))
    assert status == 0, stderr.decode()
    modified = target.read_bytes()
    assert json.loads(stdout)["patched_methods"] == 1
    assert original_path.read_bytes() == original
    assert modified[12:32] == hashlib.sha1(modified[32:]).digest()
    assert struct.unpack_from("<I", original, 0x60)[0] == struct.unpack_from("<I", modified, 0x60)[0]
    original_offset = locate_methods(original, "Lcom/ace/gshell/AceApplication;", ("attachBaseContext",))["attachBaseContext"][1]
    offset = locate_methods(modified, "Lcom/ace/gshell/AceApplication;", ("attachBaseContext",))["attachBaseContext"][1]
    assert struct.unpack_from("<H", modified, offset)[0] == struct.unpack_from("<H", original, original_offset)[0]
    assert struct.unpack_from("<H", modified, offset + 6)[0] == 0
    assert struct.unpack_from("<I", modified, offset + 12)[0] == 4
    instructions = struct.unpack_from("<4H", modified, offset + 16)
    assert instructions[0] & 255 in (0x6F, 0x75)
    assert instructions[3] == 0xE


def test_ace_patcher_refuses_to_overwrite_an_existing_file(signer, tmp_path):
    directory, _, _, _ = signer
    target = tmp_path / "existing.dex"
    target.write_bytes(b"preserve-this-file")
    status, _, _ = asyncio.run(run(JDK / "java", "-cp", f"{directory}:{JAR}", "PatchAce", "unused-source.dex", target))
    assert status != 0
    assert target.read_bytes() == b"preserve-this-file"
