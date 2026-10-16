"""原虚空教学入口的延迟初始化契约；native 替身不替代 Android 教学验收。"""

import pytest

from test_offline_bridge import BRIDGE, run_production_js


NODE_VOID_INTRO_CHECK = r"""
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const base = 0x10000000, manager = 0x20000000, hooks = new Map();
const reports = [], declarations = [], calls = [], results = [];
let slotReads = 0, initialized = 0, present = Object.hasOwn(input, 'activity');
let activity = present ? structuredClone(input.activity) : null;
const savedata = structuredClone(input.savedata ?? {player: {completeguide: [900040]}, rewards: [], bag: {}});
const savedBefore = JSON.stringify(savedata);
const fingerprints = {
  0x296e5c0: 0xd102c3ff, 0x296e5c4: 0xa90053f3,
  0x296d95c: 0xd10143ff, 0x296d960: 0xa90053f3,
  0x298a290: 0xd11143ff, 0x298a294: 0xd10183ff,
  0x48a8cc4: 0x9783163f, 0x48a8cc8: 0x53001c00,
};
function pointer(address) {
  return {address, add: offset => pointer(address + offset), isNull: () => address === 0,
    equals: other => address === other.address, toInt32: () => address,
    toString: () => '0x' + address.toString(16),
    readU32: () => input.badFingerprint === address - base ? 0 : fingerprints[address - base],
    readPointer: () => {
      if (address !== base + 0x67b8298) throw new Error('Unexpected pointer read');
      slotReads++;
      if (input.failure === 'slot') throw new Error('Unreadable singleton slot');
      return pointer(input.singleton ?? manager);
    },
  };
}
function enter(query = {}) {
  const args = [pointer(query.manager ?? input.manager ?? manager), pointer(query.id ?? 100048), pointer(42)];
  const originalArgs = args.slice();
  const value = hooks.get(base + 0x296e5c0).onEnter.call({returnAddress: pointer(base + (query.caller ?? 0x48a8cc8))}, args);
  results.push({argsUnchanged: args.every((arg, index) => arg === originalArgs[index]), returnedUndefined: value === undefined});
}
function NativeFunction(address, result, arguments_) {
  const offset = address.address - base;
  declarations.push({offset, result, arguments: arguments_});
  return (...args) => {
    calls.push({offset, args: args.map(arg => arg.address ?? arg)});
    if (offset === 0x296d95c) {
      if (input.failure === 'query') throw new Error('Unreadable activity table');
      if (input.failure === 'queryNull' || (initialized && input.failure === 'nullAfter')) return pointer(0);
      return pointer(present ? 0x30000030 : base + 0x67b82a0);
    }
    if (offset === 0x298a290) {
      initialized++;
      if (input.reenter) enter();
      if (input.failure === 'initialize') throw new Error('Original initializer failed');
      if (input.failure !== 'missingAfter') { present = true; activity = {constructedByOriginal: true}; }
      return;
    }
    throw new Error('Unexpected native function');
  };
}
const context = vm.createContext({
  Process: {findModuleByName: () => null}, Module: {getExportByName: () => null}, NativeFunction,
  Interceptor: {attach: (entry, callbacks) => { if (entry !== null) hooks.set(entry.address, callbacks); }},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.report = value => reports.push(value);
let configurationError;
try { context.configureOfflineVoidIntro({base: pointer(base)}); }
catch (error) { configurationError = error.message; }
const callsAtConfigure = calls.length;
if (!configurationError) for (const query of input.queries ?? [{}, {}, {}]) enter(query);
process.stdout.write(JSON.stringify({
  configurationError, declarations, calls, callsAtConfigure, initialized, slotReads, activity, reports, results,
  savedataUnchanged: savedBefore === JSON.stringify(savedata),
  hooks: [...hooks].map(([address, callbacks]) => ({offset: address - base, callbacks: Object.keys(callbacks)})),
}));
"""


@pytest.fixture
def check_intro(run_production_js):
    return lambda payload: run_production_js(NODE_VOID_INTRO_CHECK, payload)


