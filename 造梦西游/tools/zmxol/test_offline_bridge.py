"""用 native/文件操作替身验证生产脚本契约，不替代 Android/native 集成验证。"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest


BRIDGE = Path(__file__).with_name("offline_bridge.js")
NODE_CHECK = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({
  Process: {findModuleByName: () => null},
  Module: {getExportByName: () => null},
  Interceptor: {attach: () => {}},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.serializedInput = fs.readFileSync(0, 'utf8');
const result = vm.runInContext(`
  const input = JSON.parse(serializedInput);
  const before = JSON.stringify(input);
  let result;
  try {
    const keys = validateSaveUpdate(input);
    const repeatedKeys = validateSaveUpdate(input);
    result = {accepted: true, keys, repeatedKeys};
  } catch (error) {
    result = {accepted: false, error: error.message};
  }
  result.unchanged = before === JSON.stringify(input);
  result.input = input;
  result;
`, context);
process.stdout.write(JSON.stringify(result));
"""
NODE_WIRE_CHECK = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const hooks = new Map(), replacements = new Map(), memory = new Map(), values = new Map(), writes = [], notifications = [], reports = [];
let nextString = 0x10000, captures = 0, reads = 0, diskWrites = 0;
let nativeLotteryCalls = 0, nativeOtherCalls = 0;
let nativeAddCalls = 0, snapshotCalls = 0, randomCalls = 0;
const entryCalls = [], factoryValues = [], castCalls = [], addCalls = [], retained = [], released = [], destroyed = [];
let pendingDisk = '', persisted = null, captureSource;
let diskText = '{"roledata":{"player":{"roleid":1},"role":{"rolelv":1}},"bag":{"spiritcount":2000}' +
  (input.nativePoint === undefined ? '' : ',"point":' + input.nativePoint) + '}';
if (input.baseline !== undefined) diskText = JSON.stringify(input.baseline);
// 保留数字原文，模拟 JsonCpp writer 的 int64 精度；合并规则仍由生产 capture 执行。
const parseValue = text => JSON.parse(text, (_key, value, context) =>
  typeof value === 'number' ? JSON.rawJSON(context.source) : value);
