"""用已核对的 ARM64 运行时快照恢复加载信息；输出仍需游戏运行验证。"""

import argparse
import asyncio
import hashlib
import json
import logging
import struct
from pathlib import Path


LOGGER = logging.getLogger(__name__)
ORIGINAL_SHA256 = "77af9fc72f675784a0fe347cda8c21e952e98800433410a4e68158d9d1afe6ee"
SNAPSHOT_SHA256 = "7022ab772da77d71eb3820a2f67f11c2182afcdd55a03e1b845d1719b8b67dcf"
STDIO_GUARDS = (("fread", 0x67A2568), ("fwrite", 0x67A2634))
STDIO_GUARD_ORIGINAL = bytes.fromhex("080100d0")
STDIO_GUARD_FORWARD = bytes.fromhex("20000014")
DT_INIT, DT_INIT_ARRAY, DT_INIT_ARRAYSZ = 12, 25, 27
DT_RELACOUNT = 0x6FFFFFF9


class RestoreError(ValueError):
    """输入不属于已验证版本或 ELF 加载信息不完整。"""


def restore_initializers(data: bytearray, offset: int, size: int, address: int, count: int, guard_address: int) -> None:
    if offset < 0 or size < 16 or size % 16 or offset + size > len(data) or count <= 0:
        raise RestoreError("Invalid dynamic table bounds")
    entries = []
    for position in range(offset, offset + size, 16):
        tag, value = struct.unpack_from("<QQ", data, position)
        if tag == 0:
            break
        entries.append((position, tag, value))
    else:
        raise RestoreError("Missing dynamic table terminator")
    initializers = [position for position, tag, value in entries if tag == DT_INIT and value == guard_address]
    count_slots = [position for position, tag, _ in entries if tag == DT_RELACOUNT]
    if len(initializers) != 1 or len(count_slots) != 1 or any(tag in (DT_INIT_ARRAY, DT_INIT_ARRAYSZ) for _, tag, _ in entries):
        raise RestoreError("Unsupported initializer layout")
    struct.pack_into("<QQ", data, initializers[0], DT_INIT_ARRAY, address)
    # RELACOUNT 只是加速信息；替换终止标记前的槽位，保留标准 RELA 表。
    struct.pack_into("<QQ", data, count_slots[0], DT_INIT_ARRAYSZ, count * 8)


def restore_image(original: bytes, snapshot: bytes) -> tuple[bytes, dict]:
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA256:
        raise RestoreError("Unsupported original native library")
    if hashlib.sha256(snapshot).hexdigest() != SNAPSHOT_SHA256:
        raise RestoreError("Unsupported runtime snapshot")
    if original[:64] != snapshot[:64] or len(snapshot) != 0x5E3C000:
        raise RestoreError("Snapshot ELF header mismatch")
    if original[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", original, 18)[0] != 183:
        raise RestoreError("Expected little-endian ARM64 ELF")
    array, count = struct.unpack_from("<II", original, 0x67A4034 + 0x10)
    if (array, count) != (0x5E4CD98, 4987):
        raise RestoreError("Unexpected original initializer metadata")
    for offset in range(0x1C9538, 0x1C9538 + 0x2568, 24):
        target, info, addend = struct.unpack_from("<QQq", original, offset)
        new_target, new_info, new_addend = struct.unpack_from("<QQq", snapshot, offset)
        if (target, addend, info & 0xFFFFFFFF) != (new_target, new_addend, new_info & 0xFFFFFFFF) or new_info >> 32 >= 23095:
            raise RestoreError("Runtime import relocation mismatch")
    output = bytearray(original)
    sections = ((0x1C9538, 0x2568), (0x1CA22C0, 0x34E3740), (0x5185A00, 0x311E60))
    for offset, size in sections:
        output[offset:offset + size] = snapshot[offset:offset + size]
    restore_initializers(output, 0x67A4240, 0x240, array, count, 0x68B23C4)
    for _, offset in STDIO_GUARDS:
        if output[offset:offset + 4] != STDIO_GUARD_ORIGINAL:
            raise RestoreError("Unexpected stdio guard instructions")
        # 转发到原 stdio 跳板，避免未初始化的 guard 终止资源读写。
        output[offset:offset + 4] = STDIO_GUARD_FORWARD
    result = bytes(output)
    report = {
        "status": "EXPERIMENTAL_NOT_PLAYABLE",
        "original_sha256": ORIGINAL_SHA256,
        "snapshot_sha256": SNAPSHOT_SHA256,
        "output_sha256": hashlib.sha256(result).hexdigest(),
        "initializer_slots": count,
        "import_relocations": 399,
        "restored_ranges": [{"offset": hex(offset), "size": size} for offset, size in sections],
        "native_patches": [{
            "offset": hex(offset),
            "original": STDIO_GUARD_ORIGINAL.hex(),
            "replacement": STDIO_GUARD_FORWARD.hex(),
            "purpose": f"forward-{name}-without-guard-initialization",
        } for name, offset in STDIO_GUARDS],
    }
    return result, report


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    try:
        original, snapshot = await asyncio.gather(
            asyncio.to_thread(arguments.original.read_bytes), asyncio.to_thread(arguments.snapshot.read_bytes)
        )
        output, report = await asyncio.to_thread(restore_image, original, snapshot)
        # 独占创建，拒绝覆盖原库或已有分析产物。
        def save():
            with arguments.output.open("xb") as destination:
                destination.write(output)
        await asyncio.to_thread(save)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, RestoreError) as error:
        LOGGER.error("Native restoration failed (%s)", type(error).__name__)
        raise RestoreError("Native restoration failed") from error


if __name__ == "__main__":
    asyncio.run(main())
