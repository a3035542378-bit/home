import asyncio
import hashlib
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

import apk_patch
from apk_patch import HELPER, PatchError, build_unsigned, locate_methods, patch_dex, read_uleb
from legacy_resources import LegacyResourceError
from test_legacy_resources import BULLET_ENTRIES, BULLET_IDS, STATIC_BACKGROUND_ENTRIES, legacy_apk
from test_offline_manifest import DEFAULT_PERMISSIONS, INTERNET, fixture_manifest


def uleb(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def fixture_dex():
    names = [HELPER, "initHummingbirdSDK", "checkHummingbirdSDKUpdate", "setHummingbirdSDKInitEnd"]
    data = bytearray(0x70 + len(names) * 4 + 4 + 3 * 8 + 32)
    data[:8] = b"dex\n035\0"
    strings_offset = 0x70
    type_offset = strings_offset + len(names) * 4
    method_offset = type_offset + 4
    class_offset = method_offset + 24
    struct.pack_into("<II", data, 0x38, len(names), strings_offset)
    struct.pack_into("<II", data, 0x40, 1, type_offset)
    struct.pack_into("<II", data, 0x58, 3, method_offset)
    struct.pack_into("<II", data, 0x60, 1, class_offset)
    for index, name in enumerate(names):
        struct.pack_into("<I", data, strings_offset + index * 4, len(data))
        data.extend(uleb(len(name)) + name.encode() + b"\0")
    for index in range(3):
        struct.pack_into("<HHI", data, method_offset + index * 8, 0, 0, index + 1)
    class_data = len(data)
    struct.pack_into("<I", data, class_offset + 24, class_data)
    data.extend(b"\0" * 32)
    while len(data) % 4:
        data.append(0)
    offsets = []
    for _ in range(3):
        offsets.append(len(data))
        data.extend(struct.pack("<HHHHII", 1, 0, 2, 0, 0, 8))
        data.extend(struct.pack("<8H", *([0] * 7 + [0xE])))
    encoded = b"\0\0\3\0"
    for index, offset in enumerate(offsets):
        encoded += uleb(0 if index == 0 else 1) + uleb(9) + uleb(offset)
    data[class_data:class_data + len(encoded)] = encoded
    struct.pack_into("<I", data, 0x20, len(data))
    return bytes(data)


def test_patch_changes_only_selected_code_and_dex_checksums():
    original = fixture_dex()
    modified, report = patch_dex(original)
    assert len(modified) == len(original)
    assert len(report) == 2
    methods = locate_methods(modified)
    initialization = methods["initHummingbirdSDK"][1] + 16
    update = methods["checkHummingbirdSDKUpdate"][1] + 16
    assert struct.unpack_from("<5H", modified, initialization) == (0x1012, 0x1071, 2, 0, 0xE)
    assert struct.unpack_from("<8H", modified, update) == (0xE, 0, 0, 0, 0, 0, 0, 0)
    allowed = set(range(8, 32)) | set(range(initialization, initialization + 16)) | set(range(update, update + 16))
    assert all(before == after or index in allowed for index, (before, after) in enumerate(zip(original, modified)))
    assert modified[12:32] == hashlib.sha1(modified[32:]).digest()
    assert struct.unpack_from("<I", modified, 8)[0] == zlib.adler32(modified[12:]) & 0xFFFFFFFF


def test_rejects_try_regions_instead_of_leaving_invalid_exception_handlers():
    data = bytearray(fixture_dex())
    offset = locate_methods(data)["initHummingbirdSDK"][1]
    struct.pack_into("<H", data, offset + 6, 1)
    with pytest.raises(PatchError, match="layout"):
        patch_dex(data)


def test_rejects_insufficient_registers():
    data = bytearray(fixture_dex())
    offset = locate_methods(data)["initHummingbirdSDK"][1]
    struct.pack_into("<H", data, offset, 0)
    with pytest.raises(PatchError, match="registers"):
        patch_dex(data)


@pytest.mark.parametrize("data", [b"", b"not a dex", b"dex\n035\0" + b"\0" * 104])
def test_rejects_invalid_dex_input(data):
    with pytest.raises(PatchError):
        patch_dex(data)


@pytest.mark.parametrize("data", [b"\x80", b"\x80" * 5])
def test_rejects_unterminated_uleb(data):
    with pytest.raises(PatchError):
        read_uleb(data, 0)


def test_real_apk_has_exactly_one_supported_helper_dex():
    apk = Path("/Users/baize/Downloads/造梦西游OL.apk (1).1")
    if not apk.is_file():
        pytest.skip("Local source APK unavailable")
    reports = []
    with zipfile.ZipFile(apk) as source:
        for name in source.namelist():
            if name.startswith("classes") and name.endswith(".dex"):
                original = source.read(name)
                modified, report = patch_dex(original)
                if report:
                    reports.append((name, report))
                    assert len(modified) == len(original)
                    assert modified[12:32] == hashlib.sha1(modified[32:]).digest()
                else:
                    assert modified == original
    assert len(reports) == 1
    assert {item["method"] for item in reports[0][1]} == {"initHummingbirdSDK", "checkHummingbirdSDKUpdate"}


@pytest.fixture
def apk_inputs(tmp_path, monkeypatch):
    source = tmp_path / "original.apk"
    game = tmp_path / "libgame.so"
    tprt = tmp_path / "libtprt.so"
    game.write_bytes(b"verified-game-library-fixture")
    tprt.write_bytes(b"verified-tprt-library-fixture")
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("classes3.dex", fixture_dex())
        archive.writestr("assets/fixture.txt", b"preserve-game-resource")
        archive.writestr("lib/arm64-v8a/libgame.so", b"original-game-library")
        archive.writestr("lib/arm64-v8a/libtprt.so", b"original-tprt-library")
        archive.writestr("lib/armeabi/libgame.so", b"preserve-arm32-library")
        archive.writestr("META-INF/ORIGINAL.RSA", b"original-signature")
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(apk_patch, "EXPECTED_NATIVE_SHA256", {
        "lib/arm64-v8a/libgame.so": hashlib.sha256(game.read_bytes()).hexdigest(),
        "lib/arm64-v8a/libtprt.so": hashlib.sha256(tprt.read_bytes()).hexdigest(),
    })
    return source, tmp_path / "new.apk", game, tprt


def test_build_replaces_only_supported_dex_and_arm64_libraries(apk_inputs):
    source, target, game, tprt = apk_inputs
    original = source.read_bytes()
    report = build_unsigned(source, target, game_library=game, tprt_library=tprt)
    assert source.read_bytes() == original
    assert report["status"] == "EXPERIMENTAL_NOT_PLAYABLE"
    assert report["native_patch_abi"] == "arm64-v8a"
    assert report["zip_crc"] == "PASS"
    assert len(report["modified_dex"]) == 1
    assert report["modified_dex"][0]["entry"] == "classes3.dex"
    assert {item["entry"]: item["output_sha256"] for item in report["modified_native"]} == apk_patch.EXPECTED_NATIVE_SHA256
    with zipfile.ZipFile(target) as archive:
        assert archive.read("lib/arm64-v8a/libgame.so") == game.read_bytes()
        assert archive.read("lib/arm64-v8a/libtprt.so") == tprt.read_bytes()
        assert archive.read("lib/armeabi/libgame.so") == b"preserve-arm32-library"
        assert archive.read("assets/fixture.txt") == b"preserve-game-resource"
        assert archive.read("classes3.dex") == patch_dex(fixture_dex())[0]
        assert "META-INF/ORIGINAL.RSA" not in archive.namelist()
    assert not target.with_suffix(".apk.partial").exists()
    assert report["excluded_native_abis"] == []
    assert report["excluded_native_entry_count"] == 0


def test_only_gadget_mode_excludes_all_non_arm64_library_entries(gadget_inputs, monkeypatch):
    source, target, game, tprt, *_ = gadget_inputs
    other_entries = ["lib/x86/", "lib/x86/libfixture.so", "lib/armeabi-v7a/libfixture.so"]
    with zipfile.ZipFile(source, "a") as archive:
        for name in other_entries:
            archive.writestr(name, b"other-abi-fixture" if not name.endswith("/") else b"")
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    ordinary_target = target.with_name("ordinary-startup.apk")
    ordinary = build_unsigned(source, ordinary_target, game_library=game, tprt_library=tprt)
    assert ordinary["excluded_native_abis"] == []
    assert ordinary["excluded_native_entry_count"] == 0
    with zipfile.ZipFile(ordinary_target) as archive:
        assert all(name in archive.namelist() for name in other_entries + ["lib/armeabi/libgame.so"])
    gadget = gadget_build(gadget_inputs)
    assert gadget["excluded_native_abis"] == ["armeabi", "armeabi-v7a", "x86"]
    assert gadget["excluded_native_entry_count"] == 4
    with zipfile.ZipFile(target) as archive:
        assert all(not name.startswith("lib/") or name.startswith("lib/arm64-v8a/") for name in archive.namelist())
        assert archive.read("lib/arm64-v8a/libgame.so") == game.read_bytes()
        assert archive.read("assets/fixture.txt") == b"preserve-game-resource"


def test_default_build_keeps_original_native_libraries(apk_inputs):
    source, target, _, _ = apk_inputs
    report = build_unsigned(source, target)
    assert report["modified_native"] == []
    assert report["native_patch_abi"] is None
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target) as archive:
        for name in apk_patch.EXPECTED_NATIVE_SHA256:
            assert archive.read(name) == original.read(name)


