import asyncio
import hashlib
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

import apk_patch
from apk_patch import PatchError, locate_methods, patch_gadget_dex, read_uleb


SOURCE_APK = Path("/Users/baize/Downloads/造梦西游OL.apk (1).1")
ACE = "Lcom/ace/gshell/AceApplication;"


def initializer_instructions(data):
    string_count, string_offset = struct.unpack_from("<II", data, 0x38)
    strings = []
    for index in range(string_count):
        position = struct.unpack_from("<I", data, string_offset + 4 * index)[0]
        _, position = read_uleb(data, position)
        strings.append(data[position:data.index(0, position)].decode("ascii", errors="replace"))
    type_count, type_offset = struct.unpack_from("<II", data, 0x40)
    types = [strings[struct.unpack_from("<I", data, type_offset + 4 * index)[0]] for index in range(type_count)]
    proto_count, proto_offset = struct.unpack_from("<II", data, 0x48)
    protos = []
    for index in range(proto_count):
        _, result, parameters = struct.unpack_from("<III", data, proto_offset + 12 * index)
        count = struct.unpack_from("<I", data, parameters)[0] if parameters else 0
        arguments = tuple(types[struct.unpack_from("<H", data, parameters + 4 + 2 * item)[0]] for item in range(count))
        protos.append((arguments, types[result]))
    field_count, field_offset = struct.unpack_from("<II", data, 0x50)
    fields = []
    for index in range(field_count):
        owner, value_type, name = struct.unpack_from("<HHI", data, field_offset + 8 * index)
        fields.append((types[owner], strings[name], types[value_type]))
    method_count, method_offset = struct.unpack_from("<II", data, 0x58)
    methods = []
    for index in range(method_count):
        owner, proto, name = struct.unpack_from("<HHI", data, method_offset + 8 * index)
        methods.append((types[owner], strings[name], *protos[proto]))
    offset = locate_methods(data, ACE, ("<clinit>",))["<clinit>"][1]
    registers, _, _, tries, _, size = struct.unpack_from("<HHHHII", data, offset)
    assert registers == 1 and tries == 0
    units = struct.unpack_from(f"<{size}H", data, offset + 16)
    decoded = []
    index = 0
    while index < size:
        word = units[index]
        opcode = word & 0xFF
        if opcode in (0x1A, 0x22, 0x69):
            name, references = {0x1A: ("const-string", strings), 0x22: ("new-instance", types), 0x69: ("sput-object", fields)}[opcode]
            decoded.append((name, word >> 8, references[units[index + 1]]))
            index += 2
        elif opcode in (0x70, 0x71):
            count = word >> 12
            registers_word = units[index + 2]
            arguments = tuple((registers_word >> (4 * item)) & 0xF for item in range(4)) + ((word >> 8) & 0xF,)
            decoded.append(("invoke-direct" if opcode == 0x70 else "invoke-static", arguments[:count], methods[units[index + 1]]))
            index += 3
        else:
            assert opcode == 0x0E, f"Unexpected initializer opcode {opcode:#x}"
            decoded.append(("return-void",))
            index += 1
    return decoded


@pytest.fixture(scope="module")
def real_dexes():
    if not SOURCE_APK.is_file() or not apk_patch.JAVA.is_file() or not apk_patch.DEXLIB_JAR.is_file():
        pytest.skip("Local source APK, OpenJDK or JADX 1.5.5 unavailable")
    with zipfile.ZipFile(SOURCE_APK) as archive:
        return archive.read("classes.dex"), archive.read("classes5.dex")


@pytest.fixture(scope="module")
def patched_dex(real_dexes):
    return patch_gadget_dex(real_dexes[0])


def test_real_gadget_dex_preserves_original_tail_and_class_count(real_dexes, patched_dex):
    original = real_dexes[0]
    modified, report = patched_dex
    before = initializer_instructions(original)
    after = initializer_instructions(modified)
    assert before[0] == ("const-string", 0, "tprt")
    assert before[2] == ("const-string", 0, "tersafe2")
    assert after[:2] == [
        ("const-string", 0, "gadget"),
        ("invoke-static", (0,), ("Ljava/lang/System;", "loadLibrary", ("Ljava/lang/String;",), "V")),
    ]
    assert after[2:] == before
    assert struct.unpack_from("<I", modified, 0x60)[0] == struct.unpack_from("<I", original, 0x60)[0] == 1539
    assert struct.unpack_from("<I", modified, 0x58)[0] == struct.unpack_from("<I", original, 0x58)[0]
    assert report == {"class_count": 1539, "original_instructions": 8, "patched_instructions": 10, "original_tail_preserved": True}
    assert modified[12:32] == hashlib.sha1(modified[32:]).digest()
    assert struct.unpack_from("<I", modified, 8)[0] == zlib.adler32(modified[12:]) & 0xFFFFFFFF


def test_real_gadget_dex_rejects_repeated_injection(patched_dex):
    with pytest.raises(PatchError, match="Gadget DEX patch failed"):
        patch_gadget_dex(patched_dex[0])


def test_real_gadget_dex_rejects_missing_ace_class(real_dexes):
    with pytest.raises(PatchError, match="Gadget DEX patch failed"):
        patch_gadget_dex(real_dexes[1])


def test_java_gadget_helper_refuses_existing_output(real_dexes, tmp_path):
    source = tmp_path / "classes.dex"
    target = tmp_path / "existing.dex"
    source.write_bytes(real_dexes[0])
    target.write_bytes(b"preserve-existing-output")
    async def run():
        process = await asyncio.create_subprocess_exec(
            str(apk_patch.JAVA), "--class-path", str(apk_patch.DEXLIB_JAR), "--source", "17",
            str(Path(apk_patch.__file__).with_name("PatchGadget.java")), str(source), str(target),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, error = await process.communicate()
        return process.returncode, error
    code, error = asyncio.run(run())
    assert code != 0 and b"Output must be a new file" in error
    assert source.read_bytes() == real_dexes[0]
    assert target.read_bytes() == b"preserve-existing-output"


def test_gadget_patch_reports_missing_java_dependency(tmp_path, monkeypatch):
    monkeypatch.setattr(apk_patch, "JAVA", tmp_path / "missing-java")
    with pytest.raises(PatchError, match="requires local OpenJDK"):
        patch_gadget_dex(b"unused")
