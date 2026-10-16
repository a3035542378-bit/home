"""提取强良兽悟空合体原模型，按原客户端新路径隔离映射。"""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile

from legacy_resources import EXPECTED_APK_SHA256, SOURCE_PREFIX, _atlas_pages


def collect_armor_resources(archive: zipfile.ZipFile) -> dict[str, bytes]:
    # shortcut: 只验收强良兽/悟空95011；扩展职业或真灵前逐项核对原loader及动画。
    names = ('95011.json', '95011.atlas', '95011.png')
    counts = Counter(archive.namelist())
    if any(counts[SOURCE_PREFIX + name] != 1 for name in names):
        raise ValueError('Missing or duplicate original armor member')
    raw = {name: archive.read(SOURCE_PREFIX + name) for name in names}
    if any(not value for value in raw.values()):
        raise ValueError('Empty original armor member')
    _atlas_pages(raw['95011.atlas'], frozenset(['95011.png']))
    model = json.loads(raw['95011.json'])
    if not {'rest', 'run', '9501000', '9501010_0', '9501010_1', '9501020', '9501030'} <= model.get('animations', {}).keys():
        raise ValueError('Missing original armor animation')
    return {f'skeleton/beast_armor/9501/{name}': value for name, value in raw.items()}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original_apk', type=Path)
    parser.add_argument('output_directory', type=Path)
    args = parser.parse_args()
    with args.original_apk.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != EXPECTED_APK_SHA256:
            raise ValueError('Unsupported original APK fingerprint')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            entries = collect_armor_resources(archive)
    args.output_directory.mkdir(parents=True, exist_ok=False)
    evidence = []
    for name, raw in entries.items():
        target = args.output_directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as out: out.write(raw)
        evidence.append({'source': SOURCE_PREFIX + target.name, 'target': name,
                         'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    (args.output_directory / 'evidence.json').write_text(json.dumps({'original_apk_sha256': EXPECTED_APK_SHA256, 'files': evidence}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