def test_missing_activity_calls_original_initializer_once_on_original_click(check_intro):
    result = check_intro({})
    assert result["hooks"] == [{"offset": 0x296E5C0, "callbacks": ["onEnter"]}]
    assert result["declarations"] == [
        {"offset": 0x296D95C, "result": "pointer", "arguments": ["pointer", "int"]},
        {"offset": 0x298A290, "result": "void", "arguments": ["pointer"]},
    ]
    assert result["callsAtConfigure"] == 0
    assert result["initialized"] == 1
    assert result["activity"] == {"constructedByOriginal": True}
    assert result["calls"] == [
        {"offset": 0x296D95C, "args": [0x20000000, 100048]},
        {"offset": 0x298A290, "args": [0x20000000]},
        *[{"offset": 0x296D95C, "args": [0x20000000, 100048]}] * 3,
    ]
    assert result["reports"] == [{"event": "offline-void-intro-initialized", "map": 100048}]
    assert result["savedataUnchanged"]
    assert result["results"] == [{"argsUnchanged": True, "returnedUndefined": True}] * 3


@pytest.mark.parametrize("activity", [
    [],
    [{"levels": {}}],
    [{"levels": {"700145": {"remaintimes": 0, "force_open": 0}}}],
    [{"levels": {"700145": {"remaintimes": 3, "force_open": 1}}}],
])
def test_existing_key_is_preserved_even_when_empty_or_exhausted(check_intro, activity):
    result = check_intro({"activity": activity})
    assert result["activity"] == activity
    assert result["initialized"] == 0 and result["reports"] == []
    assert all(call["offset"] == 0x296D95C for call in result["calls"])
    assert result["savedataUnchanged"]


@pytest.mark.parametrize("query", [
    {"caller": 0}, {"caller": 0x48A8CC4}, {"caller": 0x48A8CCC},
    {"caller": 0x4884608}, {"id": 100047}, {"id": 700145},
])
def test_other_callers_and_ids_do_not_read_or_initialize_activity(check_intro, query):
    result = check_intro({"queries": [query], "failure": "slot"})
    assert result["calls"] == [] and result["slotReads"] == 0
    assert result["reports"] == [] and result["initialized"] == 0
    assert result["results"] == [{"argsUnchanged": True, "returnedUndefined": True}]


@pytest.mark.parametrize("offset", [
    0x296E5C0, 0x296E5C4, 0x296D95C, 0x296D960,
    0x298A290, 0x298A294, 0x48A8CC4, 0x48A8CC8,
])
def test_bad_native_fingerprint_logs_failure_without_installing_hook(check_intro, offset):
    result = check_intro({"badFingerprint": offset})
    assert "Void intro native fingerprint mismatch" in result["configurationError"]
    assert result["hooks"] == [] and result["declarations"] == [] and result["calls"] == []
    assert result["reports"] == [{
        "event": "offline-void-intro-failed", "stage": "configure", "error": result["configurationError"],
    }]


@pytest.mark.parametrize("changes", [
    {"manager": 0}, {"singleton": 0}, {"manager": 0x20000008}, {"failure": "slot"},
])
def test_invalid_existing_manager_logs_failure_without_native_calls(check_intro, changes):
    result = check_intro({**changes, "queries": [{}]})
    assert result["calls"] == [] and result["initialized"] == 0
    assert len(result["reports"]) == 1
    assert result["reports"][0]["event"] == "offline-void-intro-failed"
    assert result["reports"][0]["stage"] == "entry"


@pytest.mark.parametrize("failure", ["query", "queryNull"])
def test_bad_activity_query_does_not_authorize_initialization(check_intro, failure):
    result = check_intro({"failure": failure, "queries": [{}]})
    assert result["initialized"] == 0 and len(result["calls"]) == 1
    assert result["reports"][0]["event"] == "offline-void-intro-failed"
    assert result["savedataUnchanged"]


@pytest.mark.parametrize("failure", ["initialize", "missingAfter", "nullAfter"])
def test_failed_original_initialization_is_reported_and_not_retried(check_intro, failure):
    result = check_intro({"failure": failure})
    assert result["initialized"] == 1
    assert not any(report["event"] == "offline-void-intro-initialized" for report in result["reports"])
    assert result["reports"][0]["event"] == "offline-void-intro-failed"
    assert result["savedataUnchanged"]


def test_native_reentry_cannot_repeat_missing_activity_construction(check_intro):
    result = check_intro({"reenter": True, "queries": [{}]})
    assert result["initialized"] == 1
    assert result["reports"] == [{"event": "offline-void-intro-initialized", "map": 100048}]


def test_void_intro_is_configured_after_artifact_preview():
    source = BRIDGE.read_text(encoding="utf-8")
    configure = source[source.index("function configure(game){"):]
    assert configure.index("configureOfflineArtifactPreview(game);") < configure.index("configureOfflineVoidIntro(game);") < configure.index("createNativeSaveStore(game);")
