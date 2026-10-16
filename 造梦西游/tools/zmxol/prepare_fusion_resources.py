"""提取一条已验证预览配方的旧包原模型，供隔离测试使用。"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile

from legacy_resources import EXPECTED_APK_SHA256, SOURCE_PREFIX, _atlas_pages


def collect_resources(archive: zipfile.ZipFile) -> dict[str, bytes]:
    counts = Counter(archive.namelist())
    entries = {}
    for pet_id in (221, 229, 9001, 9003):
        names = [f"{pet_id}.json", f"{pet_id}.atlas", f"{pet_id}.png"]
        if any(counts[SOURCE_PREFIX + name] != 1 for name in names):
            raise ValueError("Missing or duplicate original fusion model member")
        atlas = archive.read(SOURCE_PREFIX + names[1])
        _atlas_pages(atlas, frozenset([names[2]]))
        for name in names:
            raw = archive.read(SOURCE_PREFIX + name)
            if not raw:
                raise ValueError("Empty original fusion model member")
            entries[f"skeleton/pet/{name}"] = raw
    return entries


async def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original_apk", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    with args.original_apk.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != EXPECTED_APK_SHA256:
            raise ValueError("Unsupported original APK fingerprint")
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            entries = collect_resources(archive)
    args.output_directory.mkdir(parents=True, exist_ok=False)
    evidence = []
    for name, raw in entries.items():
        target = args.output_directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
        evidence.append({"target": name, "source": SOURCE_PREFIX + target.name,
                         "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    (args.output_directory / "evidence.json").write_text(
        json.dumps({"original_apk_sha256": EXPECTED_APK_SHA256, "files": evidence}, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(run())
