import asyncio

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from app.adapters.browser.exceptions import (
    BrowserClosedError,
    BrowserSessionError,
    BrowserStartError,
)
from app.adapters.browser.operations import operation
from app.adapters.browser.schemas import ScreenshotPolicy, account_key


class BrowserManager:
    def __init__(self, settings, storage, *, driver_factory=async_playwright):
        self.settings, self.storage, self.driver_factory = settings, storage, driver_factory
        self._driver, self._browser = None, None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(settings.browser_max_contexts)
        self.sessions = {}
        self._closing = False

    @property
    def is_connected(self):
        return self._browser is not None and self._browser.is_connected()

    def health(self):
        return "UP" if self.is_connected else "DOWN"

    async def startup(self):
        async with self._lock:
            if self.is_connected:
                return
            await self._shutdown()
            self._closing = False
            try:
                async with asyncio.timeout(self.settings.browser_navigation_timeout):
                    self._driver = await self.driver_factory().start()
                    self._browser = await self._driver.chromium.launch(headless=self.settings.browser_headless)
            except (PlaywrightError, TimeoutError, OSError):
                await self._shutdown()
                raise BrowserStartError() from None
            except asyncio.CancelledError:
                await self._shutdown()
                raise

    async def _shutdown(self):
        self._closing = True
        errors = False
        for session in list(self.sessions.values()):
            try:
                await session.close()
            except BrowserSessionError:
                errors = True
        try:
            if self._browser is not None:
                async with asyncio.timeout(self.settings.browser_timeout):
                    await self._browser.close()
        except (PlaywrightError, TimeoutError):
            errors = True
        finally:
            self._browser = None
            try:
                if self._driver is not None:
                    async with asyncio.timeout(self.settings.browser_navigation_timeout):
                        await self._driver.stop()
            except (PlaywrightError, TimeoutError):
                errors = True
            finally:
                self._driver = None
        if errors:
            # close 尽力释放所有资源，固定异常已记录，关闭本身可重复调用。
            raise BrowserSessionError()

    async def shutdown(self):
        async with self._lock:
            await self._shutdown()

    async def create_session(self, account_id, *, restore_state=False, execution_id="manual", task_code="BROWSER",
                             screenshot_policy=ScreenshotPolicy.FAILURE_ONLY, request_policy=None):
        account_key(account_id)
        try:
            screenshot_policy = ScreenshotPolicy(screenshot_policy)
        except ValueError:
            raise BrowserSessionError() from None
        await self._slots.acquire()
        context = None
        try:
            async with self._lock:
                if self._closing or not self.is_connected:
                    raise BrowserClosedError()
                state = await self.storage.load(account_id) if restore_state else None
                options = {"locale": self.settings.browser_locale, "timezone_id": self.settings.browser_timezone}
                if request_policy is not None:
                    options.update(service_workers="block", java_script_enabled=False, accept_downloads=False)
                if self.settings.browser_user_agent:
                    options["user_agent"] = self.settings.browser_user_agent
                if state:
                    options["storage_state"] = state
                async with operation(self, BrowserSessionError):
                    context = await self._browser.new_context(**options)
                guard_state = {"blocked": False}
                if request_policy is not None:
                    async def guard(route):
                        if not request_policy(route.request.url, route.request.method):
                            guard_state["blocked"] = True
                            await route.abort("blockedbyclient")
                            return
                        try:
                            # 不跟随重定向；不依赖仅覆盖首个跳转 URL 的路由回调。
                            response = await route.fetch(max_redirects=0, max_retries=0,
                                                         timeout=self.settings.browser_navigation_timeout * 1000)
                            try:
                                if 300 <= response.status < 400:
                                    guard_state["blocked"] = True
                                    await route.abort("blockedbyclient")
                                else:
                                    await route.fulfill(response=response)
                            finally:
                                await response.dispose()
                        except PlaywrightError:
                            # 回调不能泄漏包含 URL 的第三方异常；导航层返回固定错误。
                            from app.adapters.browser.exceptions import BrowserNavigationError
                            BrowserNavigationError()
                            try:
                                await route.abort("failed")
                            except PlaywrightError:
                                BrowserSessionError()
                    async def block_socket(websocket):
                        guard_state["blocked"] = True
                        await websocket.close()
                    await context.route("**/*", guard)
                    await context.route_web_socket("**/*", block_socket)
                context.set_default_timeout(self.settings.browser_timeout * 1000)
                context.set_default_navigation_timeout(self.settings.browser_navigation_timeout * 1000)
                from app.adapters.browser.session import BrowserSession
                session = BrowserSession(self, context, account_id, execution_id, task_code, screenshot_policy)
                session.guard_state = guard_state
                session.storage_restored = bool(state and (state.get("cookies") or state.get("origins")))
                self.sessions[session.session_id] = session
                return session
        except BaseException:
            self._slots.release()
            if context is not None:
                try:
                    await context.close()
                except PlaywrightError:
                    BrowserSessionError()
            raise

    def released(self, session):
        if self.sessions.pop(session.session_id, None) is not None:
            self._slots.release()
