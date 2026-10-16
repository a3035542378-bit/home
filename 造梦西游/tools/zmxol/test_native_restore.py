import struct
from pathlib import Path

import pytest

from native_restore import DT_INIT, DT_INIT_ARRAY, DT_INIT_ARRAYSZ, DT_RELACOUNT, RestoreError, restore_image, restore_initializers


def dynamic_fixture():
    entries = [(DT_INIT, 0x3000), (DT_RELACOUNT, 25), (0, 0), (DT_RELACOUNT, 25), (0, 0)]
    return bytearray(b"ELF prefix data!" + b"".join(struct.pack("<QQ", *entry) for entry in entries))


def test_initializer_size_is_before_first_null_and_tail_is_unchanged():
    data = dynamic_fixture()
    before = bytes(data)
    restore_initializers(data, 16, 80, 0x2000, 7, 0x3000)
    assert struct.unpack_from("<QQ", data, 16) == (DT_INIT_ARRAY, 0x2000)
    assert struct.unpack_from("<QQ", data, 32) == (DT_INIT_ARRAYSZ, 56)
    assert data[:16] == before[:16]
    assert data[48:] == before[48:]


def test_does_not_use_acceleration_slot_after_terminator():
    data = dynamic_fixture()
    struct.pack_into("<Q", data, 32, 1)
    before = bytes(data)
    with pytest.raises(RestoreError, match="layout"):
        restore_initializers(data, 16, 80, 0x2000, 7, 0x3000)
    assert bytes(data) == before


def test_rejects_missing_terminator_without_partial_changes():
    data = dynamic_fixture()
    struct.pack_into("<Q", data, 48, 1)
    struct.pack_into("<Q", data, 80, 1)
    before = bytes(data)
    with pytest.raises(RestoreError, match="terminator"):
        restore_initializers(data, 16, 80, 0x2000, 7, 0x3000)
    assert bytes(data) == before


@pytest.mark.parametrize("offset,size,count", [(-1, 80, 7), (16, 81, 7), (16, 96, 7), (16, 80, 0)])
def test_rejects_invalid_dynamic_bounds(offset, size, count):
    with pytest.raises(RestoreError, match="bounds"):
        restore_initializers(dynamic_fixture(), offset, size, 0x2000, count, 0x3000)


def test_rejects_existing_initializer_array():
    data = dynamic_fixture()
    struct.pack_into("<Q", data, 16, DT_INIT_ARRAY)
    with pytest.raises(RestoreError, match="layout"):
        restore_initializers(data, 16, 80, 0x2000, 7, 0x3000)


def test_wrong_original_is_rejected():
    with pytest.raises(RestoreError, match="original"):
        restore_image(b"not a supported ELF", b"not a snapshot")


def test_verified_original_and_snapshot_restore_exact_expected_image():
    original = Path("/private/tmp/zmxol-revival-newer/lib/arm64-v8a/libgame.so")
    snapshot = Path(__file__).resolve().parents[2] / "artifacts/zmxol-offline/15.7.2/game-runtime-code.bin"
    if not original.exists() or not snapshot.exists():
        pytest.skip("Requires the verified original ARM64 library and runtime snapshot")
    original_bytes = original.read_bytes()
    restored, report = restore_image(original_bytes, snapshot.read_bytes())
    assert len(restored) == len(original_bytes)
    assert report["output_sha256"] == "91a8b745b51a2e4b7743a94d5fe7f1e6e1ec50c1ed6149c64d2b5b2cf5b9ddb0"
    assert report["status"] == "EXPERIMENTAL_NOT_PLAYABLE"
    for offset in (0x67A2568, 0x67A2634):
        assert original_bytes[offset:offset + 4] == bytes.fromhex("080100d0")
        assert restored[offset:offset + 4] == bytes.fromhex("20000014")
    assert report["native_patches"] == [{
        "offset": "0x67a2568",
        "original": "080100d0",
        "replacement": "20000014",
        "purpose": "forward-fread-without-guard-initialization",
    }, {
        "offset": "0x67a2634",
        "original": "080100d0",
        "replacement": "20000014",
        "purpose": "forward-fwrite-without-guard-initialization",
    }]
    with pytest.raises(RestoreError, match="snapshot"):
        restore_image(original_bytes, b"invalid snapshot")
