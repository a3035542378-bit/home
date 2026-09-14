"""共享 MySQL Outbox 的开发环境验收，暂停常驻发布者后恢复原状态。"""
import asyncio
import json


async def command(*args, capture=False):
    process = await asyncio.create_subprocess_exec('docker', 'compose', *args,
        stdout=asyncio.subprocess.PIPE if capture else None)
    output, _ = await process.communicate()
    if process.returncode:
        raise RuntimeError('Docker 验收命令失败')
    return output.decode() if capture else None


async def main():
    rows = (await command('ps', '--format', 'json', capture=True)).splitlines()
    active = [row['Service'] for row in map(json.loads, rows)
              if row['Service'] in {'worker', 'scheduler'} and row['State'] == 'running']
    active = sorted(set(active))
    try:
        if active:
            await command('stop', *active)
        await command('exec', '-T', 'backend', 'python', '-m', 'app.tools.business_acceptance')
    finally:
        if active:
            await command('start', *active)


if __name__ == '__main__':
    asyncio.run(main())