@pytest.mark.parametrize("missing", ["game", "tprt"])
def test_build_requires_both_native_libraries(apk_inputs, missing):
    source, target, game, tprt = apk_inputs
    with pytest.raises(PatchError, match="Both ARM64"):
        build_unsigned(source, target, game_library=None if missing == "game" else game, tprt_library=None if missing == "tprt" else tprt)
    assert not target.exists()


@pytest.mark.parametrize("invalid", ["game", "tprt"])
def test_build_rejects_unknown_native_fingerprints(apk_inputs, invalid):
    source, target, game, tprt = apk_inputs
    (game if invalid == "game" else tprt).write_bytes(b"unknown-native-library")
    with pytest.raises(PatchError, match="native library fingerprint"):
        build_unsigned(source, target, game_library=game, tprt_library=tprt)
    assert not target.exists()
    assert not target.with_suffix(".apk.partial").exists()


def test_build_rejects_missing_native_input(apk_inputs):
    source, target, game, tprt = apk_inputs
    tprt.unlink()
    with pytest.raises(PatchError, match="Unable to read"):
        build_unsigned(source, target, game_library=game, tprt_library=tprt)
    assert not target.exists()


@pytest.mark.parametrize("existing", ["source", "target", "game", "tprt"])
def test_build_refuses_to_overwrite_source_or_existing_output(apk_inputs, existing):
    source, target, game, tprt = apk_inputs
    target.write_bytes(b"existing-output")
    destination = {"source": source, "target": target, "game": game, "tprt": tprt}[existing]
    original = destination.read_bytes()
    with pytest.raises(PatchError, match="new file"):
        build_unsigned(source, destination, game_library=game, tprt_library=tprt)
    assert destination.read_bytes() == original


