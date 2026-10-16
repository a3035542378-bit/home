"""替换已定位的 SDK 方法，可选嵌入已核对 ARM64 库与 Gadget 离线脚本。"""

import argparse
import asyncio
import hashlib
import json
import logging
import struct
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path

from legacy_resources import load_legacy_game_resources
from offline_manifest import remove_internet_permission


LOGGER = logging.getLogger(__name__)
HELPER = "Lorg/yjmobile/lib/YJMobileJNIHelper;"
EXPECTED_APK_SHA256 = "1d87033ad10f66f21968ac8cdff0a405063391ab8145152b27bec6861804567f"
EXPECTED_NATIVE_SHA256 = {
    "lib/arm64-v8a/libgame.so": "91a8b745b51a2e4b7743a94d5fe7f1e6e1ec50c1ed6149c64d2b5b2cf5b9ddb0",
    "lib/arm64-v8a/libtprt.so": "18457ba0f0af412857a4047c029025bb17dbf2e93f6e0c1516bf9f75bed0b97f",
}
EXPECTED_GADGET_SHA256 = "61be4bbeae285bb19164dc9eebee58669f6ad2ab4b4d64422ea0a779731b0898"
GADGET_VERSION = "16.7.19"
GADGET_ENTRY = "lib/arm64-v8a/libgadget.so"
GADGET_CONFIG_ENTRY = "lib/arm64-v8a/libgadget.config.so"
OFFLINE_SCRIPT_ENTRY = "lib/arm64-v8a/liboffline.script.so"
GADGET_CONFIG = {
    "interaction": {"type": "script", "path": "liboffline.script.so", "on_change": "ignore"},
    "runtime": "qjs",
}
JAVA = Path("/opt/homebrew/opt/openjdk/bin/java")
DEXLIB_JAR = Path("/opt/homebrew/opt/jadx/libexec/lib/jadx-1.5.5-all.jar")


class PatchError(ValueError):
    """输入或修改不符合当前测试包的约束。"""


def read_uleb(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 35, 7):
        if offset >= len(data):
            raise PatchError("Truncated ULEB128")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
    raise PatchError("Invalid ULEB128")


def locate_methods(data: bytes, descriptor: str = HELPER, method_names: tuple[str, ...] = ("initHummingbirdSDK", "checkHummingbirdSDKUpdate", "setHummingbirdSDKInitEnd")) -> dict[str, tuple[int, int]]:
    if len(data) < 0x70 or data[:4] != b"dex\n":
        raise PatchError("Not a DEX file")
    if struct.unpack_from("<I", data, 0x20)[0] != len(data):
        raise PatchError("DEX file length mismatch")
    strings_count, strings_offset = struct.unpack_from("<II", data, 0x38)
    strings = []
    for index in range(strings_count):
        position = struct.unpack_from("<I", data, strings_offset + index * 4)[0]
        _, position = read_uleb(data, position)
        end = data.index(0, position)
        # 这里只匹配 ASCII 类和方法名，不将 MUTF-8 的其他字符串写入日志。
        strings.append(data[position:end].decode("ascii", errors="replace"))
    type_count, type_offset = struct.unpack_from("<II", data, 0x40)
    types = [strings[struct.unpack_from("<I", data, type_offset + i * 4)[0]] for i in range(type_count)]
    method_count, method_offset = struct.unpack_from("<II", data, 0x58)
    methods = [struct.unpack_from("<HHI", data, method_offset + i * 8) for i in range(method_count)]
    class_count, class_offset = struct.unpack_from("<II", data, 0x60)
    result = {}
    for index in range(class_count):
        definition = class_offset + index * 32
        class_index = struct.unpack_from("<I", data, definition)[0]
        if types[class_index] != descriptor:
            continue
        position = struct.unpack_from("<I", data, definition + 24)[0]
        sizes = []
        for _ in range(4):
            size, position = read_uleb(data, position)
            sizes.append(size)
        for _ in range(sizes[0] + sizes[1]):
            _, position = read_uleb(data, position)
            _, position = read_uleb(data, position)
        for count in sizes[2:]:
            method_index = 0
            for _ in range(count):
                difference, position = read_uleb(data, position)
                method_index += difference
                _, position = read_uleb(data, position)
                code_offset, position = read_uleb(data, position)
                name = strings[methods[method_index][2]]
                if name not in method_names:
                    continue
                if name in result:
                    raise PatchError("Ambiguous helper method")
                result[name] = method_index, code_offset
    return result