const count = value => ({toNumber: () => value});
function pointer(address) {
  return {
    address, add: offset => pointer(address + offset), isNull: () => address === 0,
    sub: offset => pointer(address - offset), readU64: () => count(memory.get(address)),
    toInt32: () => address, toUInt32: () => address >>> 0, toString: () => '0x' + address.toString(16), readPointer: () => memory.get(address),
    equals: other => address === other.address,
    readU32: () => input.badFingerprint === address ? 0 : ({
      0x29b9468: 0xd10743ff, 0x29b946c: 0xd10183ff, 0x2d4053c: 0xd10dc3ff, 0x2d40540: 0xb001d1a1,
      0x2fedf74: 0xd12843ff, 0x2fedf78: 0xd101c3ff, 0x3c6b750: 0xd101c3ff, 0x3c6b754: 0x52800001,
      0x4ffd82c: 0xa9ba7bfd, 0x4ffd830: 0x52800209, 0x2d41900: 0xd10503ff, 0x2d41904: 0xeb02001f,
      0x4e13d28: 0xd10043ff, 0x4e13d2c: 0xa9007bf3, 0x4e13da8: 0xd10043ff, 0x4e13dac: 0xa9007bf3,
      0x29839d4: 0xd10243ff, 0x29839d8: 0x52800003,
      0x2afba4c: 0xd10703ff, 0x2afba50: 0xd10183ff,
      0x2fe924c: 0xd100c3ff, 0x2fe9250: 0xa9015bf5, 0x2fea720: 0xd10143ff, 0x2fea724: 0xa90053f3,
      0x2ab9290: 0xd10483ff, 0x2ab9294: 0xa9036bf9,
      0x3c85cac: 0xd10443ff, 0x3c85cb0: 0x6d04a7e8, 0x3d293b8: 0xd101c3ff, 0x3d293bc: 0xa90053f3,
      0x3c93dd4: 0xd10183ff, 0x3c93dd8: 0xd2800101, 0x3a0c618: 0xd10cc3ff, 0x3a0c61c: 0xb0016b42,
      0x2c1ab40: 0xf001dac2, 0x2c1ab44: 0xd10443ff, 0x2c1348c: 0xd10083ff, 0x2c13490: 0xa90053f3,
      0x2fecd6c: 0xd10083ff, 0x2fecd70: 0xa90053f3, 0x2fe19a4: 0xd10103ff, 0x2fe19a8: 0xd0012141,
      0x2fe1a98: 0xd10143ff, 0x2fe1a9c: 0xa90053f3,
    })[address] ?? memory.get(address),
    writeU32: value => memory.set(address, value),
    readUtf8String: () => memory.get(address),
    writeU8: value => writes.push({address, value}),
    writeS64: value => writes.push({address, value}),
  };
}
function string(text) {
  const result = pointer(nextString); nextString += 0x10000;
  memory.set(result.address, text); return result;
}
function reference(root, key, create = false) {
  if (create && values.get(root.address).value == null) values.get(root.address).value = {};
  const object = values.get(root.address).value, name = key.readUtf8String(), result = string('');
  values.set(result.address, {get value() { return object[name] ?? null; }, set value(value) { object[name] = value; }});
  return result;
}
function NativeFunction(address) {
  return (...args) => {
    if (address === '__android_log_write') { reports.push(JSON.parse(args[2].readUtf8String())); return 0; }
    if (address === 'strlen') return {toNumber: () => args[0].readUtf8String().length};
    if (address.address === 0x3d295b8) return input.nativeStore ? Object.hasOwn(values.get(args[0].address).value, args[1].readUtf8String()) : input.hasSavedata;
    if (address.address === 0x3d2957c) return input.nativeStore ? reference(...args) : pointer(0x3000);
    if (address.address === 0x3d2c370) return reference(args[0], args[1], true);
    if (address.address === 0x3d2a33c) { destroyed.push(args[0].address); return; }
    if ([0x3d28344, 0x3d23f04, 0x211e004, 0x3d1f05c, 0x3d1e598].includes(address.address)) return;
    if (address.address === 0x3d27110) {
      values.set(args[3].address, {value: parseValue(args[1].readUtf8String())}); return 1;
    }
    if (address.address === 0x3d2ab7c || address.address === 0x3d2b1d0) {
      const value = parseValue(JSON.stringify(values.get(args[1].address).value));
      if (address.address === 0x3d2ab7c) values.set(args[0].address, {value});
      else values.get(args[0].address).value = value;
      return args[0];
    }
    if (address.address === 0x3d1f08c) {
      const text = JSON.stringify(values.get(args[1].address).value), bytes = string(text);
      memory.set(args[0].address + 8, bytes); memory.set(bytes.address - 0x18, text.length); return;
    }
    if (address.address === 0x2a7da54) {
      writes.push({address: args[0].address, body: args[1].readUtf8String()}); return;
    }
    if (address.address === 0x29839d4) { entryCalls.push(args.map(arg => arg.address ?? arg)); return; }
    if (address.address === 0x3c6b750) {
      factoryValues.push({address: args[0].address, value: JSON.parse(JSON.stringify(values.get(args[0].address).value)),
        phase: JSON.parse(persisted ?? diskText)._offline_lottery?.phase, diskWrites});
      return pointer(input.factoryNull ? 0 : 0x7200);
    }
    if (address.address === 0x4ffd82c) { castCalls.push(args.map(arg => arg.address ?? arg)); return pointer(input.castNull ? 0 : 0x7300); }
    if (address.address === 0x4e13d28) { retained.push(args[0].address); return; }
    if (address.address === 0x4e13da8) { released.push(args[0].address); return; }
    if (address.address === 0x2d41900) {
      addCalls.push(args.map(arg => arg.address ?? arg));
      if (input.addFails) return false;
      nativeAddCalls++; return true;
    }
    if (address.address === 0x29b9468) {
      const tag = args[1].add(0x38).readPointer().add(0x18).readPointer().readUtf8String();
      if (tag !== 'REQUEST_LEVEL_LOTTERY') { nativeOtherCalls++; return; }
      nativeLotteryCalls++;
      replacements.get(0x4e5f714).call({returnAddress: pointer(0x29b9720)}, pointer(0x7000), string('REQUEST_DATA_HANDLED'), args[1]);
      replacements.get(0x4e5f908).call({returnAddress: pointer(0x29b9734)}, pointer(0x7000), string('GO_ON'));
      return;
    }
    if (address.address === 0x4e5f094 || address.address === 0x2d1f964) return pointer(0x7000);
    if (address.address === 0x4e5f9c4) return;
    if (address.address === 0x4e5f714 || address.address === 0x4e5f908) {
      notifications.push({name: args[1].readUtf8String(), phase: persisted === null ? null : JSON.parse(persisted)._offline_lottery?.phase}); return;
    }
    if (address.address === 0x30d0b74) {
      memory.set(0x8000, pointer(0x9000)); memory.set(0x9058, pointer(0xdeadbeef)); return pointer(0x8000);
    }
    if (address.address === 0xdeadbeef) return {toString: () => input.recoveryRuns && nativeAddCalls === 0 ? input.nativePoint ?? '0' : input.nativePointAfter ?? input.nativePoint ?? '0'};
    if (memory.get(address.address) === 0xaa0103e8 && memory.get(address.address + 4) === 0xd61f0040) {
      snapshotCalls++;
      if (input.snapshotFails || snapshotCalls === input.snapshotFailAt) throw new Error('Test native snapshot failure');
      if (args[2].address !== 0x2d4053c) throw new Error('Wrong native serializer target');
      const bag = input.recoveryRuns && nativeAddCalls === 0 ? input.nativeBagBefore : input.nativeBagAfter;
      values.set(args[1].address, {value: parseValue(JSON.stringify(bag))}); return;
    }
    throw new Error('Unexpected native call in callback contract test');
  };
}
function SystemFunction(name) {
  return (...args) => {
    if (name === 'open') {
      if (args[1] & 0x200) pendingDisk = '';
      return input.noBaseline && args[0].readUtf8String().endsWith('/offline-save.json') ? {value: -1, errno: 2} : {value: args[1] & 0x4000 ? 8 : 7};
    }
    if (name === 'close') return {value: 0};
    if (name === 'fsync') return input.failDirectorySync && args[0] === 8 ? {value: -1, errno: 5} : {value: 0};
    if (name === 'read') {
      if (reads++) return {value: count(0)};
      memory.set(args[1].address, diskText); return {value: count(diskText.length)};
    }
    if (name === 'write') {
      diskWrites++;
      if (diskWrites === input.failWriteAt) return {value: count(-1), errno: 5};
      pendingDisk += args[1].readUtf8String().slice(0, args[2]); return {value: count(args[2])};
    }
    if (name === 'rename') { persisted = pendingDisk; return {value: 0}; }
    throw new Error('Unexpected filesystem call in store contract test');
  };
}
const context = vm.createContext({
  Process: {findModuleByName: () => null, pageSize: 4096},
  Module: {getExportByName: (_module, name) => name},
  Interceptor: {attach: (address, callbacks) => hooks.set(address.address ?? address, callbacks), replace: (address, callback) => replacements.set(address.address, callback)},
  Memory: {allocUtf8String: string, alloc: () => string(''), protect: () => true, patchCode: (address, _size, apply) => apply(address)}, NativeFunction, SystemFunction, ptr: pointer,
  NativeCallback: function (callback) { return callback; },
  console: {log: () => {}},
  Math: Object.assign(Object.create(Math), {random: () => {
    const index = randomCalls++;
    return input.randomValues?.[index] ?? input.random ?? Math.random();
  }}),
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const game = {base: pointer(0)};
memory.set(0x67784d0, pointer(input.sourceTypeNull ? 0 : 0x7400)); memory.set(0x677f968, pointer(input.itemTypeNull ? 0 : 0x7500));
let store = input.nativeStore ? context.createNativeSaveStore(game) : {
  healthy: () => true, exists: () => true,
  capture: () => { captures++; if (input.captureFails) throw new Error('Test storage failure'); },
};
if (input.captureUpdate) {
  const source = string(''); values.set(source.address, {value: parseValue(JSON.stringify(input.captureUpdate))});
  for (let count = 0; count < (input.captureCount ?? 1); count++) store.capture(source, false);
  captureSource = JSON.stringify(values.get(source.address).value);
}
if (input.lotteryActions) {
  const results = [], nativeValue = value => {
    const result = string(''); values.set(result.address, {value: parseValue(JSON.stringify(value))}); return result;
  };
  for (const action of input.lotteryActions) {
    try {
      let result;
      if (action.kind === 'create') store.capture(nativeValue(action.savedata), true);
      else if (action.kind === 'begin') result = store.beginLottery(action.levelid);
      else if (action.kind === 'leave') result = JSON.parse(store.captureOrdinaryLeave(nativeValue(action.savedata), action.request));
      else if (action.kind === 'draw') result = JSON.parse(store.prepareLottery(action.request));
      else if (action.kind === 'commit') store.commitLotteryReward(nativeValue(action.bag), String(action.point));
      else if (action.kind === 'reload') { diskText = persisted; reads = 0; store = context.createNativeSaveStore(game); }
      else throw new Error('Unknown test action');
      results.push({kind: action.kind, result});
    } catch (error) { results.push({kind: action.kind, error: error.message}); }
  }
  process.stdout.write(JSON.stringify({results, stored: JSON.parse(store.text()), role: JSON.parse(store.roleResponse()),
    healthy: store.healthy(), diskWrites, persisted: persisted === null ? null : JSON.parse(persisted)}));
  process.exit(0);
}
try { context.configureRoleWire(game, store); }
catch (error) { process.stdout.write(JSON.stringify({configurationError: error.message, factoryValues, diskWrites})); process.exit(0); }
if (input.recoveryRuns) {
  const roleReturns = [];
  if (input.failBeforeResponse) store.blockLottery();
  for (const run of input.recoveryRuns) {
    if (run.reload) {
      diskText = persisted ?? diskText; reads = 0;
      nativeAddCalls = 0;
      store = context.createNativeSaveStore(game); context.configureRoleWire(game, store);
    }
    const invocation = {returnAddress: pointer(run.caller ?? 0x2ff7130)};
    let returned = run.returned ?? 1;
    hooks.get(0x2fedf74).onEnter.call(invocation, [pointer(0), pointer(0)]);
    hooks.get(0x2fedf74).onLeave.call(invocation, {toUInt32: () => returned >>> 0, replace: value => {returned = value.toUInt32();}});
    roleReturns.push(returned);
  }
  process.stdout.write(JSON.stringify({roleReturns, factoryValues, castCalls, addCalls, retained, released, destroyed, snapshotCalls, randomCalls,
    notifications, reports, diskWrites, healthy: store.healthy(), stored: JSON.parse(store.text()),
    persisted: JSON.parse(persisted ?? diskText), role: JSON.parse(store.roleResponse())}));
  process.exit(0);
}
if (input.entryAttempts) {
  for (const levelid of input.entryAttempts) {
    const root = string(''), tag = string('REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER'), request = string(''), raw = string('');
    values.set(root.address, {value: parseValue(JSON.stringify({levelid, mode: 2, rid: '10001'}))});
    memory.set(request.address + 0x40, tag); memory.set(raw.address + 0x18, request);
    hooks.get(0x2ab7c78).onEnter([pointer(0), pointer(37), root, pointer(0), tag]);
    hooks.get(0x2ab75d8).onEnter([pointer(0), pointer(0), raw]);
    replacements.get(0x29839d4)(pointer(0x7100), levelid, 9);
  }
  process.stdout.write(JSON.stringify({entryCalls, reports, diskWrites, healthy: store.healthy(), stored: JSON.parse(store.text()),
    persisted: JSON.parse(persisted ?? diskText)}));
  process.exit(0);
}
if (input.roleInfoQueries) {
  const requests = input.roleInfoQueries.map(query => {
    const root = string(''), tag = string(query.tag ?? 'REQUEST_ROLE_INFO_2'), request = string(''), raw = string('');
    values.set(root.address, {value: parseValue(JSON.stringify(query.body))});
    memory.set(request.address + 0x40, tag); memory.set(raw.address + 0x18, request);
    const invocation = {};
    if (!query.skipPrepare) {
      hooks.get(0x2ab9290).onEnter.call(invocation, [pointer(0), pointer(query.command ?? 168), root, pointer(0), tag]);
      hooks.get(0x2ab9290).onLeave.call(invocation, query.nullRequest ? pointer(0) : request);
    }
    return {request, raw};
  });
  if (input.failBeforeResponse) store.blockLottery();
  const packets = [];
  for (const index of input.responseOrder ?? requests.map((_request, index) => index)) {
    const {request, raw} = requests[index], start = writes.length;
    hooks.get(0x2ab75d8).onEnter([pointer(0), pointer(0), raw]);
    const converter = [pointer(0), request, pointer(0), pointer(1), pointer(1)];
    hooks.get(0x2a97c18).onEnter(converter);
    packets.push({index, writes: writes.slice(start), decode: converter[4].toInt32()});
  }
  process.stdout.write(JSON.stringify({packets, diskWrites, captures, stored: store.exists() ? JSON.parse(store.text()) : null}));
  process.exit(0);
}
if (input.wireLottery) {
  const packets = [], levelid = input.levelid ?? 700002;
  function fire(command, tagText, body) {
    const root = string(''), tag = string(tagText), request = string(''), raw = string('');
    values.set(root.address, {value: parseValue(JSON.stringify(body))});
    memory.set(request.address + 0x40, tag); memory.set(raw.address + 0x18, request);
    const start = writes.length;
    hooks.get(0x2ab7c78).onEnter([pointer(0), pointer(command), root, pointer(0), tag]);
    hooks.get(0x2ab75d8).onEnter([pointer(0), pointer(0), raw]);
    const packet = {tag: tagText, writes: writes.slice(start)}; packets.push(packet); return packet;
  }
  function response(tag, body) {
    const result = string(''), tagObject = string(''), bodyObject = string('');
    memory.set(tagObject.address + 0x18, string(tag)); memory.set(bodyObject.address + 0x18, string(body));
    memory.set(result.address + 0x38, tagObject); memory.set(result.address + 0x30, bodyObject); return result;
  }
  fire(37, 'REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER', {levelid, mode: 2, rid: '10001'});
  if (!input.skipPostEnter) replacements.get(0x29839d4)(pointer(0), levelid, 0);
  fire(38, 'REQUEST_LEAVE_LEVEL', {levelid, result: true, battleresult: 1, savedata: {bag: {spiritcount: 2080}}});
  const draw = {levelid, removed: input.removed ?? [0, 2], rid: '10001'};
  const packet = fire(39, 'REQUEST_LEVEL_LOTTERY', draw);
  const body = packet.writes.find(write => write.body !== undefined)?.body ?? '';
  const nativeResponse = response('REQUEST_LEVEL_LOTTERY', input.mismatchBody ? '{"code":1000,"reward":[]}' : body);
  replacements.get(0x29b9468)(pointer(0x7100), nativeResponse);
  if (input.repeat) {
    fire(39, 'REQUEST_LEVEL_LOTTERY', draw);
    replacements.get(0x29b9468)(pointer(0x7100), nativeResponse);
  }
  if (input.otherTag) replacements.get(0x29b9468)(pointer(0x7100), response('OTHER_REQUEST', '{}'));
  process.stdout.write(JSON.stringify({packets, nativeLotteryCalls, nativeOtherCalls, notifications, reports,
    healthy: store.healthy(), stored: JSON.parse(store.text()), persisted: persisted === null ? null : JSON.parse(persisted)}));
  process.exit(0);
}
const raw = pointer(0x1000), request = pointer(0x2000), tag = string(input.tag);
memory.set(0x1018, request); memory.set(0x2040, tag);
if (input.send) {
  if (input.nativeStore && input.requestBody !== undefined) values.set(0x3000, {value: parseValue(JSON.stringify(input.requestBody))});
  hooks.get(0x2ab7c78).onEnter([pointer(0), pointer(input.command), pointer(0x3000), pointer(0), tag]);
}
let callbackError;
try { hooks.get(0x2ab75d8).onEnter([pointer(0), pointer(0), raw]); }
catch (error) { callbackError = error.message; }
const converterArgs = [pointer(0), request, pointer(0), pointer(1), pointer(1)];
hooks.get(0x2a97c18).onEnter(converterArgs);
process.stdout.write(JSON.stringify({writes, captures, callbackError, diskWrites, persisted, captureSource,
  stored: input.nativeStore && store.exists() ? store.text() : undefined, decode: converterArgs[4].toInt32(),
  healthy: input.nativeStore ? store.healthy() : undefined,
  requestSource: input.requestBody === undefined ? undefined : JSON.stringify(values.get(0x3000).value)}));
"""
NODE_MASK_CHECK = r"""
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8')), hooks = new Map(), logs = [];
const base = 0x100000000, entry = base + 0x2996e2c;
const fingerprint = input.fingerprint ?? [0xd10283ff, 0xa90473fb];
function pointer(address) {
  return {
    address, add: offset => pointer(address + offset), equals: other => address === other.address,
    toInt32: () => address | 0, toUInt32: () => address >>> 0,
    readU32() {
      if (address === entry) return fingerprint[0];
      if (address === entry + 4) return fingerprint[1];
      if (address === base + 0x2ebbf98) throw new Error('Stopped after victory mask hook');
      throw new Error('Unexpected native read in leave mask contract test');
    },
  };
}
const context = vm.createContext({
  Process: {findModuleByName: () => null},
  Module: {getExportByName: (_module, name) => name},
  Interceptor: {attach: (address, callbacks) => hooks.set(address.address ?? address, callbacks)},
  Memory: {allocUtf8String: text => text}, ptr: pointer,
  NativeFunction: function (address) {
    if (address !== '__android_log_write') throw new Error('Unexpected native function in leave mask contract test');
    return (_priority, _tag, text) => logs.push(JSON.parse(text));
  },
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
let configurationError;
try {
  const game = {base: pointer(base)};
  if (input.configure) context.configure(game);
  else context.configureFirstLevelVictorySaveMask(game);
} catch (error) { configurationError = error.message; }
const args = [pointer(0x1234), pointer(input.level ?? 700002), pointer(input.victory ?? 1),
  pointer(input.reason ?? 0), pointer(input.mask ?? 0xf4), pointer(0x5678)];
const before = args.map(arg => arg.address), hook = hooks.get(entry);
if (hook) hook.onEnter.call({returnAddress: pointer(base + (input.caller ?? 0x4b92bf8))}, args);
process.stdout.write(JSON.stringify({registered: Boolean(hook), configurationError, before,
  after: args.map(arg => arg.address), logs}));
"""
NODE_LOTTERY_CHECK = r"""
const fs = require('node:fs'), vm = require('node:vm'), input = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = vm.createContext({
  Process: {findModuleByName: () => null}, Module: {getExportByName: () => null}, Interceptor: {attach: () => {}},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
vm.runInContext('Math.random = () => ' + JSON.stringify(input.random ?? 0), context);
const before = JSON.stringify(input);
let result;
try { result = {pool: context.offlineLotteryPool(input.levelid), reward: context.drawOfflineLottery(input.levelid, input.removed)}; }
catch (error) { result = {error: error.message}; }
result.unchanged = before === JSON.stringify(input);
process.stdout.write(JSON.stringify(result));
"""


@pytest.fixture(scope="module")
def run_production_js():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable for production JavaScript validation")

    async def invoke(script, payload):
        process = await asyncio.create_subprocess_exec(
            node, "-e", script, str(BRIDGE),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, error = await process.communicate(json.dumps(payload).encode())
        assert process.returncode == 0, error.decode()
        return json.loads(output)

    return lambda script, payload: asyncio.run(invoke(script, payload))


@pytest.fixture(scope="module")
def check_update(run_production_js):
    return lambda payload: run_production_js(NODE_CHECK, payload)


def test_accepts_first_battle_snapshots_without_reapplying_spirit_reward(check_update):
    payload = {
        "roledata": {"player": {"roleid": 1}, "role": {"rolelv": 1, "roleexp": 18}},
        "bag": {"spiritcount": 30, "bagsize": 72, "item": []},
        "pet": {"bagsize": 8, "petinfo": [], "maxglobalpetid": 4399},
        "mire": {"storytask": []},
        "level": {"phfiel2": 0},
        "eggdata": {},
        "novice_boot_task_progress": {},
        "interaction_data": {"get_base_item_list": {"1": [{"A2": 503031, "A4": 30}]}},
    }
    result = check_update(payload)
    assert result["accepted"], result
    assert set(result["keys"]) == set(payload)
    assert result["repeatedKeys"] == result["keys"]
    assert result["unchanged"] and result["input"] == payload
    assert result["input"]["bag"]["spiritcount"] == 30


def test_accepts_partial_snapshot_without_events(check_update):
    payload = {"bag": {"spiritcount": 90}, "eggdata": {}, "novice_boot_task_progress": {}}
    result = check_update(payload)
    assert result["accepted"], result
    assert result["unchanged"] and result["input"] == payload


def test_accepts_spirit_earned_then_spent_before_save(check_update):
    payload = {
        "bag": {"spiritcount": 1900},
        "interaction_data": {"get_base_item_list": {"1": [{"A2": 503031, "A4": 2000}]}},
    }
    result = check_update(payload)
    assert result["accepted"], result
    assert result["unchanged"] and result["input"]["bag"]["spiritcount"] == 1900


@pytest.mark.parametrize("fight_time", [68, 0, 9007199254740991], ids=["recorded-68", "zero", "safe-max"])
def test_accepts_nonnegative_safe_integer_fight_time(check_update, fight_time):
    payload = {"interaction_data": {"fight_time": fight_time}}
    result = check_update(payload)
    assert result["accepted"], result
    assert result["unchanged"] and result["input"] == payload


@pytest.mark.parametrize("fight_time", ["68", -1, 0.5, None, True, [], {}, 9007199254740992], ids=[
    "string", "negative", "fraction", "null", "boolean", "array", "object", "overflow",
])
def test_rejects_invalid_fight_time(check_update, fight_time):
    payload = {"interaction_data": {"fight_time": fight_time}}
    result = check_update(payload)
    assert not result["accepted"] and result["error"] == "Invalid offline fight time"
    assert result["unchanged"] and result["input"] == payload


@pytest.mark.parametrize("count,pet", [
    (0, None),
    (1, {"petinfo": [], "bagsize": 8, "maxglobalpetid": 4399}),
    (2147483647, {"petinfo": [], "bagsize": 4294967295, "maxglobalpetid": 4294967295}),
], ids=["zero-without-snapshot", "complete-empty-snapshot", "native-integer-limits"])
def test_accepts_pet_catch_count_with_complete_snapshot(check_update, count, pet):
    payload = {"interaction_data": {"catch_pet": count}}
    if pet is not None:
        payload["pet"] = pet
    result = check_update(payload)
    assert result["accepted"], result
    assert result["repeatedKeys"] == result["keys"]
    assert result["unchanged"] and result["input"] == payload


@pytest.mark.parametrize("count", ["1", -1, 0.5, None, True, [], {}, 2147483648], ids=[
    "string", "negative", "fraction", "null", "boolean", "array", "object", "int32-overflow",
])
def test_rejects_invalid_pet_catch_count(check_update, count):
    result = check_update({"interaction_data": {"catch_pet": count}})
    assert not result["accepted"] and result["error"] == "Invalid offline pet catch count"
    assert result["unchanged"]


@pytest.mark.parametrize("pet", [
    None, {}, {"petinfo": {}, "bagsize": 8, "maxglobalpetid": 4399},
    {"petinfo": [], "maxglobalpetid": 4399},
    {"petinfo": [], "bagsize": -1, "maxglobalpetid": 4399},
    {"petinfo": [], "bagsize": 4294967296, "maxglobalpetid": 4399},
    {"petinfo": [], "bagsize": True, "maxglobalpetid": 4399},
    {"petinfo": [], "bagsize": 8},
    {"petinfo": [], "bagsize": 8, "maxglobalpetid": "4399"},
    {"petinfo": [], "bagsize": 8, "maxglobalpetid": 0.5},
    {"petinfo": [], "bagsize": 8, "maxglobalpetid": 4294967296},
], ids=["missing", "empty", "invalid-list", "missing-size", "negative-size", "size-overflow", "boolean-size",
        "missing-id", "string-id", "fractional-id", "id-overflow"])
def test_pet_catch_requires_same_update_complete_pet_snapshot(check_update, pet):
    payload = {"interaction_data": {"catch_pet": 1}}
    if pet is not None:
        payload["pet"] = pet
    result = check_update(payload)
    assert not result["accepted"] and result["error"] == "Offline pet catch is missing its complete pet snapshot"
    assert result["unchanged"] and result["input"] == payload


def test_unknown_interaction_error_lists_keys_without_values(check_update):
    payload = {"interaction_data": {
        "fight_time": 68, "unknown_event": "value-must-not-be-logged", "another_event": {"detail": 123},
    }}
    result = check_update(payload)
    assert not result["accepted"]
    assert result["error"] == "Unsupported offline interaction: unknown_event,another_event"
    assert result["unchanged"] and result["input"] == payload


@pytest.mark.parametrize("marker", [{}, {"is_saved_from": 1}], ids=["absent", "numeric-one"])
def test_accepts_optional_save_source_marker(check_update, marker):
    payload = {"bag": {"spiritcount": 1900}, **marker}
    result = check_update(payload)
    assert result["accepted"], result
    assert result["unchanged"] and result["input"] == payload


@pytest.mark.parametrize("marker", [0, 2, "1", True, None, {}, []], ids=[
    "zero", "other-number", "string", "boolean", "null", "object", "array",
])
def test_rejects_invalid_save_source_marker(check_update, marker):
    payload = {"bag": {}, "is_saved_from": marker}
    result = check_update(payload)
    assert not result["accepted"] and result["error"] == "Invalid offline save source marker"
    assert result["unchanged"] and result["input"] == payload


@pytest.mark.parametrize("payload", [
    None,
    [],
    {"unknown_module": {}},
    {"roledata": None},
    {"bag": []},
    {"pet": "invalid"},
    {"mire": {"storytask": {}}},
    {"eggdata": []},
    {"novice_boot_task_progress": []},
    {"interaction_data": []},
    {"interaction_data": {"get_base_item_list": []}},
], ids=[
    "null-update", "array-update", "unknown-module", "null-role", "array-bag",
    "string-pet", "object-story-tasks", "array-egg-events", "array-novice-events",
    "array-interaction", "array-item-groups",
])
def test_rejects_malformed_save_structures(check_update, payload):
    result = check_update(payload)
    assert not result["accepted"], result
    assert result["unchanged"] and result["input"] == payload


@pytest.mark.parametrize("payload", [
    {"eggdata": {"new": 1}},
    {"novice_boot_task_progress": {"new": 1}},
    {"mire": {"unknown_event": []}},
    {"interaction_data": {"unknown_event": []}},
    {"interaction_data": {"get_base_item_list": {"1": [{"A2": 503031, "A4": 30}]}}},
    {"bag": {"spiritcount": -1}, "interaction_data": {"get_base_item_list": {"1": [{"A2": 503031, "A4": 30}]}}},
    {"bag": {"spiritcount": 30}, "interaction_data": {"get_base_item_list": {"1": [{"A2": 503032, "A4": 30}]}}},
    {"bag": {"spiritcount": 30}, "interaction_data": {"get_base_item_list": {"1": [{"A2": 503031, "A4": -1}]}}},
    {"bag": {"spiritcount": 30}, "interaction_data": {"get_base_item_list": {"1": [{"A2": 503031, "A4": 0.5}]}}},
], ids=[
    "nonempty-egg-event", "nonempty-novice-event", "unknown-mire-event",
    "unknown-interaction", "missing-bag", "reward-not-in-bag", "other-item",
    "negative-reward", "fractional-reward",
])
def test_rejects_unimplemented_events_and_unbacked_rewards(check_update, payload):
    result = check_update(payload)
    assert not result["accepted"], result
    assert result["unchanged"] and result["input"] == payload


def test_enter_level_callback_returns_required_numeric_state_in_plaintext(run_production_js):
    result = run_production_js(NODE_WIRE_CHECK, {"tag": "REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER"})
    body = json.loads(result["writes"][0]["body"])
    assert body["code"] == 1000 and type(body["state"]) is int and body["state"] == 0
    assert result["writes"][1:] == [{"address": 0x1020, "value": 1}, {"address": 0x1058, "value": 200}]
    assert result["decode"] == 0 and result["captures"] == 0


@pytest.mark.parametrize("tag,command", [("REQUEST_SAVE_DATA", 4), ("REQUEST_CREATE_ROLE", 65)])
@pytest.mark.parametrize("send,has_savedata,capture_fails,captures", [
    (False, False, False, 0),
    (True, False, False, 0),
    (True, True, True, 1),
], ids=["unprepared", "missing-savedata", "storage-failure"])
def test_save_callback_never_acknowledges_without_successful_capture(
    run_production_js, tag, command, send, has_savedata, capture_fails, captures,
):
    result = run_production_js(NODE_WIRE_CHECK, {
        "tag": tag, "command": command, "send": send,
        "hasSavedata": has_savedata, "captureFails": capture_fails,
    })
    assert result["captures"] == captures
    assert result.get("callbackError") is None
    assert result["writes"] == []


@pytest.mark.parametrize("tag,command", [("REQUEST_SAVE_DATA", 4), ("REQUEST_CREATE_ROLE", 65)])
def test_save_callback_acknowledges_after_successful_capture(run_production_js, tag, command):
    result = run_production_js(NODE_WIRE_CHECK, {
        "tag": tag, "command": command, "send": True, "hasSavedata": True,
    })
    assert result["captures"] == 1
    assert json.loads(result["writes"][0]["body"])["code"] == 1000
    assert result["writes"][1:] == [{"address": 0x1020, "value": 1}, {"address": 0x1058, "value": 200}]


@pytest.mark.parametrize("native_point", ["0", "71", "9007199254740993"])
def test_point_response_preserves_native_writer_value(run_production_js, native_point):
    result = run_production_js(NODE_WIRE_CHECK, {
        "tag": "REQUEST_POINT", "nativeStore": True, "nativePoint": native_point,
    })
    assert result.get("callbackError") is None
    assert result["writes"][0]["body"] == '{"code":1000,"point":' + native_point + '}'
    assert result["writes"][1:] == [{"address": 0x1020, "value": 1}, {"address": 0x1058, "value": 200}]
    assert result["decode"] == 0 and result["captures"] == 0 and result["diskWrites"] == 0


@pytest.mark.parametrize("no_baseline", [False, True], ids=["missing-point", "missing-profile"])
def test_point_response_does_not_invent_zero_without_snapshot(run_production_js, no_baseline):
    result = run_production_js(NODE_WIRE_CHECK, {
        "tag": "REQUEST_POINT", "nativeStore": True, "noBaseline": no_baseline,
    })
    assert result["writes"] == [] and result["captures"] == 0 and result["diskWrites"] == 0
    assert result.get("callbackError") == (None if no_baseline else "Offline point snapshot is missing")


def test_bulletin_response_has_empty_message_without_reading_or_changing_profile(run_production_js):
    result = run_production_js(NODE_WIRE_CHECK, {"tag": "REQUEST_RECEIVE_BULLETIN"})
    assert result.get("callbackError") is None
    assert result["writes"][0]["body"] == '{"code":1000,"message":""}'
    assert result["writes"][1:] == [{"address": 0x1020, "value": 1}, {"address": 0x1058, "value": 200}]
    assert result["decode"] == 0 and result["captures"] == 0 and result["diskWrites"] == 0


def test_capture_omits_save_source_marker_from_disk_and_role_response(run_production_js):
    update = {"bag": {"spiritcount": 1900}, "is_saved_from": 1}
    result = run_production_js(NODE_WIRE_CHECK, {
        "tag": "REQUEST_ROLE_DATA", "nativeStore": True, "nativePoint": "71", "captureUpdate": update,
    })
    assert result.get("callbackError") is None
    assert result["diskWrites"] == 1 and result["persisted"] == result["stored"]
    stored = json.loads(result["persisted"])
    response = json.loads(result["writes"][0]["body"])
    assert "is_saved_from" not in stored and "is_saved_from" not in response["savedata"]
    assert response["code"] == 1000 and response["savedata"] == stored
    assert stored["bag"] == {"spiritcount": 1900} and stored["point"] == 71
    assert json.loads(result["captureSource"]) == update


@pytest.mark.parametrize("fight_time", [68, 0], ids=["recorded-68", "zero"])
def test_capture_keeps_fight_time_record_without_replaying_rewards(run_production_js, fight_time):
    update = {
        "bag": {"spiritcount": 1900},
        "interaction_data": {
            "fight_time": fight_time,
            "get_base_item_list": {"1": [{"A2": 503031, "A4": 60}]},
        },
    }
    result = run_production_js(NODE_WIRE_CHECK, {
        "tag": "REQUEST_ROLE_DATA", "nativeStore": True, "captureUpdate": update, "captureCount": 2,
    })
    assert result.get("callbackError") is None
    assert result["diskWrites"] == 2 and result["persisted"] == result["stored"]
    stored = json.loads(result["persisted"])
    response = json.loads(result["writes"][0]["body"])
    assert stored["interaction_data"] == update["interaction_data"]
    assert "interaction_data" not in response and "interaction_data" not in response["savedata"]
    assert response["savedata"]["bag"] == stored["bag"] == {"spiritcount": 1900}
    assert json.loads(result["captureSource"]) == update


def test_capture_keeps_pet_snapshot_and_omits_catch_report_from_role_without_reapplying(run_production_js):
    update = {
        "pet": {"petinfo": [], "bagsize": 8, "maxglobalpetid": 4399},
        "interaction_data": {"catch_pet": 1, "fight_time": 68},
    }
    result = run_production_js(NODE_WIRE_CHECK, {
        "tag": "REQUEST_ROLE_DATA", "nativeStore": True, "nativePoint": "71",
        "captureUpdate": update, "captureCount": 2,
    })
    assert result.get("callbackError") is None and result["healthy"]
    assert result["diskWrites"] == 2 and result["persisted"] == result["stored"]
    stored = json.loads(result["persisted"])
    response = json.loads(result["writes"][0]["body"])
    assert stored["interaction_data"] == update["interaction_data"]
    assert response["savedata"]["pet"] == stored["pet"] == update["pet"]
    assert "interaction_data" not in response and "interaction_data" not in response["savedata"]
    assert stored["bag"] == response["savedata"]["bag"] == {"spiritcount": 2000}
    assert stored["point"] == response["savedata"]["point"] == 71
    assert json.loads(result["captureSource"]) == update


@pytest.mark.parametrize("condition,success", [({}, True), ({"missing_pet": True}, False), ({"failWriteAt": 1}, False)],
                         ids=["committed", "missing-snapshot", "disk-failure"])
def test_pet_save_acknowledges_only_after_valid_snapshot_commit(run_production_js, condition, success):
    update = {"interaction_data": {"catch_pet": 1}}
    if not condition.get("missing_pet"):
        update["pet"] = {"petinfo": [], "bagsize": 8, "maxglobalpetid": 4399}
    body = {"savedata": update}
    result = run_production_js(NODE_WIRE_CHECK, {
        "tag": "REQUEST_SAVE_DATA", "command": 4, "send": True, "nativeStore": True,
        "requestBody": body, **condition,
    })
    assert result.get("callbackError") is None and result["healthy"] is success
    assert json.loads(result["requestSource"]) == body
    stored = json.loads(result["stored"])
    if success:
        assert result["writes"][0]["body"] == '{"code":1000}'
        assert result["persisted"] == result["stored"] and result["diskWrites"] == 1
        assert stored["pet"] == update["pet"] and stored["interaction_data"] == update["interaction_data"]
    else:
        assert result["writes"] == [] and result["persisted"] is None
        assert "pet" not in stored and "interaction_data" not in stored
    assert stored["bag"] == {"spiritcount": 2000}


@pytest.mark.parametrize("mask,expected", [
    (0xF4, 0xFF), (0x800001F4, 0x800001FF), (0xFF, 0xFF), (0xFFFFFFFF, 0xFFFFFFFF),
], ids=["missing-snapshots", "preserve-upper-bits", "full-mask", "unsigned-full-mask"])
def test_first_victory_restores_only_snapshot_mask_bits(run_production_js, mask, expected):
    result = run_production_js(NODE_MASK_CHECK, {"mask": mask})
    assert result.get("configurationError") is None and result["registered"]
    expected_args = result["before"].copy()
    expected_args[4] = expected
    assert result["after"] == expected_args


@pytest.mark.parametrize("mismatch", [
    {"caller": 0x4B92BFC}, {"level": 700001}, {"level": 700003},
    {"victory": 0}, {"victory": 2}, {"reason": 1}, {"reason": -1},
], ids=["other-caller", "previous-level", "next-level", "not-victory", "other-victory-flag", "other-reason", "negative-reason"])
def test_leave_mask_is_unchanged_outside_exact_first_victory(run_production_js, mismatch):
    result = run_production_js(NODE_MASK_CHECK, mismatch)
    assert result.get("configurationError") is None and result["registered"]
    assert result["after"] == result["before"] and result["logs"] == []


@pytest.mark.parametrize("fingerprint", [
    [0xD10283FE, 0xA90473FB], [0xD10283FF, 0xA90473FA],
], ids=["first-instruction", "second-instruction"])
def test_configure_rejects_changed_leave_entry_fingerprint(run_production_js, fingerprint):
    result = run_production_js(NODE_MASK_CHECK, {"configure": True, "fingerprint": fingerprint})
    assert result["configurationError"] == "Level leave entry fingerprint mismatch"
    assert not result["registered"] and result["after"] == result["before"]


def test_configure_installs_first_victory_mask_hook_before_other_setup(run_production_js):
    result = run_production_js(NODE_MASK_CHECK, {"configure": True})
    assert result["configurationError"] == "Stopped after victory mask hook"
    assert result["registered"] and result["before"][4] == 0xF4 and result["after"][4] == 0xFF


@pytest.mark.parametrize("random,expected", [(0, 503031), (1 / 3, 502000), (2 / 3, 502001), (0.999, 502001)])
def test_offline_lottery_uses_equal_intervals_and_quantity_one(run_production_js, random, expected):
    result = run_production_js(NODE_LOTTERY_CHECK, {"levelid": 700002, "removed": [], "random": random})
    assert result["pool"] == [{"A2": item, "A4": 1} for item in (503031, 502000, 502001)]
    assert result["reward"] == [{"A2": expected, "A4": 1}] and result["unchanged"]


def test_offline_lottery_excludes_removed_card_indices_without_mutating_input(run_production_js):
    result = run_production_js(NODE_LOTTERY_CHECK, {"levelid": 700002, "removed": [2, 0], "random": 0.999})
    assert result["reward"] == [{"A2": 502000, "A4": 1}] and result["unchanged"]


@pytest.mark.parametrize("removed", [None, {}, ["0"], [True], [-1], [3], [0.5], [0, 0], [0, 1, 2]])
def test_offline_lottery_rejects_invalid_removed_indices(run_production_js, removed):
    result = run_production_js(NODE_LOTTERY_CHECK, {"levelid": 700002, "removed": removed})
    assert result["error"] == "Invalid offline lottery removed indices" and result["unchanged"]


def test_offline_lottery_supports_verified_stackable_recipe_for_700003(run_production_js):
    result = run_production_js(NODE_LOTTERY_CHECK, {"levelid": 700003, "removed": [], "random": 0})
    assert result["pool"] == [{"A2": item, "A4": 1} for item in (502211, 503031, 502000, 502001)]
    assert result["reward"] == [{"A2": 502211, "A4": 1}]


@pytest.mark.parametrize("levelid", [700004, 999999, "700002", None])
def test_offline_lottery_rejects_unverified_levels_and_item_types(run_production_js, levelid):
    result = run_production_js(NODE_LOTTERY_CHECK, {"levelid": levelid, "removed": []})
    assert result["error"] == "Unsupported offline lottery level" and result["unchanged"]


def lottery_actions(levelid=700002):
    return [
        {"kind": "begin", "levelid": levelid},
        {"kind": "leave", "request": {"levelid": levelid, "result": True, "battleresult": 1}, "savedata": {"bag": {"spiritcount": 2080}}},
    ]


@pytest.mark.parametrize("levelid", [700002, 700003])
def test_lottery_leave_persists_round_and_returns_actual_point_with_zero_cost(run_production_js, levelid):
    result = run_production_js(NODE_WIRE_CHECK, {
        "nativeStore": True, "nativePoint": "71", "lotteryActions": lottery_actions(levelid),
    })
    leave = result["results"][1]["result"]
    assert leave["code"] == 1000 and leave["point"] == 71 and leave["discardcost"] == 0
    assert len(leave["list"]) == (3 if levelid == 700002 else 4)
    assert result["persisted"] == result["stored"] and result["stored"]["bag"]["spiritcount"] == 2080
    assert result["stored"]["_offline_lottery"] == {"version": 1, "round": 1, "phase": "offered", "levelid": levelid}
    assert "_offline_lottery" not in result["role"]["savedata"]


def test_lottery_commits_native_snapshot_and_receipt_atomically_then_recovers_without_awarding_twice(run_production_js):
    actions = lottery_actions()
    draw = {"kind": "draw", "request": {"levelid": 700002, "removed": [0, 2]}}
    bag_after = {"spiritcount": 2080, "item": [{"A2": 502000, "A4": 1}]}
    actions += [draw, draw, {"kind": "commit", "bag": bag_after, "point": 71}, {"kind": "reload"}, draw, actions[1]]
    result = run_production_js(NODE_WIRE_CHECK, {"nativeStore": True, "nativePoint": "71", "lotteryActions": actions})
    assert result["results"][2]["result"] == result["results"][3]["result"] == {"code": 1000, "reward": [{"A2": 502000, "A4": 1}]}
    assert result["results"][6]["error"] == "Offline lottery is not available for this round"
    assert result["diskWrites"] == 4 and result["healthy"]
    assert result["stored"] == result["persisted"] and result["stored"]["_offline_lottery"]["phase"] == "committed"
    assert result["role"]["savedata"]["bag"] == result["stored"]["bag"] == bag_after
    assert result["role"]["savedata"]["point"] == 71 and "_offline_lottery" not in result["role"]["savedata"]


def test_lottery_retry_cannot_change_removed_indices_after_reward_selection(run_production_js):
    actions = lottery_actions() + [
        {"kind": "draw", "request": {"levelid": 700002, "removed": [0, 2]}},
        {"kind": "draw", "request": {"levelid": 700002, "removed": [1, 2]}},
    ]
    result = run_production_js(NODE_WIRE_CHECK, {"nativeStore": True, "nativePoint": "0", "lotteryActions": actions})
    assert result["results"][-1]["error"] == "Offline lottery retry changed removed indices"
    assert result["diskWrites"] == 3 and result["stored"]["_offline_lottery"]["reward"] == [{"A2": 502000, "A4": 1}]


@pytest.mark.parametrize("leave_request", [
    {"levelid": 700002, "result": True, "battleresult": 0},
    {"levelid": 700002, "result": False, "battleresult": 1},
    {"levelid": 700002, "result": 1, "battleresult": 1},
])
def test_lottery_rejects_conflicting_leave_victory_fields(run_production_js, leave_request):
    actions = lottery_actions()
    actions[1]["request"] = leave_request
    result = run_production_js(NODE_WIRE_CHECK, {"nativeStore": True, "nativePoint": "0", "lotteryActions": actions})
    assert result["results"][1]["error"] == "Invalid offline leave result"
    assert result["diskWrites"] == 1 and result["stored"]["_offline_lottery"]["phase"] == "entered"


def test_lottery_snapshot_commit_failure_keeps_prior_disk_state_and_blocks_more_rewards(run_production_js):
    actions = lottery_actions() + [
        {"kind": "draw", "request": {"levelid": 700002, "removed": [0, 2]}},
        {"kind": "commit", "bag": {"spiritcount": 2080, "item": [{"A2": 502000, "A4": 1}]}, "point": 0},
        {"kind": "draw", "request": {"levelid": 700002, "removed": [0, 2]}},
    ]
    result = run_production_js(NODE_WIRE_CHECK, {"nativeStore": True, "nativePoint": "0", "failWriteAt": 4, "lotteryActions": actions})
    assert result["results"][3]["error"] == "Offline save write failed: 5"
    assert result["results"][4]["error"] == "Offline lottery storage is unavailable" and not result["healthy"]
    assert result["stored"] == result["persisted"]
    assert result["stored"]["bag"] == {"spiritcount": 2080} and result["stored"]["_offline_lottery"]["phase"] == "drawn"


def test_new_wukong_profile_and_tutorial_leave_preserve_original_save_path(run_production_js):
    profile = {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 1}}, "bag": {"spiritcount": 0}}
    update = {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 2}}, "bag": {"spiritcount": 30}, "mire": {"storytask": []}}
    result = run_production_js(NODE_WIRE_CHECK, {
        "nativeStore": True, "noBaseline": True, "lotteryActions": [
            {"kind": "create", "savedata": profile},
            {"kind": "leave", "request": {"levelid": 700001, "result": True, "battleresult": 1}, "savedata": update},
        ],
    })
    assert result["results"] == [{"kind": "create"}, {"kind": "leave", "result": {"code": 1000}}]
    assert result["diskWrites"] == 2 and result["stored"] == result["persisted"] and result["healthy"]
    assert result["stored"]["roledata"] == update["roledata"] and result["stored"]["bag"] == update["bag"]
    assert result["stored"]["point"] == 0 and "_offline_lottery" not in result["stored"]


def test_unsupported_lottery_preserves_natural_leave_checkpoint_without_issuing_rewards(run_production_js):
    result = run_production_js(NODE_WIRE_CHECK, {
        "nativeStore": True, "nativePoint": "0", "lotteryActions": [
            {"kind": "leave", "request": {"levelid": 700004, "result": True, "battleresult": 1}, "savedata": {"bag": {"spiritcount": 2200}}},
            {"kind": "draw", "request": {"levelid": 700004, "removed": []}},
        ],
    })
    assert result["results"][0]["result"] == {"code": 1000}
    assert result["results"][1]["error"] == "Unsupported offline lottery level"
    assert result["diskWrites"] == 1 and result["stored"] == result["persisted"]
    assert result["stored"]["bag"] == {"spiritcount": 2200} and "_offline_lottery" not in result["stored"]


@pytest.mark.parametrize("levelid,removed,bag_after", [
    (700002, [0, 2], {"spiritcount": 2080, "item": [{"A2": 502000, "A4": 1}]}),
    (700002, [1, 2], {"spiritcount": 2081, "item": []}),
    (700003, [1, 2, 3], {"spiritcount": 2080, "item": [{"A2": 502211, "A4": 1}]}),
], ids=["material", "spirit", "recipe"])
def test_lottery_wire_calls_native_reward_once_and_commits_before_success_notifications(
    run_production_js, levelid, removed, bag_after,
):
    result = run_production_js(NODE_WIRE_CHECK, {
        "nativeStore": True, "nativePoint": "71", "wireLottery": True, "levelid": levelid,
        "removed": removed, "nativeBagAfter": bag_after, "repeat": True, "otherTag": True,
    })
    assert result["nativeLotteryCalls"] == 1 and result["nativeOtherCalls"] == 1 and result["healthy"]
    assert result["stored"] == result["persisted"] and result["stored"]["bag"] == bag_after
    assert result["stored"]["point"] == 71 and result["stored"]["_offline_lottery"]["phase"] == "committed"
    assert result["notifications"] == [
        {"name": name, "phase": "committed"}
        for name in ("REQUEST_DATA_HANDLED", "GO_ON", "REQUEST_DATA_HANDLED", "GO_ON")
    ]
    assert result["packets"][1]["writes"][0]["body"].startswith('{"code":1000,"point":71,"discardcost":0,"list":')
    assert result["packets"][3]["writes"] == []


@pytest.mark.parametrize("failure", [{"snapshotFails": True}, {"failWriteAt": 4}], ids=["native-snapshot", "disk-commit"])
def test_lottery_wire_failure_then_duplicate_never_sends_success_or_applies_again(run_production_js, failure):
    result = run_production_js(NODE_WIRE_CHECK, {
        "nativeStore": True, "nativePoint": "0", "wireLottery": True, "repeat": True,
        "nativeBagAfter": {"spiritcount": 2080, "item": [{"A2": 502000, "A4": 1}]}, **failure,
    })
    assert result["nativeLotteryCalls"] == 1 and not result["healthy"]
    assert result["notifications"] == [] and result["packets"][-1]["writes"] == []
    assert result["stored"] == result["persisted"] and result["stored"]["_offline_lottery"]["phase"] == "drawn"
    assert result["stored"]["bag"] == {"spiritcount": 2080}


@pytest.mark.parametrize("condition", [{"skipPostEnter": True}, {"mismatchBody": True}, {"levelid": 700004}], ids=[
    "no-native-entry", "different-response-body", "unsupported-equipment",
])
def test_lottery_wire_rejects_unprepared_or_mismatched_responses_without_success(run_production_js, condition):
    result = run_production_js(NODE_WIRE_CHECK, {
        "nativeStore": True, "nativePoint": "0", "wireLottery": True,
        "nativeBagAfter": {"spiritcount": 2080}, **condition,
    })
    assert result["nativeLotteryCalls"] == 0 and result["notifications"] == []
    assert result["stored"]["bag"]["spiritcount"] in (2000, 2080)


def test_own_role_info_response_is_minimal_read_only_and_bound_to_request(run_production_js):
    result = run_production_js(NODE_WIRE_CHECK, {
        "nativeStore": True, "nativePoint": "71", "roleInfoQueries": [
            {"body": {"rid": 10001, "cur_power": 123.5}},
            {"body": {"rid": 10002, "cur_power": 123.5}},
        ], "responseOrder": [1, 0],
    })
    other, own = result["packets"]
    assert other["writes"] == [] and other["decode"] == 1
    assert own["writes"][0]["body"] == '{"code":1000}' and own["decode"] == 0
    assert [write["value"] for write in own["writes"][1:]] == [1, 200]
    assert result["diskWrites"] == 0 and result["captures"] == 0
    assert result["stored"]["bag"] == {"spiritcount": 2000} and result["stored"]["point"] == 71


@pytest.mark.parametrize("query", [
    {"body": {"rid": "10001", "cur_power": 0}},
    {"body": {"rid": 10001}},
    {"body": {"rid": 10001, "cur_power": "123"}},
    {"body": {"rid": 10001, "cur_power": None}},
    {"body": {"rid": 10001, "cur_power": 0}, "command": 169},
    {"body": {"rid": 10001, "cur_power": 0}, "tag": "REQUEST_ROLE_INFO"},
    {"body": {"rid": 10001, "cur_power": 0}, "skipPrepare": True},
    {"body": {"rid": 10001, "cur_power": 0}, "nullRequest": True},
])
def test_role_info_leaves_nonlocal_or_unprepared_requests_unchanged(run_production_js, query):
    result = run_production_js(NODE_WIRE_CHECK, {"nativeStore": True, "nativePoint": "0", "roleInfoQueries": [query]})
    assert result["packets"][0]["writes"] == [] and result["packets"][0]["decode"] == 1
    assert result["diskWrites"] == 0 and result["captures"] == 0


@pytest.mark.parametrize("condition", [{"noBaseline": True}, {"failBeforeResponse": True}], ids=["no-profile", "storage-failed"])
def test_role_info_does_not_succeed_without_healthy_local_profile(run_production_js, condition):
    result = run_production_js(NODE_WIRE_CHECK, {
        "nativeStore": True, "nativePoint": "0", "roleInfoQueries": [{"body": {"rid": 10001, "cur_power": 0}}], **condition,
    })
    assert result["packets"][0]["writes"] == [] and result["packets"][0]["decode"] == 1
    assert result["diskWrites"] == 0


def recovery_input(item_id=502000, phase="drawn", levelid=None):
    levelid = levelid or (700003 if item_id == 502211 else 700002)
    pool = [502211, 503031, 502000, 502001] if levelid == 700003 else [503031, 502000, 502001]
    receipt = {"version": 1, "round": 5, "phase": phase, "levelid": levelid}
    if phase in ("drawn", "committed"):
        receipt.update(removed=[index for index, value in enumerate(pool) if value != item_id], reward=[{"A2": item_id, "A4": 1}])
    before = {"spiritcount": 2080, "item": [{"A2": 502000, "A4": 7}, {"A2": 502001, "A4": 4}, {"A2": 502211, "A4": 2}]}
    after = json.loads(json.dumps(before))
    if item_id == 503031:
        after["spiritcount"] += 1
    else:
        next(item for item in after["item"] if item["A2"] == item_id)["A4"] += 1
    return {
        "nativeStore": True, "nativePoint": "71", "recoveryRuns": [{}],
        "baseline": {"roledata": {"player": {"roleid": 1}, "role": {"rolelv": 7}}, "bag": before, "point": 71, "_offline_lottery": receipt},
        "nativeBagBefore": before, "nativeBagAfter": after,
    }


@pytest.mark.parametrize("item_id", [503031, 502000, 502001, 502211])
def test_drawn_recovery_calls_original_factory_cast_add_once_then_commits_before_role_ready(run_production_js, item_id):
    payload = recovery_input(item_id)
    payload["recoveryRuns"] = [{}, {}, {"reload": True}]
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [1, 1, 1] and result["healthy"]
    assert [item["value"] for item in result["factoryValues"]] == [{"A2": item_id, "A4": 1}]
    assert result["castCalls"] == [[0x7200, 0x7400, 0x7500, 0]]
    assert result["addCalls"] == [[0x7000, 0x7300, 0x7000, 0, 1, 0]]
    assert result["retained"] == result["released"] == [0x7200]
    assert result["factoryValues"][0]["address"] in result["destroyed"]
    assert result["diskWrites"] == 1 and result["stored"] == result["persisted"]
    assert result["stored"]["bag"] == payload["nativeBagAfter"] and result["stored"]["point"] == 71
    assert result["stored"]["_offline_lottery"] == {**payload["baseline"]["_offline_lottery"], "phase": "committed"}
    assert "_offline_lottery" not in result["role"]["savedata"] and result["notifications"] == []


@pytest.mark.parametrize("phase", [None, "entered", "committed"])
def test_role_recovery_preserves_absent_unearned_or_completed_receipts_without_awarding(run_production_js, phase):
    payload = recovery_input(phase=phase or "entered")
    if phase is None:
        del payload["baseline"]["_offline_lottery"]
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [1] and result["healthy"]
    assert result["factoryValues"] == result["addCalls"] == [] and result["snapshotCalls"] == 0
    assert result["diskWrites"] == 0 and result["stored"] == payload["baseline"]


@pytest.mark.parametrize("invocation", [{"caller": 0x2ff7134}, {"returned": 0}, {"returned": 256}])
def test_role_recovery_requires_exact_caller_and_original_true_bool(run_production_js, invocation):
    payload = recovery_input()
    payload["recoveryRuns"] = [invocation]
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [invocation.get("returned", 1)]
    assert result["factoryValues"] == [] and result["diskWrites"] == 0
    assert result["stored"] == payload["baseline"] and result["healthy"]


@pytest.mark.parametrize("receipt_change", [
    {"version": 2}, {"round": 0}, {"levelid": 700004}, {"phase": "unknown"},
    {"removed": [0, 0]}, {"removed": [2, 0]}, {"removed": [1, 2]},
    {"reward": [{"A2": 502000, "A4": 2}]}, {"reward": [{"A2": 1301, "A4": 1}]},
    {"extra": 1}, {"phase": "offered"},
])
def test_bad_pending_receipt_blocks_role_ready_without_native_award(run_production_js, receipt_change):
    payload = recovery_input()
    payload["baseline"]["_offline_lottery"].update(receipt_change)
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [0] and not result["healthy"]
    assert result["factoryValues"] == [] and result["diskWrites"] == 0
    assert result["stored"] == payload["baseline"]


@pytest.mark.parametrize("failure", [
    {"factoryNull": True}, {"sourceTypeNull": True}, {"itemTypeNull": True}, {"castNull": True},
    {"addFails": True}, {"snapshotFailAt": 1}, {"snapshotFailAt": 2}, {"failWriteAt": 1},
    {"failBeforeResponse": True}, {"nativePointAfter": "70"},
], ids=["factory", "source-rtti", "item-rtti", "cast", "add", "before-snapshot", "after-snapshot", "save", "unhealthy", "point-change"])
def test_failed_recovery_never_commits_or_retries_in_same_process(run_production_js, failure):
    payload = recovery_input()
    payload.update(failure, recoveryRuns=[{}, {}])
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [0, 0] and not result["healthy"]
    assert result["stored"] == result["persisted"] == payload["baseline"]
    assert len(result["factoryValues"]) <= 1 and len(result["addCalls"]) <= 1
    assert result["retained"] == result["released"] and result["notifications"] == []
    assert all(item["address"] in result["destroyed"] for item in result["factoryValues"])


@pytest.mark.parametrize("snapshot", [
    {"spiritcount": 2080},
    {"spiritcount": 2080, "item": [{"A2": 502000, "A4": 7}]},
    {"spiritcount": 2080, "item": [{"A2": 502000, "A4": 9}]},
    {"spiritcount": 2080, "item": [{"A2": 502000, "A4": "8"}]},
])
def test_recovery_rejects_missing_or_incorrect_native_reward_delta(run_production_js, snapshot):
    payload = recovery_input()
    payload["nativeBagAfter"] = snapshot
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [0] and not result["healthy"] and result["diskWrites"] == 0
    assert result["stored"] == payload["baseline"] and len(result["addCalls"]) == 1


@pytest.mark.parametrize("failure,awards", [({"failWriteAt": 1}, 2), ({"failDirectorySync": True}, 1)])
def test_recovery_restart_uses_actual_durable_receipt_after_commit_error(run_production_js, failure, awards):
    payload = recovery_input()
    payload.update(failure, recoveryRuns=[{}, {}, {"reload": True}])
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [0, 0, 1] and result["healthy"]
    assert len(result["factoryValues"]) == len(result["addCalls"]) == awards
    assert result["stored"] == result["persisted"] and result["stored"]["bag"] == payload["nativeBagAfter"]
    assert result["stored"]["_offline_lottery"]["phase"] == "committed"


@pytest.mark.parametrize("phase", ["offered", "drawn"])
def test_pending_receipt_blocks_store_begin_and_original_native_transition(run_production_js, phase):
    payload = recovery_input(phase=phase)
    del payload["recoveryRuns"]
    direct = run_production_js(NODE_WIRE_CHECK, {**payload, "lotteryActions": [{"kind": "begin", "levelid": 700003}]})
    assert direct["results"][0]["error"] == "Offline lottery reward is pending"
    assert direct["diskWrites"] == 0 and direct["stored"] == payload["baseline"]
    wire = run_production_js(NODE_WIRE_CHECK, {**payload, "entryAttempts": [700002, 700003, 700004]})
    assert wire["entryCalls"] == [] and wire["diskWrites"] == 0 and wire["healthy"]
    assert wire["stored"] == wire["persisted"] == payload["baseline"]
    assert sum(event["event"] == "offline-lottery-entry-blocked-pending" for event in wire["reports"]) == 3


def test_committed_reward_allows_new_round_and_original_tutorial_transition(run_production_js):
    payload = recovery_input(phase="committed")
    del payload["recoveryRuns"]
    result = run_production_js(NODE_WIRE_CHECK, {**payload, "entryAttempts": [700001, 700003]})
    assert result["entryCalls"] == [[0x7100, 700001, 9], [0x7100, 700003, 9]]
    assert result["stored"]["_offline_lottery"] == {"version": 1, "round": 6, "phase": "entered", "levelid": 700003}
    assert result["diskWrites"] == 1 and result["healthy"]


@pytest.mark.parametrize("offset", [0x2FEDF74, 0x3C6B750, 0x4FFD82C, 0x2D41900, 0x4E13D28, 0x4E13DA8, 0x29839D4])
@pytest.mark.parametrize("instruction", [0, 4])
def test_recovery_rejects_mismatched_native_entry_fingerprint(run_production_js, offset, instruction):
    result = run_production_js(NODE_WIRE_CHECK, {**recovery_input(), "badFingerprint": offset + instruction})
    assert result["configurationError"] == f"Lottery recovery native entry fingerprint mismatch: {offset:x}"
    assert result["factoryValues"] == [] and result["diskWrites"] == 0


@pytest.mark.parametrize("levelid,random,item_id", [
    (700002, 0, 503031), (700002, 0.4, 502000), (700002, 0.99, 502001),
    (700003, 0, 502211), (700003, 0.3, 503031), (700003, 0.6, 502000), (700003, 0.99, 502001),
])
def test_offered_recovery_persists_one_full_pool_selection_before_native_award(run_production_js, levelid, random, item_id):
    payload = recovery_input(item_id, phase="offered", levelid=levelid)
    payload.update(random=random, recoveryRuns=[{}, {}, {"reload": True}])
    payload["baseline"]["level"] = {"passed": [700001, 700002, 700003]}
    payload["baseline"]["mire"] = {"storytask": [{"tid": 6000000, "state": 2, "targetprogress": []}]}
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [1, 1, 1] and result["healthy"]
    assert result["randomCalls"] == 1 and result["diskWrites"] == 2
    assert len(result["factoryValues"]) == len(result["addCalls"]) == 1
    assert result["factoryValues"][0]["phase"] == "drawn" and result["factoryValues"][0]["diskWrites"] == 1
    assert result["factoryValues"][0]["value"] == {"A2": item_id, "A4": 1}
    assert result["stored"] == result["persisted"]
    assert result["stored"]["_offline_lottery"] == {
        **payload["baseline"]["_offline_lottery"], "phase": "committed", "removed": [], "reward": [{"A2": item_id, "A4": 1}],
    }
    assert result["stored"]["bag"] == payload["nativeBagAfter"] and result["stored"]["point"] == 71
    for name in ("roledata", "level", "mire"):
        assert result["stored"][name] == payload["baseline"][name]
    assert result["notifications"] == [] and "_offline_lottery" not in result["role"]["savedata"]


def test_offered_recovery_never_awards_when_selection_cannot_be_persisted(run_production_js):
    payload = recovery_input(phase="offered")
    payload.update(random=0.4, failWriteAt=1, recoveryRuns=[{}, {}])
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [0, 0] and not result["healthy"]
    assert result["factoryValues"] == result["addCalls"] == [] and result["snapshotCalls"] == 0
    assert result["stored"] == result["persisted"] == payload["baseline"]
    assert result["randomCalls"] == 1 and result["diskWrites"] == 1


def test_offered_recovery_keeps_fixed_draw_across_failed_award_commit_and_restart(run_production_js):
    payload = recovery_input(phase="offered")
    payload.update(randomValues=[0.4, 0.99], failWriteAt=2, recoveryRuns=[{}, {}, {"reload": True}, {}])
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [0, 0, 1, 1] and result["healthy"]
    assert result["randomCalls"] == 1 and result["diskWrites"] == 3
    assert [value["value"] for value in result["factoryValues"]] == [{"A2": 502000, "A4": 1}] * 2
    assert all(value["phase"] == "drawn" for value in result["factoryValues"])
    assert result["stored"] == result["persisted"] and result["stored"]["bag"] == payload["nativeBagAfter"]
    assert result["stored"]["_offline_lottery"]["phase"] == "committed"
    assert result["stored"]["_offline_lottery"]["removed"] == []
    assert result["stored"]["_offline_lottery"]["reward"] == [{"A2": 502000, "A4": 1}]


def test_offered_recovery_uses_renamed_receipt_after_directory_sync_failure(run_production_js):
    payload = recovery_input(502211, phase="offered")
    payload.update(randomValues=[0, 0.99], failDirectorySync=True, recoveryRuns=[{}, {"reload": True}, {"reload": True}])
    result = run_production_js(NODE_WIRE_CHECK, payload)
    assert result["roleReturns"] == [0, 0, 1] and result["healthy"]
    assert result["randomCalls"] == 1 and result["diskWrites"] == 2
    assert [value["value"] for value in result["factoryValues"]] == [{"A2": 502211, "A4": 1}]
    assert result["stored"] == result["persisted"] and result["stored"]["bag"] == payload["nativeBagAfter"]
    assert result["stored"]["_offline_lottery"]["phase"] == "committed"