@pytest.mark.parametrize("duplicate", [False, True])
def test_build_cleans_incomplete_archive_on_missing_or_duplicate_native_entries(apk_inputs, monkeypatch, duplicate):
    source, target, game, tprt = apk_inputs
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("classes3.dex", fixture_dex())
        archive.writestr("lib/arm64-v8a/libgame.so", b"original-game-library")
        if duplicate:
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("lib/arm64-v8a/libgame.so", b"duplicate-game-library")
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(PatchError, match="Startup APK build failed") as error:
        build_unsigned(source, target, game_library=game, tprt_library=tprt)
    assert "native library entries" in str(error.value.__cause__)
    assert not target.exists()
    assert not target.with_suffix(".apk.partial").exists()


def test_cli_refuses_report_path_that_would_overwrite_source(apk_inputs, monkeypatch):
    source, target, _, _ = apk_inputs
    report_path = target.with_suffix(".report.json")
    source.rename(report_path)
    original = report_path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["apk_patch.py", str(report_path), str(target)])
    with pytest.raises(PatchError, match="Report output must be a new file"):
        asyncio.run(apk_patch.main())
    assert report_path.read_bytes() == original
    assert not target.exists()


@pytest.fixture
def gadget_inputs(apk_inputs, monkeypatch):
    source, target, game, tprt = apk_inputs
    gadget = source.parent / "gadget.so"
    script = source.parent / "bridge.js"
    gadget.write_bytes(b"verified-gadget-library-fixture")
    script.write_bytes(b"rpc.exports = { init() { console.log('offline fixture'); } };\n")
    empty_dex = bytearray(0x70)
    empty_dex[:8] = b"dex\n035\0"
    struct.pack_into("<I", empty_dex, 0x20, len(empty_dex))
    with zipfile.ZipFile(source, "a") as archive:
        archive.writestr("classes.dex", empty_dex)
        archive.writestr("AndroidManifest.xml", fixture_manifest())
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(apk_patch, "EXPECTED_GADGET_SHA256", hashlib.sha256(gadget.read_bytes()).hexdigest())
    # 此 fixture 只验证 ZIP 编排；真实 dexlib2 修改另见 test_gadget_patch.py。
    monkeypatch.setattr(apk_patch, "patch_gadget_dex", lambda data: (data, {
        "class_count": 1, "original_instructions": 8, "patched_instructions": 10,
        "original_tail_preserved": True,
    }))
    return source, target, game, tprt, gadget, script