def patch_dex(data: bytes) -> tuple[bytes, list[dict]]:
    methods = locate_methods(data)
    if not methods:
        return data, []
    names = ("initHummingbirdSDK", "checkHummingbirdSDKUpdate", "setHummingbirdSDKInitEnd")
    if not all(name in methods for name in names):
        raise PatchError("Missing expected SDK initialization methods")
    setter = methods[names[2]][0]
    if setter > 0xFFFF:
        raise PatchError("Method index exceeds invoke-static format")
    replacements = {
        names[0]: [0x1012, 0x1071, setter, 0, 0x000E],
        names[1]: [0x000E],
    }
    output = bytearray(data)
    report = []
    for name, instructions in replacements.items():
        _, offset = methods[name]
        if not offset or offset + 16 > len(data):
            raise PatchError("Missing method code")
        registers, _, outgoing, tries, _, size = struct.unpack_from("<HHHHII", data, offset)
        if tries or size < len(instructions) or offset + 16 + size * 2 > len(data):
            raise PatchError("Unsupported method code layout")
        if name == names[0] and (registers < 1 or outgoing < 1):
            raise PatchError("Insufficient method registers")
        replacement = struct.pack("<" + "H" * size, *(instructions + [0] * (size - len(instructions))))
        output[offset + 16:offset + 16 + size * 2] = replacement
        report.append({"method": name, "code_offset": offset, "code_units": size})
    output[12:32] = hashlib.sha1(output[32:]).digest()
    struct.pack_into("<I", output, 8, zlib.adler32(output[12:]) & 0xFFFFFFFF)
    return bytes(output), report


def patch_gadget_dex(data: bytes) -> tuple[bytes, dict]:
    if not JAVA.is_file() or not DEXLIB_JAR.is_file():
        raise PatchError("Gadget DEX patch requires local OpenJDK and JADX 1.5.5")
    try:
        with tempfile.TemporaryDirectory(prefix="zmxol-gadget-dex-") as directory:
            source = Path(directory) / "classes.dex"
            target = Path(directory) / "patched.dex"
            source.write_bytes(data)
            process = subprocess.run(
                [str(JAVA), "--class-path", str(DEXLIB_JAR), "--source", "17",
                 str(Path(__file__).with_name("PatchGadget.java")), str(source), str(target)],
                capture_output=True, check=False, timeout=120,
            )
            if process.returncode:
                raise PatchError("Gadget DEX patch rejected the input")
            report = json.loads(process.stdout)
            if report.get("original_tail_preserved") is not True:
                raise PatchError("Gadget DEX verification failed")
            return target.read_bytes(), report
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        LOGGER.error("Gadget DEX patch failed (%s)", type(error).__name__)
        raise PatchError("Gadget DEX patch failed") from error


