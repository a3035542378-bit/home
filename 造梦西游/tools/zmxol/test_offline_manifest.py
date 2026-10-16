import hashlib
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

from offline_manifest import ANDROID_NAMESPACE, INTERNET, ManifestError, remove_internet_permission


SOURCE_APK = Path("/Users/baize/Downloads/造梦西游OL.apk (1).1")
JAVA = Path("/opt/homebrew/opt/openjdk/bin/java")
JAR = Path("/opt/homebrew/opt/jadx/libexec/lib/jadx-1.5.5-all.jar")
NONE = 0xFFFFFFFF
STRINGS = [
    "name", "label", "maxSdkVersion", "android", ANDROID_NAMESPACE,
    "manifest", "package", "com.example.offline", "uses-permission",
    "uses-permission-sdk-23", "uses-permission-sdk-m", "application", "meta-data",
    INTERNET, "android.permission.ACCESS_NETWORK_STATE", "android.permission.INTERNET_EXTRA",
    "保留的文本 🐒",
]
DEFAULT_PERMISSIONS = [
    ("uses-permission", INTERNET),
    ("uses-permission", "android.permission.ACCESS_NETWORK_STATE"),
]


def fixture_manifest(permissions=None, *, utf8=False, raw_names=True, extra_strings=()):
    strings = STRINGS + list(extra_strings)
    index = strings.index

    def length(value, width):
        high_bit = 1 << (width * 8 - 1)
        if value < high_bit:
            return value.to_bytes(width, "little")
        return (high_bit | (value >> (width * 8))).to_bytes(width, "little") + (value & (high_bit * 2 - 1)).to_bytes(width, "little")

    encoded, offsets = bytearray(), []
    for value in strings:
        offsets.append(len(encoded))
        units = len(value.encode("utf-16-le")) // 2
        if utf8:
            payload = value.encode("utf-8")
            encoded.extend(length(units, 1) + length(len(payload), 1) + payload + b"\0")
        else:
            encoded.extend(length(units, 2) + value.encode("utf-16-le") + b"\0\0")
    encoded.extend(bytes(-len(encoded) % 4))
    start = 28 + 4 * len(strings)
    pool = struct.pack("<HH6I", 1, 28, start + len(encoded), len(strings), 0, 0x100 if utf8 else 0, start, 0)
    pool += struct.pack(f"<{len(offsets)}I", *offsets) + encoded
    resource_map = struct.pack("<HH4I", 0x180, 8, 20, 0x01010003, 0x01010001, 0x01010271)

    def node(kind, extension):
        return struct.pack("<HHIII", kind, 16, 16 + len(extension), 7, NONE) + extension

    def attribute(name, value, namespace=ANDROID_NAMESPACE, raw=True):
        return struct.pack("<IIIHBBI", index(namespace) if namespace else NONE, index(name), index(value) if raw else NONE, 8, 0, 3, index(value))

    def element(name, attributes=()):
        return node(0x102, struct.pack("<II6H", NONE, index(name), 20, 20, len(attributes), 0, 0, 0) + b"".join(attributes))

    def end_element(name):
        return node(0x103, struct.pack("<II", NONE, index(name)))

    contents = [pool, resource_map, node(0x100, struct.pack("<II", index("android"), index(ANDROID_NAMESPACE)))]
    contents.append(element("manifest", [attribute("package", "com.example.offline", None)]))
    for tag, permission in DEFAULT_PERMISSIONS if permissions is None else permissions:
        contents.extend([element(tag, [attribute("name", permission, raw=raw_names)]), end_element(tag)])
    contents.append(element("application", [attribute("label", INTERNET)]))
    contents.append(element("meta-data", [attribute("name", INTERNET)]))
    contents.append(end_element("meta-data"))
    contents.append(node(0x104, struct.pack("<IHBBI", index("保留的文本 🐒"), 8, 0, 3, index("保留的文本 🐒"))))
    contents.extend([end_element("application"), end_element("manifest"), node(0x101, struct.pack("<II", index("android"), index(ANDROID_NAMESPACE)))])
    payload = b"".join(contents)
    return struct.pack("<HHI", 3, 8, 8 + len(payload)) + payload


def chunks(data):
    offset = 8
    while offset < len(data):
        kind, header, size = struct.unpack_from("<HHI", data, offset)
        yield offset, kind, header, size
        offset += size


def first_permission(data):
    return next(offset for offset, kind, _, _ in chunks(data) if kind == 0x102 and struct.unpack_from("<I", data, offset + 20)[0] == STRINGS.index("uses-permission"))


