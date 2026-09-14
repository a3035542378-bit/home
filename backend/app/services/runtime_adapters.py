import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

from app.adapters.browser import BrowserAdapter
from app.adapters.browser.exceptions import BrowserError, BrowserSessionError
from app.adapters.registry import AdapterRegistry
from app.services.account_runtime import AccountRuntimeReader
from app.services.capabilities import BoundExecutorRouter, CapabilityService
from app.services.onebot import OneBotService


class ScopedBrowserAdapter:
    """任务只能访问自身账号；任务完成、失败或取消时回收其全部 Context。"""
    def __init__(self, adapter, context):
        self._adapter, self._context = adapter, context
        self._sessions = []
        self._closed = False

    def capabilities(self):
        return self._adapter.capabilities()

    async def start(self):
        if self._closed:
            raise BrowserSessionError()
        await self._adapter.start()

    async def create_session(self, account_id=None, **options):
        expected = self._context.account.id
        if self._closed or (account_id is not None and account_id != expected):
            raise BrowserSessionError()
        options.update(execution_id=self._context.execution_id, task_code=self._context.task_code or "BROWSER")
        session = await self._adapter.create_session(expected, **options)
        if self._closed:
            await session.close()
            raise BrowserSessionError()
        self._sessions.append(session)
        return session

    async def aclose(self):
        self._closed = True
        results = await asyncio.gather(*(session.close() for session in self._sessions), return_exceptions=True)
        self._sessions.clear()
        if any(isinstance(result, BaseException) for result in results):
            raise BrowserSessionError()


class RuntimeAdapters:
    def __init__(self, uow, settings):
        self.uow = uow
        self.onebot = OneBotService(uow, settings)
        self.browser = BrowserAdapter(settings)
        self.capabilities = CapabilityService(uow, settings, browser_health=self.browser.health)

    def services_for_context(self, context):
        return {"account_runtime": AccountRuntimeReader(self.uow, context.account.id, context.execution_id),
                "executor_router": BoundExecutorRouter(self.capabilities, context.account.id)}

    async def start(self):
        try:
            await self.browser.start()
        except BrowserError:
            # Browser 是可选依赖；其他 Adapter 的任务仍可以执行。
            return

    def health(self):
        return self.browser.health()

    @asynccontextmanager
    async def for_context(self, context, required):
        async with AsyncExitStack() as stack:
            adapters = await stack.enter_async_context(self.onebot.for_context(context, required))
            if "browser" in required:
                scoped = ScopedBrowserAdapter(self.browser, context)
                stack.push_async_callback(scoped.aclose)
                AdapterRegistry({"browser": scoped}).require({"browser": required["browser"]})
                adapters["browser"] = scoped
            if "qq_web" in required:
                from app.adapters.sites.qq.web import QQWebSiteAdapter
                scoped = ScopedBrowserAdapter(self.browser, context)
                stack.push_async_callback(scoped.aclose)
                adapters["qq_web"] = QQWebSiteAdapter(scoped)
            yield adapters

    async def aclose(self):
        try:
            await self.browser.aclose()
        finally:
            await self.onebot.aclose()