def gadget_build(inputs, **overrides):
    source, target, game, tprt, gadget, script = inputs
    options = {"game_library": game, "tprt_library": tprt, "gadget_library": gadget, "offline_script": script}
    options.update(overrides)
    return build_unsigned(source, target, **options)


def test_gadget_build_embeds_exact_script_and_fixed_script_config(gadget_inputs):
    source, target, _, _, gadget, script = gadget_inputs
    original = source.read_bytes()
    report = gadget_build(gadget_inputs)
    assert source.read_bytes() == original
    assert report["status"] == "EXPERIMENTAL_NOT_PLAYABLE"
    assert report["gadget_version"] == "16.7.19"
    assert "legacy_resources" not in report
    assert {item["entry"] for item in report["modified_dex"]} == {"classes.dex", "classes3.dex"}
    assert report["manifest"] == {
        "entry": "AndroidManifest.xml",
        "removed_permissions": [{"element": "uses-permission", "name": INTERNET}],
        "removed_permission_count": 1,
    }
    with zipfile.ZipFile(target) as archive:
        assert archive.read("AndroidManifest.xml") == fixture_manifest([DEFAULT_PERMISSIONS[1]])
        assert archive.read(apk_patch.GADGET_ENTRY) == gadget.read_bytes()
        assert archive.read(apk_patch.OFFLINE_SCRIPT_ENTRY) == script.read_bytes()
        assert json.loads(archive.read(apk_patch.GADGET_CONFIG_ENTRY)) == {
            "interaction": {"type": "script", "path": "liboffline.script.so", "on_change": "ignore"},
            "runtime": "qjs",
        }
        assert {item["entry"]: item["sha256"] for item in report["added_entries"]} == {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in (apk_patch.GADGET_ENTRY, apk_patch.GADGET_CONFIG_ENTRY, apk_patch.OFFLINE_SCRIPT_ENTRY)
        }
        assert all(archive.getinfo(item["entry"]).compress_type == zipfile.ZIP_DEFLATED for item in report["added_entries"])
        assert "lib/armeabi/libgame.so" not in archive.namelist()
    assert report["excluded_native_abis"] == ["armeabi"]
    assert report["excluded_native_entry_count"] == 1