@pytest.mark.parametrize("utf8", [False, True])
@pytest.mark.parametrize("raw_names", [False, True])
def test_only_internet_elements_are_removed_and_other_bytes_are_identical(utf8, raw_names):
    permissions = [
        ("uses-permission", INTERNET),
        ("uses-permission", "android.permission.ACCESS_NETWORK_STATE"),
        ("uses-permission", INTERNET),
        ("uses-permission-sdk-23", INTERNET),
        ("uses-permission-sdk-m", INTERNET),
        ("uses-permission-sdk-23", "android.permission.INTERNET_EXTRA"),
    ]
    original = fixture_manifest(permissions, utf8=utf8, raw_names=raw_names)
    output, removed = remove_internet_permission(original)
    expected_permissions = [item for item in permissions if item[1] != INTERNET]
    assert output == fixture_manifest(expected_permissions, utf8=utf8, raw_names=raw_names)
    assert removed == [{"element": tag, "name": INTERNET} for tag, permission in permissions if permission == INTERNET]
    assert len(output) == len(original) - 4 * 80
    assert struct.unpack_from("<I", output, 4)[0] == len(output)
    assert remove_internet_permission(output) == (output, [])


@pytest.mark.parametrize("utf8", [False, True])
def test_manifest_without_internet_is_byte_identical(utf8):
    source = fixture_manifest([DEFAULT_PERMISSIONS[1]], utf8=utf8)
    assert remove_internet_permission(source) == (source, [])


@pytest.mark.parametrize("utf8,extra", [(True, "长" * 128), (False, "x" * 32768)])
def test_extended_string_lengths_are_preserved(utf8, extra):
    original = fixture_manifest(utf8=utf8, extra_strings=[extra])
    output, _ = remove_internet_permission(original)
    assert output == fixture_manifest([DEFAULT_PERMISSIONS[1]], utf8=utf8, extra_strings=[extra])


def test_resource_id_identifies_android_name_even_with_different_text():
    data = bytearray(fixture_manifest())
    resource_offset = next(offset for offset, kind, _, _ in chunks(data) if kind == 0x180)
    struct.pack_into("<I", data, resource_offset + 12, 0x01010003)
    permission_offset = first_permission(data)
    struct.pack_into("<II", data, permission_offset + 36, NONE, STRINGS.index("label"))
    output, removed = remove_internet_permission(bytes(data))
    assert removed == [{"element": "uses-permission", "name": INTERNET}]
    assert output[8:] == bytes(data[8:permission_offset] + data[permission_offset + 80:])


def test_permission_tag_namespace_does_not_hide_internet():
    data = bytearray(fixture_manifest())
    permission = first_permission(data)
    struct.pack_into("<I", data, permission + 16, STRINGS.index(ANDROID_NAMESPACE))
    struct.pack_into("<I", data, permission + 56 + 16, STRINGS.index(ANDROID_NAMESPACE))
    output, removed = remove_internet_permission(bytes(data))
    assert output == fixture_manifest([DEFAULT_PERMISSIONS[1]])
    assert len(removed) == 1


@pytest.mark.parametrize("case", [
    "empty", "text_xml", "total_length", "top_header", "zero_chunk", "short_header",
    "chunk_overrun", "unaligned_chunk", "truncated_header", "string_count", "string_start",
    "string_offset", "string_terminator", "style_bounds", "node_header", "node_length",
    "attribute_start", "attribute_size", "attribute_count", "attribute_index", "string_reference",
    "typed_value_size", "typed_value_reserved", "permission_reference", "permission_conflict",
    "unmatched_element", "unmatched_namespace", "unclosed_root", "unknown_node",
])
def test_malformed_axml_is_rejected(case):
    data = bytearray(fixture_manifest())
    permission = first_permission(data)
    if case == "empty":
        data = bytearray()
    elif case == "text_xml":
        data = bytearray(b"<manifest />")
    elif case == "total_length":
        struct.pack_into("<I", data, 4, len(data) - 4)
    elif case == "top_header":
        struct.pack_into("<H", data, 2, 12)
    elif case in ("zero_chunk", "chunk_overrun", "unaligned_chunk"):
        struct.pack_into("<I", data, 12, {"zero_chunk": 0, "chunk_overrun": len(data), "unaligned_chunk": 29}[case])
    elif case == "short_header":
        struct.pack_into("<H", data, 10, 4)
    elif case == "truncated_header":
        data.extend(b"\0\0\0\0")
        struct.pack_into("<I", data, 4, len(data))
    elif case == "string_count":
        struct.pack_into("<I", data, 16, NONE)
    elif case == "string_start":
        struct.pack_into("<I", data, 28, len(data))
    elif case == "string_offset":
        struct.pack_into("<I", data, 36, len(data))
    elif case == "string_terminator":
        start = 8 + struct.unpack_from("<I", data, 28)[0]
        struct.pack_into("<H", data, start + 2 + len(STRINGS[0]) * 2, 1)
    elif case == "style_bounds":
        struct.pack_into("<I", data, 20, 1)
    elif case == "node_header":
        struct.pack_into("<H", data, permission + 2, 8)
    elif case == "node_length":
        struct.pack_into("<I", data, permission + 4, 20)
    elif case in ("attribute_start", "attribute_size", "attribute_count", "attribute_index"):
        relative, value = {"attribute_start": (24, 4), "attribute_size": (26, 16), "attribute_count": (28, 65535), "attribute_index": (30, 2)}[case]
        struct.pack_into("<H", data, permission + relative, value)
    elif case == "string_reference":
        struct.pack_into("<I", data, permission + 40, NONE)
    elif case == "typed_value_size":
        struct.pack_into("<H", data, permission + 48, 0)
    elif case == "typed_value_reserved":
        data[permission + 50] = 1
    elif case == "permission_reference":
        data[permission + 51] = 1
    elif case == "permission_conflict":
        struct.pack_into("<I", data, permission + 44, STRINGS.index("android.permission.ACCESS_NETWORK_STATE"))
    elif case == "unmatched_element":
        struct.pack_into("<I", data, permission + 56 + 20, STRINGS.index("application"))
    elif case == "unmatched_namespace":
        struct.pack_into("<I", data, len(data) - 8, STRINGS.index("label"))
    elif case == "unclosed_root":
        del data[-48:-24]
        struct.pack_into("<I", data, 4, len(data))
    elif case == "unknown_node":
        struct.pack_into("<H", data, permission, 0x105)
    with pytest.raises(ManifestError):
        remove_internet_permission(bytes(data))


