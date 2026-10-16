"""状态边界与原子存储替身测试；真实原生验收另存设备证据。"""
import asyncio
import copy
import json
from pathlib import Path

import pytest

from debug_fusion_response import build_fusion_script
from debug_spirit_state import build_spirit_state_script
from test_debug_fusion_response import inputs


def run_node(script, payload, path):
    async def execute():
        process = await asyncio.create_subprocess_exec('node', '-e', script, str(path), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, error = await process.communicate(json.dumps(payload).encode())
        assert process.returncode == 0, error.decode()
        return json.loads(out)
    return asyncio.run(execute())


def sample():
    _, _, spirit = inputs()
    spirit.update(globalid=4407, level=75, tamestate=2)
    before = {'roledata': {'player': {'roleid': 1}}, 'pet': {'petinfo': [{'petid': 4399, 'tamestate': 1}]}, 'true_spirit_bag': {'list': [spirit], 'bagsize': 8, 'maxspiritid': 4407}}
    after = copy.deepcopy(before)
    after['pet']['petinfo'][0]['tamestate'] = 2
    after['true_spirit_bag']['list'][0]['tamestate'] = 1
    return {'rid': 10001, 'global_id': 4407, 'state': 1}, before, after


@pytest.mark.parametrize('case', ['deploy', 'repeat', 'rest', 'switch', 'missing', 'type_id', 'role', 'other_profile', 'state', 'string_state', 'removed_pet', 'changed_level', 'pet_conflict', 'changed_id'])
def test_native_transition_guard(case, tmp_path):
    request, before, after = sample()
    if case == 'repeat': before = copy.deepcopy(after)
    if case == 'rest':
        before = copy.deepcopy(after)
        request['state'] = 2
        after['true_spirit_bag']['list'][0]['tamestate'] = 2
    if case == 'switch':
        other = copy.deepcopy(before['true_spirit_bag']['list'][0]); other.update(globalid=4406, tamestate=1)
        before['true_spirit_bag']['list'].append(other)
        other = copy.deepcopy(other); other['tamestate'] = 2
        after['true_spirit_bag']['list'].append(other)
    if case == 'missing': request['global_id'] = 1
    if case == 'type_id': request['global_id'] = 9001
    if case == 'role': request['rid'] = 10002
    if case == 'other_profile': before['roledata']['player']['roleid'] = 2
    if case == 'state': request['state'] = 3
    if case == 'string_state': request['state'] = '1'
    if case == 'removed_pet': after['pet']['petinfo'] = []
    if case == 'changed_level': after['true_spirit_bag']['list'][0]['level'] += 1
    if case == 'pet_conflict': after['pet']['petinfo'][0]['tamestate'] = 1
    if case == 'changed_id': after['true_spirit_bag']['list'][0]['globalid'] = 4406
    path = tmp_path / 'guard.js'
    path.write_text(Path(__file__).with_name('debug_fusion_response.js').read_text() + '\n' + Path(__file__).with_name('debug_spirit_state.js').read_text().split(' const stateThreads=')[0])
    harness = "const fs=require('fs'),vm=require('vm'),c=vm.createContext({});vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);try{c.validateSpiritStateTransition(...JSON.parse(fs.readFileSync(0,'utf8')));process.stdout.write('true');}catch(e){process.stdout.write('false');}"
    assert run_node(harness, [request, before, after], path) is (case in ['deploy', 'repeat', 'rest', 'switch'])


def test_integration_is_narrow_and_checks_input(tmp_path):
    source = build_fusion_script(*inputs(), experimental=True)
    generated = build_spirit_state_script(source)
    assert source != generated
    assert "store.debugSpiritStateSave(after);stateThreads.add" in generated
    assert 'debugFusion?.preparedState(req)&&store.healthy()' in generated
    with pytest.raises(ValueError): build_spirit_state_script('invalid')
    path = tmp_path / 'bridge.js'; path.write_text(generated)
    harness = "const vm=require('vm'),fs=require('fs');new vm.Script(fs.readFileSync(process.argv[1],'utf8'));process.stdout.write('true');"
    assert run_node(harness, {}, path)


@pytest.mark.parametrize('failure', [{}, {'failWriteAt': 2}, {'failDirectorySync': True}])
def test_state_save_replay_and_restart_use_durable_state(tmp_path, failure):
    from test_offline_bridge import NODE_WIRE_CHECK
    _, before, after = sample()
    path = tmp_path / 'bridge.js'
    path.write_text(build_spirit_state_script(build_fusion_script(*inputs(), experimental=True)))
    actions = [{'kind': 'fusion', 'snapshot': {**before, 'bag': {'spiritcount': 17245}}, 'receipt': {'phase': 'committed'}},
               {'kind': 'state', 'snapshot': after}, {'kind': 'state', 'snapshot': after}, {'kind': 'reload'}]
    harness = NODE_WIRE_CHECK.replace("else throw new Error('Unknown test action');", "else if(action.kind==='fusion')store.debugFusionSave(action.snapshot,action.receipt);else if(action.kind==='state')store.debugSpiritStateSave(action.snapshot);else throw new Error('Unknown test action');", 1)
    result = run_node(harness, {'nativeStore': True, 'lotteryActions': actions, **failure}, path)
    state = result['role']['savedata']['true_spirit_bag']['list'][0]['tamestate']
    assert state == (1 if not failure else 2)
    assert result['stored']['pet']['petinfo'] == (after if not failure else before)['pet']['petinfo']
    assert result['stored']['_DEBUG_ONLY_fusion'] == {'phase': 'committed'}
    assert result['stored']['bag']['spiritcount'] == 17245
    if failure: assert 'error' in result['results'][1] and 'error' in result['results'][2]