def test_ordinary_build_preserves_manifest_bytes_and_report(gadget_inputs):
    source, target, game, tprt, *_ = gadget_inputs
    report = build_unsigned(source, target, game_library=game, tprt_library=tprt)
    assert "manifest" not in report
    assert "legacy_resources" not in report
    with zipfile.ZipFile(target) as archive:
        assert archive.read("AndroidManifest.xml") == fixture_manifest()


@pytest.mark.parametrize("manifest", [None, b"invalid AXML", fixture_manifest([DEFAULT_PERMISSIONS[1]])])
def test_gadget_manifest_validation_and_zero_removal_report(gadget_inputs, monkeypatch, manifest):
    source, target, *libraries = gadget_inputs
    replacement = source.with_name("manifest-input.apk")
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(replacement, "w") as archive:
        for info in original.infolist():
            if info.filename != "AndroidManifest.xml":
                archive.writestr(info, original.read(info))
        if manifest is not None:
            archive.writestr("AndroidManifest.xml", manifest)
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(replacement.read_bytes()).hexdigest())
    inputs = replacement, target, *libraries
    if manifest is None or manifest == b"invalid AXML":
        with pytest.raises(PatchError, match="Startup APK build failed"):
            gadget_build(inputs)
        assert not target.exists()
        assert not target.with_suffix(".apk.partial").exists()
    else:
        report = gadget_build(inputs)
        assert report["manifest"]["removed_permissions"] == []
        assert report["manifest"]["removed_permission_count"] == 0
        with zipfile.ZipFile(target) as archive:
            assert archive.read("AndroidManifest.xml") == manifest


def test_gadget_build_embeds_all_legacy_resources_without_changing_their_bytes(gadget_inputs, legacy_apk):
    source, target, *_ = gadget_inputs
    old_apk, _ = legacy_apk()
    original, original_legacy = source.read_bytes(), old_apk.read_bytes()
    report = gadget_build(gadget_inputs, legacy_apk=old_apk)
    recovery = report["legacy_resources"]
    assert recovery["source_apk"] == str(old_apk)
    assert recovery["source_version"] == "11.6.0"
    assert recovery["source_sha256"] == hashlib.sha256(original_legacy).hexdigest()
    assert recovery["role_ids"] == [1, 5]
    assert recovery["enemy_ids"] == [300, 301, 302, 303, 304, 305, 322, 323, 324, 516]
    assert recovery["pet_ids"] == [210, 252]
    assert recovery["bullet_ids"] == BULLET_IDS
    assert recovery["static_background_ids"] == [1, 2]
    assert {item["target_entry"] for item in recovery["files"] if "static_background_id" in item} == set(STATIC_BACKGROUND_ENTRIES)
    assert [(item["enemy_id"], item["file_count"]) for item in recovery["enemies"]] == [(enemy_id, 3) for enemy_id in (300, 301, 302, 303, 304, 305, 322, 323, 324, 516)]
    assert {item["target_entry"] for item in recovery["files"] if "enemy_id" in item} == {
        f"assets/images/hd/skeleton/enemy/{enemy_id}.{extension}"
        for enemy_id in (300, 301, 302, 303, 304, 305, 322, 323, 324, 516) for extension in ("json", "atlas", "png")
    }
    assert {item["target_entry"] for item in recovery["files"] if "bullet_id" in item} == set(BULLET_ENTRIES)
    assert {item["target_entry"] for item in recovery["files"] if "pet_id" in item} == {
        f"assets/images/hd/skeleton/pet/{pet_id}.{extension}" for pet_id in (210, 252) for extension in ("json", "atlas", "png")
    }
    assert recovery["file_count"] == len(recovery["files"]) == 321
    assert recovery["texture_page_count"] == 219
    assert recovery["bullet_texture_count"] == 36
    assert len(report["added_entries"]) == 324
    added_hashes = {item["entry"]: item["sha256"] for item in report["added_entries"]}
    with zipfile.ZipFile(old_apk) as legacy, zipfile.ZipFile(target) as archive:
        for item in recovery["files"]:
            expected = legacy.read(item["source_entry"])
            assert archive.read(item["target_entry"]) == expected
            assert archive.getinfo(item["target_entry"]).compress_type == zipfile.ZIP_DEFLATED
            assert item["sha256"] == added_hashes[item["target_entry"]] == hashlib.sha256(expected).hexdigest()
            assert item["bytes"] == len(expected)
        assert archive.read("assets/fixture.txt") == b"preserve-game-resource"
        assert archive.read("AndroidManifest.xml") == fixture_manifest([DEFAULT_PERMISSIONS[1]])
        assert "META-INF/ORIGINAL.RSA" not in archive.namelist()
        assert "lib/armeabi/libgame.so" not in archive.namelist()
        assert all("role_1_bul_1112" not in entry for entry in archive.namelist())
        assert len(archive.namelist()) == len(set(archive.namelist()))
    assert source.read_bytes() == original
    assert old_apk.read_bytes() == original_legacy


