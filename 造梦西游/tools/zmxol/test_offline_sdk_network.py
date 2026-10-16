"""SDK 网络失败边界契约；Java 替身不能替代 Android 启动验收。"""

from pathlib import Path
import struct
import zipfile

import pytest

from apk_patch import locate_methods, read_uleb
from test_offline_bridge import run_production_js


NODE_SDK_CHECK = r"""
const fs = require('node:fs'), vm = require('node:vm');
const used = [], events = [], overload = {};
const context = vm.createContext({
 Process: {findModuleByName: () => null},
 Module: {getExportByName: () => null}, Interceptor: {attach: () => {}},
 NativeFunction: function(){return (_priority, _tag, event) => events.push(JSON.parse(event));},
 Memory: {allocUtf8String: text => text},
 Java: {perform: callback => callback(), use: name => {
   used.push(name);
   if (name === 'com.ssjj.fnsdk.core.SsjjFNUtility') return {openUrlOnceWithTimeOut: {overload: (...types) => {overload.types = types;return overload;}}};
   if (name === 'java.io.IOException') return {$new: message => ({type: name, message})};
   throw new Error('Unexpected Java class');
 }},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const errors = [];
for (const method of ['GET', 'POST', 'DELETE']) {
 try {overload.implementation(null,'sensitive-url',method,'sensitive-parameters','sensitive-headers','sensitive-body',1000,1000);}
 catch(error){errors.push(error);}
}
process.stdout.write(JSON.stringify({used, events, types: overload.types, errors}));
"""


def test_sdk_requests_take_original_io_failure_path_without_logging_arguments(run_production_js):
    result = run_production_js(NODE_SDK_CHECK, {})
    assert result['types'] == ['android.content.Context', 'java.lang.String', 'java.lang.String',
                               'com.ssjj.fnsdk.core.entity.SsjjFNParameters', 'java.lang.String',
                               'java.lang.String', 'int', 'int']
    assert result['errors'] == [{'type': 'java.io.IOException', 'message': 'Offline SDK network unavailable'}] * 3
    assert result['events'] == [{'event': 'offline-sdk-network-failure-ready'}] + [{'event': 'offline-sdk-network-blocked'}] * 3
    assert 'sensitive-' not in str(result)


def test_hook_signature_matches_actual_15_7_2_dex():
    apk = Path(__file__).resolve().parents[2] / 'artifacts/zmxol-offline/squad-build/15.7.2-mail-stability-signed.apk'
    if not apk.is_file():
        pytest.skip('15.7.2 baseline APK unavailable')
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if not name.startswith('classes') or not name.endswith('.dex'):
                continue
            data = archive.read(name)
            methods = locate_methods(data, 'Lcom/ssjj/fnsdk/core/SsjjFNUtility;', ('openUrlOnceWithTimeOut',))
            if not methods:
                continue
            method_index, _ = methods['openUrlOnceWithTimeOut']
            method_offset = struct.unpack_from('<I', data, 0x5c)[0]
            proto_index = struct.unpack_from('<H', data, method_offset + method_index * 8 + 2)[0]
            proto_offset = struct.unpack_from('<I', data, 0x4c)[0] + proto_index * 12
            return_type, parameters = struct.unpack_from('<II', data, proto_offset + 4)
            type_offset = struct.unpack_from('<I', data, 0x44)[0]
            string_offset = struct.unpack_from('<I', data, 0x3c)[0]

            def descriptor(index):
                string_index = struct.unpack_from('<I', data, type_offset + index * 4)[0]
                position = struct.unpack_from('<I', data, string_offset + string_index * 4)[0]
                _, position = read_uleb(data, position)
                return data[position:data.index(0, position)].decode('ascii')

            count = struct.unpack_from('<I', data, parameters)[0]
            types = struct.unpack_from(f'<{count}H', data, parameters + 4)
            assert descriptor(return_type) == 'Ljava/lang/String;'
            assert [descriptor(index) for index in types] == [
                'Landroid/content/Context;', 'Ljava/lang/String;', 'Ljava/lang/String;',
                'Lcom/ssjj/fnsdk/core/entity/SsjjFNParameters;', 'Ljava/lang/String;',
                'Ljava/lang/String;', 'I', 'I']
            return
    pytest.fail('SDK network method missing from baseline DEX')
