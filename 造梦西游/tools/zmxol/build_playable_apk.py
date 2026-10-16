"""从已验证稳定底包生成V6离线测试包；只替换桥、加入初档和已核对资源。"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile

from playable_bridge import build_playable_bridge


BASE_SHA256 = 'a2bdc1d36bd8ea7b772b81e39e1f4c43bcdbc1f2abd7da75119b8909e24c4ba1'
NOTICE_OFFSETS = (0x5209e90, 0x520d4b0)


def patch_network_notice(native: bytes) -> bytes:
    patched = bytearray(native)
    replacement = '离线请求未完成，请返回并检查存档'.encode()
    for offset in NOTICE_OFFSETS:
        end = native.index(b'\0', offset)
        original = native[offset:end]
        if not original.startswith('网络连接出错(%ld)'.encode()) or len(replacement) > len(original):
            raise ValueError('Native notice fingerprint or size mismatch')
        patched[offset:end] = replacement + bytes(len(original) - len(replacement))
    return bytes(patched)


def build(base: Path, target: Path, profile: Path, resources: list[Path]) -> dict:
    with base.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != BASE_SHA256:
        raise ValueError('Unsupported stable APK fingerprint')
    seed = profile.read_bytes()
    data = json.loads(seed)
    if data.get('roledata', {}).get('player', {}).get('roleid') != 1 or any(key.startswith('_DEBUG') for key in data) or 'true_spirit_bag' in data:
        raise ValueError('Expected preserved ordinary Wukong profile without experimental fusion')
    source = Path(__file__).with_name('offline_bridge.js').read_text()
    bridge = build_playable_bridge(source).encode()
    additions = {'lib/arm64-v8a/liboffline.script.so': bridge, 'assets/offline-v6-profile.json': seed}
    for directory in resources:
        evidence = json.loads((directory / 'evidence.json').read_text())
        for item in evidence['files']:
            name = item['target']
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                raise ValueError('Unsafe resource path')
            payload = (directory / name).read_bytes()
            if hashlib.sha256(payload).hexdigest() != item['sha256']:
                raise ValueError('Resource fingerprint mismatch')
            target_name = 'assets/images/hd/' + name
            if target_name in additions:
                raise ValueError('Duplicate resource')
            additions[target_name] = payload
    temporary = target.with_suffix('.apk.partial')
    if target.exists() or temporary.exists():
        raise FileExistsError('Output must be new')
    try:
        with zipfile.ZipFile(base) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError('Duplicate input APK members')
            additions['lib/arm64-v8a/libgame.so'] = patch_network_notice(archive.read('lib/arm64-v8a/libgame.so'))
            for name in additions:
                if name in names and name not in ('lib/arm64-v8a/liboffline.script.so', 'lib/arm64-v8a/libgame.so'):
                    raise ValueError('Existing resource must not be overwritten: ' + name)
            with temporary.open('xb') as output, zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as result:
                for item in archive.infolist():
                    if item.filename in additions or item.filename.upper().startswith('META-INF/'):
                        continue
                    with archive.open(item) as src, result.open(item, 'w') as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                for name, payload in additions.items():
                    result.writestr(name, payload)
        with zipfile.ZipFile(temporary) as result:
            if result.testzip() is not None:
                raise ValueError('Generated APK CRC failure')
        # 同目录新文件提交，不覆盖既有APK。
        temporary.rename(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {'base_sha256': digest, 'bridge_sha256': hashlib.sha256(bridge).hexdigest(),
            'profile_sha256': hashlib.sha256(seed).hexdigest(), 'added_or_replaced': list(additions),
            'zip_crc': 'PASS', 'status': 'UNSIGNED_REQUIRES_DEVICE_ACCEPTANCE'}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('profile', type=Path)
    parser.add_argument('resources', type=Path, nargs='*')
    args = parser.parse_args()
    report = await asyncio.to_thread(build, args.base, args.target, args.profile, args.resources)
    with args.target.with_suffix('.report.json').open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    asyncio.run(main())
