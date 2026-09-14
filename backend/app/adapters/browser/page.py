import asyncio
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from app.adapters.browser.exceptions import (
    BrowserActionError,
    BrowserNavigationError,
    BrowserNavigationTimeout,
    BrowserSelectorTimeout,
)
from app.adapters.browser.operations import operation
from app.adapters.browser.schemas import BrowserEvidence, ScreenshotPolicy, Selector, safe_origin
from app.adapters.browser.storage import atomic_private_write


class BrowserPage:
    def __init__(self, session, page):
        self.session, self._page = session, page
        self.crashed = False
        page.on("crash", self._crash)

    def _crash(self, *args):
        self.crashed = True

    @property
    def url(self):
        return self._page.url

    def _locator(self, selector):
        if isinstance(selector, str):
            return self._page.locator(selector)
        if not isinstance(selector, Selector):
            raise BrowserActionError()
        if selector.kind == "role":
            return self._page.get_by_role(selector.value, name=selector.name)
        if selector.kind == "text":
            return self._page.get_by_text(selector.value, exact=True)
        return self._page.locator(selector.value)

    async def _call(self, fn, error=BrowserActionError, timeout_type=None, timeout=None):
        self.session.touch()
        kwargs = {"timeout_type": timeout_type} if timeout_type else {}
        async with operation(self.session.manager, error, page=self, timeout=timeout, **kwargs):
            return await fn()

    async def goto(self, url):
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except (ValueError, TypeError):
            raise BrowserNavigationError() from None
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise BrowserNavigationError()
        response = await self._call(lambda: self._page.goto(url, wait_until="domcontentloaded"),
            BrowserNavigationError, BrowserNavigationTimeout, self.session.manager.settings.browser_navigation_timeout)
        return response.status if response else None

    async def click(self, selector):
        await self._call(lambda: self._locator(selector).click())

    async def fill(self, selector, value):
        await self._call(lambda: self._locator(selector).fill(value))

    async def title(self):
        return await self._call(self._page.title)

    async def text(self, selector):
        return await self._call(lambda: self._locator(selector).inner_text(), timeout_type=BrowserSelectorTimeout)

    async def exists(self, selector):
        return bool(await self._call(lambda: self._locator(selector).count()))

    async def read_attributes(self, selector, attributes, *, limit=100):
        # 只返回指定属性，限制条数及字段长度；不导出 HTML 或任意页面文本。
        return await self._call(lambda: self._locator(selector).evaluate_all(
            "(nodes, options) => nodes.slice(0, options.limit).map(node => "
            "Object.fromEntries(options.attributes.map(key => [key, node.getAttribute(key)?.slice(0, 101) ?? null])))",
            {"attributes": attributes, "limit": limit},
        ))

    async def wait_for(self, selector):
        await self._call(lambda: self._locator(selector).wait_for(state="visible"), timeout_type=BrowserSelectorTimeout)

    async def wait_for_url(self, pattern):
        await self._call(lambda: self._page.wait_for_url(pattern), timeout_type=BrowserNavigationTimeout,
                         timeout=self.session.manager.settings.browser_navigation_timeout)

    async def evaluate(self, script):
        return await self._call(lambda: self._page.evaluate(script))

    async def reload(self):
        await self._call(lambda: self._page.reload(wait_until="domcontentloaded"),
            BrowserNavigationError, BrowserNavigationTimeout, self.session.manager.settings.browser_navigation_timeout)

    async def screenshot(self, *, failure=False, safe_selector=None):
        # 默认不拍整页。调用方必须明确指定无敏感内容的区域；其输入字段仍强制遮罩。
        if self.session.screenshot_policy == ScreenshotPolicy.DISABLED or not failure or not safe_selector:
            return None
        data = await self._call(lambda: self._locator(safe_selector).screenshot(
            mask=[self._page.locator("input, textarea, [contenteditable], [data-sensitive]")],
        ))
        safe = lambda value: re.sub(r"[^A-Za-z0-9_-]", "_", value)[:80]
        filename = f"{safe(self.session.execution_id)}_{safe(self.session.task_code)}_{uuid4().hex}.png"
        path = Path(self.session.manager.settings.browser_screenshot_dir) / filename
        try:
            await asyncio.to_thread(atomic_private_write, path, data)
        except OSError:
            raise BrowserActionError() from None
        return BrowserEvidence(final_url=safe_origin(self.url), screenshot_path=str(path))

    def evidence(self):
        return BrowserEvidence(final_url=safe_origin(self.url))

    async def close(self):
        if not self._page.is_closed():
            await self._call(self._page.close)