@pytest.mark.parametrize("with_native", [False, True])
def test_legacy_resources_are_rejected_outside_gadget_mode(apk_inputs, with_native):
    source, target, game, tprt = apk_inputs
    native = {"game_library": game, "tprt_library": tprt} if with_native else {}
    with pytest.raises(PatchError, match="Legacy resources require Gadget mode"):
        build_unsigned(source, target, legacy_apk=source.parent / "legacy.apk", **native)
    assert not target.exists()


@pytest.mark.parametrize("invalid", ["missing", "fingerprint", "duplicate", "bullet_texture"])
def test_gadget_build_rejects_invalid_legacy_apk(gadget_inputs, legacy_apk, invalid):
    old_apk, _ = legacy_apk(
        duplicate="1.skel" if invalid == "duplicate" else None,
        omitted=BULLET_ENTRIES[1] if invalid == "bullet_texture" else None,
    )
    if invalid == "missing":
        old_apk.unlink()
    elif invalid == "fingerprint":
        old_apk.write_bytes(b"unsupported legacy APK")
    with pytest.raises(PatchError, match="Startup APK build failed") as error:
        gadget_build(gadget_inputs, legacy_apk=old_apk)
    assert isinstance(error.value.__cause__, LegacyResourceError)
    assert not gadget_inputs[1].exists()
    assert not gadget_inputs[1].with_suffix(".apk.partial").exists()


@pytest.mark.parametrize("entry", [
    "assets/images/hd/skeleton/role/1/1.skel",
    "assets/images/hd/skeleton/role/5/5.atlas",
    "assets/images/hd/skeleton/role/1/1.skel/",
    "assets/images/hd/skeleton/role/5",
    "assets/images/hd/skeleton/enemy/303.json",
    *STATIC_BACKGROUND_ENTRIES,
    STATIC_BACKGROUND_ENTRIES[0] + "/",
    BULLET_ENTRIES[0],
    BULLET_ENTRIES[1],
])
def test_gadget_legacy_resources_do_not_replace_existing_entries(gadget_inputs, legacy_apk, monkeypatch, entry):
    source, target, *_ = gadget_inputs
    old_apk, _ = legacy_apk()
    with zipfile.ZipFile(source, "a") as archive:
        archive.writestr(entry, b"preserve-existing-resource")
    original = source.read_bytes()
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(original).hexdigest())
    with pytest.raises(PatchError, match="Startup APK build failed"):
        gadget_build(gadget_inputs, legacy_apk=old_apk)
    assert source.read_bytes() == original
    assert not target.exists()
    assert not target.with_suffix(".apk.partial").exists()


