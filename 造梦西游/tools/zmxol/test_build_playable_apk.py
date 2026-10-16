import hashlib
import json
import zipfile

import pytest

import build_playable_apk as module


def test_package_preserves_assets_and_embeds_runtime(tmp_path, monkeypatch):
    base = tmp_path / 'base.apk'
    with zipfile.ZipFile(base, 'w') as archive:
        archive.writestr('lib/arm64-v8a/liboffline.script.so', b'old bridge')
        archive.writestr('lib/arm64-v8a/libgame.so', b'original native')
        archive.writestr('assets/original.dat', b'original')
        archive.writestr('META-INF/OLD.SF', b'old signature')
    monkeypatch.setattr(module, 'BASE_SHA256', hashlib.sha256(base.read_bytes()).hexdigest())
    monkeypatch.setattr(module, 'patch_network_notice', lambda value: value + b' notice patched')
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'roledata': {'player': {'roleid': 1}}}))
    target = tmp_path / 'new.apk'
    module.build(base, target, profile, [])
    with zipfile.ZipFile(target) as result:
        assert result.read('assets/original.dat') == b'original'
        assert result.read('assets/offline-v6-profile.json') == profile.read_bytes()
        assert b'offline-playable-feedback-ready' in result.read('lib/arm64-v8a/liboffline.script.so')
        assert 'META-INF/OLD.SF' not in result.namelist()
        assert result.read('lib/arm64-v8a/libgame.so') == b'original native notice patched'
    with pytest.raises(FileExistsError):
        module.build(base, target, profile, [])
    profile.write_text(json.dumps({'roledata': {'player': {'roleid': 1}}, '_DEBUG_ONLY_fusion': {}}))
    with pytest.raises(ValueError, match='experimental'):
        module.build(base, tmp_path / 'unsafe.apk', profile, [])


def test_notice_patch_preserves_layout_and_other_warnings(monkeypatch):
    first = '网络连接出错(%ld),请检查网络链接是否正常 \n'.encode() + b'\0'
    warning = '网络连接出错，请重新进入游戏避免存档信息丢失!'.encode() + b'\0'
    raw = first + warning + first
    monkeypatch.setattr(module, 'NOTICE_OFFSETS', (0, len(first) + len(warning)))
    result = module.patch_network_notice(raw)
    assert len(result) == len(raw)
    assert result[len(first):len(first) + len(warning)] == warning
    assert result.startswith('离线请求未完成，请返回并检查存档'.encode())
    with pytest.raises(ValueError):
        module.patch_network_notice(bytes(len(raw)))