def read_input(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        LOGGER.error("%s read failed (%s)", label, type(error).__name__)
        raise PatchError(f"Unable to read {label}") from error


def validate_entries(names: list[str]) -> None:
    seen = set()
    files = {name for name in names if not name.endswith("/")}
    for name in names:
        path = name.removesuffix("/")
        parts = path.split("/")
        if not path or "\\" in name or "\0" in name or ":" in parts[0] or any(part in ("", ".", "..") for part in parts):
            raise PatchError("Unsafe ZIP entry path")
        if path in seen:
            raise PatchError("Duplicate ZIP entry path")
        if any("/".join(parts[:index]) in files for index in range(1, len(parts))):
            raise PatchError("ZIP file blocks an entry directory")
        seen.add(path)


def build_unsigned(
    source: Path, target: Path, ace_dex: Path | None = None,
    game_library: Path | None = None, tprt_library: Path | None = None,
    gadget_library: Path | None = None, offline_script: Path | None = None,
    legacy_apk: Path | None = None,
) -> dict:
    if source.resolve() == target.resolve() or target.exists() or target.is_symlink():
        raise PatchError("Output must be a new file")
    if (game_library is None) != (tprt_library is None):
        raise PatchError("Both ARM64 native libraries are required")
    if (gadget_library is None) != (offline_script is None):
        raise PatchError("Gadget library and offline script must be provided together")
    if gadget_library is not None and (game_library is None or ace_dex is not None):
        raise PatchError("Gadget mode requires both native libraries and cannot use --ace-dex")
    if legacy_apk is not None and gadget_library is None:
        raise PatchError("Legacy resources require Gadget mode")
    native_libraries = {}
    if game_library is not None:
        for name, path in (("lib/arm64-v8a/libgame.so", game_library), ("lib/arm64-v8a/libtprt.so", tprt_library)):
            data = read_input(path, "native library")
            if hashlib.sha256(data).hexdigest() != EXPECTED_NATIVE_SHA256[name]:
                raise PatchError(f"Unsupported native library fingerprint: {name}")
            native_libraries[name] = data
    additions = {}
    if gadget_library is not None:
        gadget = read_input(gadget_library, "Gadget library")
        if hashlib.sha256(gadget).hexdigest() != EXPECTED_GADGET_SHA256:
            raise PatchError("Unsupported Gadget library fingerprint")
        script = read_input(offline_script, "offline script")
        try:
            decoded_script = script.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PatchError("Offline script must be UTF-8 JavaScript") from error
        if not decoded_script.strip() or "\0" in decoded_script:
            raise PatchError("Offline script must be nonempty JavaScript without NUL bytes")
        additions = {
            GADGET_ENTRY: gadget,
            GADGET_CONFIG_ENTRY: (json.dumps(GADGET_CONFIG, indent=2) + "\n").encode("utf-8"),
            OFFLINE_SCRIPT_ENTRY: script,
        }
    digest = hashlib.sha256()
    with source.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != EXPECTED_APK_SHA256:
        raise PatchError("Unsupported source APK fingerprint")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    if temporary.exists() or temporary.is_symlink():
        raise PatchError("Previous partial output exists")
    changed = []
    changed_native = []
    excluded_abis = set()
    excluded_native_entry_count = 0
    manifest_report = None
    legacy_report = None
    owns_temporary = False
    try:
        with zipfile.ZipFile(source) as original:
            names = original.namelist()
            if any(names.count(name) != 1 for name in native_libraries):
                raise PatchError("Unexpected native library entries")
            validate_entries([info.orig_filename for info in original.infolist()])
            if additions and ("classes.dex" not in names or any(name in names for name in additions)):
                raise PatchError("Unexpected Gadget or primary DEX entries")
            if additions and names.count("AndroidManifest.xml") != 1:
                raise PatchError("Gadget mode requires exactly one AndroidManifest.xml")
            legacy_entries = {}
            if legacy_apk is not None:
                legacy_entries, legacy_report = load_legacy_game_resources(legacy_apk)
            validate_entries(names + list(additions) + list(legacy_entries))
            additions.update(legacy_entries)
            with temporary.open("xb") as destination:
                owns_temporary = True
                with zipfile.ZipFile(destination, "w", allowZip64=False) as generated:
                    for info in original.infolist():
                        name = info.filename
                        parts = name.split("/", 2)
                        if additions and len(parts) == 3 and parts[0] == "lib" and parts[1] != "arm64-v8a":
                            excluded_abis.add(parts[1])
                            excluded_native_entry_count += 1
                            continue
                        upper = name.upper()
                        if upper.startswith("META-INF/") and (upper.endswith((".SF", ".RSA", ".DSA", ".EC")) or upper == "META-INF/MANIFEST.MF"):
                            continue
                        data = original.read(info)
                        if name == "AndroidManifest.xml" and additions:
                            data, removed_permissions = remove_internet_permission(data)
                            manifest_report = {
                                "entry": name,
                                "removed_permissions": removed_permissions,
                                "removed_permission_count": len(removed_permissions),
                            }
                        if name == "classes.dex" and ace_dex is not None:
                            data = ace_dex.read_bytes()
                            matches = locate_methods(data, "Lcom/ace/gshell/AceApplication;", ("attachBaseContext",))
                            if len(matches) != 1:
                                raise PatchError("ACE replacement DEX missing expected method")
                            changed.append({"entry": name, "patches": [{"method": "AceApplication.attachBaseContext", "purpose": "initialization-experiment"}]})
                        if name == "classes.dex" and additions:
                            data, verification = patch_gadget_dex(data)
                            changed.append({"entry": name, "patches": [{"method": "AceApplication.<clinit>", "purpose": "embedded-gadget-script", **verification}]})
                        if name.startswith("classes") and name.endswith(".dex"):
                            data, patches = patch_dex(data)
                            if patches:
                                changed.append({"entry": name, "patches": patches})
                        if name in native_libraries:
                            changed_native.append({
                                "entry": name,
                                "source_sha256": hashlib.sha256(data).hexdigest(),
                                "output_sha256": EXPECTED_NATIVE_SHA256[name],
                            })
                            data = native_libraries[name]
                        generated.writestr(info, data, compresslevel=1)
                    for name, data in additions.items():
                        generated.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)
        if len(changed) != (2 if ace_dex is not None or additions else 1):
            raise PatchError("Unexpected modified DEX count")
        with zipfile.ZipFile(temporary) as generated:
            if generated.testzip() is not None:
                raise PatchError("Generated ZIP CRC verification failed")
        # 同目录硬链接发布不会覆盖在构建期间新建的目标文件。
        target.hardlink_to(temporary)
        temporary.unlink()
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile, struct.error) as error:
        LOGGER.error("Startup APK build failed: %s", type(error).__name__)
        if owns_temporary:
            temporary.unlink(missing_ok=True)
        raise PatchError("Startup APK build failed") from error
    return {
        "status": "EXPERIMENTAL_NOT_PLAYABLE",
        "source_sha256": digest.hexdigest(),
        "modified_dex": changed,
        "modified_native": changed_native,
        "added_entries": [{"entry": name, "sha256": hashlib.sha256(data).hexdigest()} for name, data in additions.items()],
        "gadget_version": GADGET_VERSION if additions else None,
        "excluded_native_abis": sorted(excluded_abis),
        "excluded_native_entry_count": excluded_native_entry_count,
        "zip_crc": "PASS",
        "purpose": "startup-test-only",
        "native_patch_abi": "arm64-v8a" if native_libraries else None,
        **({"manifest": manifest_report} if additions else {}),
        **({"legacy_resources": legacy_report} if legacy_apk is not None else {}),
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--ace-dex", type=Path)
    parser.add_argument("--game-library", type=Path, help="Verified experimental ARM64 libgame.so; requires --tprt-library")
    parser.add_argument("--tprt-library", type=Path, help="Verified experimental ARM64 libtprt.so; requires --game-library")
    parser.add_argument("--gadget-library", type=Path, help="Verified official Frida 16.7.19 ARM64 Gadget; requires --offline-script and both native libraries")
    parser.add_argument("--offline-script", type=Path, help="Local UTF-8 JavaScript to embed in Gadget script mode; requires --gadget-library")
    parser.add_argument("--legacy-apk", type=Path, help="Verified 11.6.0 APK for original roles 1/5 and enemies 300/303; Gadget mode only")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    report_path = arguments.target.with_suffix(".report.json")
    if report_path.exists() or report_path.is_symlink() or report_path.resolve() == arguments.target.resolve():
        raise PatchError("Report output must be a new file")
    report = await asyncio.to_thread(build_unsigned, arguments.source, arguments.target, arguments.ace_dex, arguments.game_library, arguments.tprt_library, arguments.gadget_library, arguments.offline_script, arguments.legacy_apk)
    def save_report():
        with report_path.open("x", encoding="utf-8") as destination:
            json.dump(report, destination, indent=2)
    await asyncio.to_thread(save_report)
    LOGGER.info("Startup test APK built; ZIP CRC passed")


if __name__ == "__main__":
    asyncio.run(main())
