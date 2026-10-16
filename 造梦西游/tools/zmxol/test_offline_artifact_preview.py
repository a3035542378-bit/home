"""原桥接的缺资源预览回退；native 替身不代替 Android 动画验收。"""

import pytest

from test_offline_bridge import run_production_js


NODE_PREVIEW_CHECK = r"""
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8')), reports = [], hooks = new Map();
const bridge = fs.readFileSync(process.argv[1], 'utf8'), start = bridge.indexOf('function configureOfflineArtifactPreview(game){');
if (start < 0) throw new Error('Production preview function is missing');
const source = bridge.slice(start, bridge.indexOf('\nlet configured=', start));
let allocated = 0, reads = 0;
const base = 0x10000000;
function pointer(address, text) {
 return {address, add: value => pointer(address + value), isNull: () => address === 0,
  equals: other => address === other.address,
  readUtf8String: () => { reads++; if (input.failRead) throw new Error('Unexpected path read'); return text; },
  readU32: () => input.badFingerprint === address - base ? 0 :
   ({[base + 0x307c294]: 0xd10083ff, [base + 0x307c298]: 0xa90053f3})[address]
 };
}
const context = vm.createContext({
 Memory: {allocUtf8String: text => pointer(0x20000000 + allocated++, text)},
 Interceptor: {attach: (entry, callbacks) => hooks.set(entry.address, callbacks)},
 report: value => reports.push(value)
});
vm.runInContext(source, context);
try { context.configureOfflineArtifactPreview({base: pointer(base)}); }
catch (error) { process.stdout.write(JSON.stringify({configurationError: error.message, allocated, hooks: hooks.size})); process.exit(0); }
const path = input.path ?? 'skeleton/artifact_armor/509100.skel';
const original = pointer(input.nullPath ? 0 : 0x30000000, path), untouched = pointer(0x30000008, 'unchanged');
const args = [original, untouched], before = JSON.stringify(input.savedata ?? {});
hooks.get(base + 0x307c294).onEnter.call({returnAddress: pointer(base + (input.caller ?? 0x1f829d0))}, args);
process.stdout.write(JSON.stringify({
 replaced: args[0] !== original, path: args[0].isNull() ? null : (args[0] === original ? path : args[0].readUtf8String()),
 otherArgumentUnchanged: args[1] === untouched, savedataUnchanged: before === JSON.stringify(input.savedata ?? {}),
 reads, allocated, reports, hooks: [...hooks.keys()].map(address => address - base)
}));
"""


@pytest.mark.parametrize("caller", [0x1F829D0, 0x1F808F8])
def test_only_default_missing_artifact_preview_is_replaced(run_production_js, caller):
    result = run_production_js(NODE_PREVIEW_CHECK, {"caller": caller, "savedata": {"rolelv": 90, "completedguide": [900001], "bag": []}})
    assert result["replaced"] and result["path"] == "skeleton/artifact_armor/509135.skel"
    assert result["otherArgumentUnchanged"] and result["savedataUnchanged"]
    assert result["hooks"] == [0x307C294] and result["allocated"] == 1
    assert result["reports"] == [{"event": "offline-artifact-preview-fallback", "missing": 509100, "preview": 509135}]


@pytest.mark.parametrize("changes", [
    {"caller": 0x30DDB0C, "failRead": True},
    {"caller": 0x1F829CC, "failRead": True},
    {"caller": 0x1F808F4, "failRead": True},
    {"caller": 0x1F808FC, "failRead": True},
    {"path": "skeleton/artifact_armor/509100.json"},
    {"path": "skeleton/artifact_armor/509135.skel"},
    {"path": "skeleton/pet/509100.skel"},
    {"path": "skeleton/artifact_armor/509100.skel.bak"},
    {"nullPath": True, "failRead": True},
])
def test_other_paths_callers_and_null_are_untouched(run_production_js, changes):
    result = run_production_js(NODE_PREVIEW_CHECK, changes)
    assert not result["replaced"] and result["otherArgumentUnchanged"] and result["savedataUnchanged"]
    assert result["reports"] == []
    if changes.get("failRead"):
        assert result["reads"] == 0


@pytest.mark.parametrize("address", [0x307C294, 0x307C298])
def test_native_fingerprint_mismatch_installs_no_hook(run_production_js, address):
    result = run_production_js(NODE_PREVIEW_CHECK, {"badFingerprint": address})
    assert result == {"configurationError": "Artifact preview native entry fingerprint mismatch", "allocated": 0, "hooks": 0}
