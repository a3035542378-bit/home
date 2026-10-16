import csv
from collections import Counter

import pytest

from search_forum import INDEX, search_index


def test_collected_digest_pages_and_online_sources():
    rows = search_index(INDEX, [])
    assert len(rows) == 172
    assert Counter(row['page'] for row in rows) == {'1': 35, '2': 36, '3': 34, '4': 35, '5': 29, '6': 3}
    assert len({row['url'] for row in rows}) == 172
    result = search_index(INDEX, ['至尊', '装备'])
    assert [row['thread_id'] for row in result] == ['19181807']
    assert result[0]['url'] == 'https://bbs.4399.cn/thread-tid-19181807'
    assert result[0]['evidence'] == 'TITLE_INDEX_ONLY'
    assert result[0]['version_15_7_2'] == 'UNVERIFIED'
    assert search_index(INDEX, ['不存在的纳戒协议']) == []
    assert search_index(INDEX, ['boss']) == search_index(INDEX, ['BOSS'])


@pytest.mark.parametrize('thread_id', ['../../secret', '１２３', '12?token=x'])
def test_index_rejects_noncanonical_thread_identity(tmp_path, thread_id):
    path = tmp_path / 'index.tsv'
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t')
        writer.writerow(['page', 'thread_id', 'title'])
        writer.writerow(['1', thread_id, 'example'])
    with pytest.raises(ValueError, match='Invalid'):
        search_index(path, [])


def test_index_rejects_duplicate_threads(tmp_path):
    path = tmp_path / 'index.tsv'
    path.write_text('page\tthread_id\ttitle\n1\t123\texample\n2\t123\texample\n')
    with pytest.raises(ValueError, match='Duplicate'):
        search_index(path, [])