def test_legacy_and_gadget_additions_are_validated_before_dictionary_merge(gadget_inputs, monkeypatch):
    monkeypatch.setattr(apk_patch, "load_legacy_game_resources", lambda path: ({apk_patch.GADGET_ENTRY: b"cannot-replace-gadget"}, {}))
    with pytest.raises(PatchError, match="Startup APK build failed") as error:
        gadget_build(gadget_inputs, legacy_apk=gadget_inputs[0].parent / "legacy.apk")
    assert "Duplicate ZIP entry path" in str(error.value.__cause__)
    assert not gadget_inputs[1].exists()


@pytest.mark.parametrize("missing", ["gadget_library", "offline_script"])
def test_gadget_options_must_be_paired(gadget_inputs, missing):
    with pytest.raises(PatchError, match="provided together"):
        gadget_build(gadget_inputs, **{missing: None})
    assert not gadget_inputs[1].exists()


def test_gadget_requires_verified_native_pair(gadget_inputs):
    with pytest.raises(PatchError, match="requires both native libraries"):
        gadget_build(gadget_inputs, game_library=None, tprt_library=None)


def test_gadget_rejects_ace_replacement_mode(gadget_inputs):
    with pytest.raises(PatchError, match="cannot use --ace-dex"):
        gadget_build(gadget_inputs, ace_dex=gadget_inputs[0].parent / "unused.dex")


def test_gadget_rejects_unknown_binary_fingerprint(gadget_inputs):
    gadget_inputs[4].write_bytes(b"unknown-gadget-library")
    with pytest.raises(PatchError, match="Gadget library fingerprint"):
        gadget_build(gadget_inputs)
    assert not gadget_inputs[1].exists()


@pytest.mark.parametrize("script", [b"", b" \n", b"\xff", b"rpc.exports = {};\0"])
def test_gadget_rejects_invalid_script_bytes(gadget_inputs, script):
    gadget_inputs[5].write_bytes(script)
    with pytest.raises(PatchError, match="Offline script must be"):
        gadget_build(gadget_inputs)


@pytest.mark.parametrize("entry", [apk_patch.GADGET_ENTRY, apk_patch.GADGET_CONFIG_ENTRY, apk_patch.OFFLINE_SCRIPT_ENTRY, apk_patch.GADGET_ENTRY + "/"])
def test_gadget_rejects_existing_embedded_entries(gadget_inputs, monkeypatch, entry):
    source, target, *_ = gadget_inputs
    with zipfile.ZipFile(source, "a") as archive:
        archive.writestr(entry, b"existing-content")
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(PatchError, match="Startup APK build failed"):
        gadget_build(gadget_inputs)
    assert not target.exists()
    assert not target.with_suffix(".apk.partial").exists()


@pytest.mark.parametrize("entry", ["/absolute", "../parent", "assets/../parent", "assets//empty", "assets/./dot", "C:/drive", "assets\\backslash"])
def test_build_rejects_unsafe_zip_paths(apk_inputs, monkeypatch, entry):
    source, target, *_ = apk_inputs
    with zipfile.ZipFile(source, "a") as archive:
        archive.writestr(entry, b"invalid")
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(PatchError, match="Startup APK build failed") as error:
        build_unsigned(source, target)
    assert "Unsafe ZIP entry path" in str(error.value.__cause__)
    assert not target.exists()
    assert not target.with_suffix(".apk.partial").exists()


@pytest.mark.parametrize("entry", ["classes3.dex", "assets/fixture.txt"])
def test_build_rejects_duplicate_dex_or_resource_entries(apk_inputs, monkeypatch, entry):
    source, target, *_ = apk_inputs
    with zipfile.ZipFile(source, "a") as archive:
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(entry, b"duplicate")
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(PatchError, match="Startup APK build failed") as error:
        build_unsigned(source, target)
    assert "Duplicate ZIP entry path" in str(error.value.__cause__)
    assert not target.exists()


