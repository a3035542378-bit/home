"""队列验收用临时站点：只监听本容器 loopback，stdin 关闭即退出。"""
import asyncio
import sys

from app.tools.browser_site import browser_site


async def main():
    async with browser_site() as origin:
        print(origin, flush=True)
        await asyncio.to_thread(sys.stdin.buffer.read, 1)


if __name__ == "__main__":
    asyncio.run(main())
