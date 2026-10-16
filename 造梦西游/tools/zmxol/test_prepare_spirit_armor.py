import io
import json
import zipfile

import pytest

from legacy_resources import SOURCE_PREFIX
from prepare_spirit_armor import collect_armor_resources


@pytest.mark.parametrize('case', ['valid', 'missing', 'duplicate', 'empty', 'unsafe_page', 'missing_animation'])
def test_original_armor_dependency_closure(case):
    animation = {key: {} for key in ['rest', 'run', '9501000', '9501010_0', '9501010_1', '9501020', '9501030']}
    if case == 'missing_animation': del animation['9501030']
    entries = {'95011.json': json.dumps({'animations': animation}).encode(),
               '95011.atlas': b'\n95011.png\nsize: 1024,512\nformat: RGBA8888\n', '95011.png': b'original pixels'}
    if case == 'missing': del entries['95011.png']
    if case == 'empty': entries['95011.png'] = b''
    if case == 'unsafe_page': entries['95011.atlas'] = b'\n../95011.png\nsize: 1024,512\n'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, value in entries.items(): archive.writestr(SOURCE_PREFIX + name, value)
        if case == 'duplicate':
            with pytest.warns(UserWarning): archive.writestr(SOURCE_PREFIX + '95011.png', b'duplicate')
    with zipfile.ZipFile(stream) as archive:
        if case != 'valid':
            with pytest.raises(ValueError): collect_armor_resources(archive)
        else:
            result = collect_armor_resources(archive)
            assert len(result) == 3
            for name, value in entries.items(): assert result['skeleton/beast_armor/9501/' + name] == value
