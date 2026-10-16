"""检索已采集的4399精华标题，返回原帖链接；不读取或保存登录凭据。"""
import argparse
import asyncio
import csv
import json
from pathlib import Path

INDEX = Path(__file__).resolve().parents[2] / 'docs/zmxol-knowledge/4399-digest.tsv'


def search_index(path: Path, words: list[str]) -> list[dict]:
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    seen, results = set(), []
    for row in rows:
        if (set(row) != {'page', 'thread_id', 'title'}
                or not row['thread_id'].isascii() or not row['thread_id'].isdigit()
                or row['page'] not in {'1', '2', '3', '4', '5', '6'} or not row['title']):
            raise ValueError('Invalid forum index row')
        if row['thread_id'] in seen:
            raise ValueError('Duplicate forum thread')
        seen.add(row['thread_id'])
        if all(word.casefold() in row['title'].casefold() for word in words):
            results.append({**row, 'url': 'https://bbs.4399.cn/thread-tid-' + row['thread_id'],
                            'evidence': 'TITLE_INDEX_ONLY', 'version_15_7_2': 'UNVERIFIED'})
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('keywords', nargs='*', help='多个关键词为同时匹配；不填列出全部')
    args = parser.parse_args()
    results = await asyncio.to_thread(search_index, INDEX, args.keywords)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