@pytest.fixture(scope="module")
def real_manifest():
    if not SOURCE_APK.is_file():
        pytest.skip("Local source APK unavailable")
    with zipfile.ZipFile(SOURCE_APK) as archive:
        return archive.read("AndroidManifest.xml")


def test_real_apk_removes_both_internet_nodes_and_preserves_all_other_bytes(real_manifest):
    assert hashlib.sha256(real_manifest).hexdigest() == "dfd0f25a04dc114dbf7157ee2b557895622a70516212e33cc54a0101d30bd516"
    assert len(real_manifest) == 25744
    output, removed = remove_internet_permission(real_manifest)
    assert removed == [{"element": "uses-permission", "name": INTERNET}] * 2
    expected = bytearray(real_manifest[:0x28EC] + real_manifest[0x293C:0x324C] + real_manifest[0x329C:])
    struct.pack_into("<I", expected, 4, len(expected))
    assert output == bytes(expected)
    assert remove_internet_permission(output) == (output, [])


def test_android_parser_accepts_patched_real_manifest(real_manifest, tmp_path):
    if not JAVA.is_file() or not JAR.is_file():
        pytest.skip("Local Android apksig parser unavailable")
    java_source = tmp_path / "ReadManifest.java"
    java_source.write_text('''
import com.android.apksig.internal.apk.AndroidBinXmlParser;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
class ReadManifest {
    public static void main(String[] args) throws Exception {
        AndroidBinXmlParser p = new AndroidBinXmlParser(ByteBuffer.wrap(Files.readAllBytes(Path.of(args[0]))));
        while (p.next() != AndroidBinXmlParser.EVENT_END_DOCUMENT) {
            if (p.getEventType() != AndroidBinXmlParser.EVENT_START_ELEMENT) continue;
            System.out.println("element:" + p.getDepth() + ":" + p.getNamespace() + ":" + p.getName());
            for (int i = 0; i < p.getAttributeCount(); i++) {
                String value = p.getAttributeValueType(i) == AndroidBinXmlParser.VALUE_TYPE_STRING
                    ? p.getAttributeStringValue(i) : "<non-string>";
                System.out.println("attribute:" + p.getAttributeNameResourceId(i) + ":" + p.getAttributeNamespace(i) + ":" + p.getAttributeName(i) + ":" + value);
            }
        }
    }
}
''', encoding="utf-8")

    def parse(data, name):
        manifest = tmp_path / name
        manifest.write_bytes(data)
        process = subprocess.run([str(JAVA), "--class-path", str(JAR), "--source", "17", str(java_source), str(manifest)], capture_output=True, check=True, timeout=30)
        return process.stdout.decode().splitlines()

    before = parse(real_manifest, "original.axml")
    after = parse(remove_internet_permission(real_manifest)[0], "offline.axml")
    expected = []
    for index, line in enumerate(before):
        if line.endswith(":" + INTERNET) and line.startswith("attribute:"):
            assert before[index - 1] == "element:2::uses-permission"
            expected.pop()
        else:
            expected.append(line)
    assert after == expected