@pytest.mark.parametrize("entries", [["dir", "dir/child"], ["dir/", "dir"], ["null\0hidden"]])
def test_zip_entry_validation_rejects_directory_collisions_and_nul(entries):
    with pytest.raises(PatchError):
        apk_patch.validate_entries(entries)


@pytest.mark.parametrize("which", ["target", "partial", "report"])
def test_cli_rejects_dangling_output_symlinks(apk_inputs, monkeypatch, which):
    source, target, *_ = apk_inputs
    path = {"target": target, "partial": target.with_suffix(".apk.partial"), "report": target.with_suffix(".report.json")}[which]
    missing = target.parent / "must-not-be-created"
    path.symlink_to(missing)
    monkeypatch.setattr(sys, "argv", ["apk_patch.py", str(source), str(target)])
    with pytest.raises(PatchError):
        asyncio.run(apk_patch.main())
    assert path.is_symlink()
    assert not missing.exists()


def test_build_does_not_overwrite_output_created_during_build(apk_inputs, monkeypatch):
    source, target, *_ = apk_inputs
    original_hardlink = Path.hardlink_to
    def simulate_competing_writer(destination, temporary):
        destination.write_bytes(b"another-build-result")
        original_hardlink(destination, temporary)
    monkeypatch.setattr(Path, "hardlink_to", simulate_competing_writer)
    with pytest.raises(PatchError, match="Startup APK build failed"):
        build_unsigned(source, target)
    assert target.read_bytes() == b"another-build-result"
    assert not target.with_suffix(".apk.partial").exists()


def test_unsigned_build_removes_all_old_v1_signatures(apk_inputs, monkeypatch):
    source, target, *_ = apk_inputs
    signatures = ["META-INF/CERT.SF", "META-INF/CERT.DSA", "META-INF/CERT.EC", "META-INF/MANIFEST.MF"]
    with zipfile.ZipFile(source, "a") as archive:
        for name in signatures:
            archive.writestr(name, b"old-signature")
        archive.writestr("META-INF/keep.txt", b"ordinary-metadata")
    monkeypatch.setattr(apk_patch, "EXPECTED_APK_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    build_unsigned(source, target)
    with zipfile.ZipFile(target) as archive:
        assert not set(signatures + ["META-INF/ORIGINAL.RSA"]) & set(archive.namelist())
        assert archive.read("META-INF/keep.txt") == b"ordinary-metadata"


@pytest.mark.parametrize("include_legacy", [False, True])
def test_cli_routes_gadget_options_and_writes_report(gadget_inputs, legacy_apk, monkeypatch, include_legacy):
    source, target, game, tprt, gadget, script = gadget_inputs
    arguments = [
        "apk_patch.py", str(source), str(target), "--game-library", str(game),
        "--tprt-library", str(tprt), "--gadget-library", str(gadget), "--offline-script", str(script),
    ]
    if include_legacy:
        old_apk, _ = legacy_apk()
        arguments.extend(["--legacy-apk", str(old_apk)])
    monkeypatch.setattr(sys, "argv", arguments)
    asyncio.run(apk_patch.main())
    report = json.loads(target.with_suffix(".report.json").read_text())
    assert report["gadget_version"] == "16.7.19"
    assert len(report["added_entries"]) == (324 if include_legacy else 3)
    if include_legacy:
        assert report["legacy_resources"]["source_apk"] == str(old_apk)
        assert report["legacy_resources"]["file_count"] == 321
        assert report["legacy_resources"]["enemy_ids"] == [300, 301, 302, 303, 304, 305, 322, 323, 324, 516]
        assert report["legacy_resources"]["pet_ids"] == [210, 252]
        assert report["legacy_resources"]["bullet_ids"] == BULLET_IDS
        assert report["legacy_resources"]["static_background_ids"] == [1, 2]
    else:
        assert "legacy_resources" not in report
