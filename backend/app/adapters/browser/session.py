import asyncio
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError

from app.adapters.browser.exceptions import (
    BrowserSessionError,
    BrowserStorageError,
    BrowserUserActionRequired,
)
from app.adapters.browser.operations import operation
from app.models.common import utcnow


class BrowserSession:
    def __init__(self, manager, context, account_id, execution_id, task_code, screenshot_policy):
        self.manager, self._context, self.account_id = manager, context, account_id
        self.session_id = uuid4().hex
        self.execution_id, self.task_code, self.screenshot_policy = execution_id, task_code, screenshot_policy
        self.created_at = self.last_used_at = utcnow()
        self.closed = False
        self._close_lock = asyncio.Lock()

    def touch(self):
        if self.closed:
            raise BrowserSessionError()
        self.last_used_at = utcnow()

    async def __aenter__(self):
        self.touch()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def new_page(self):
        self.touch()
        async with operation(self.manager, BrowserSessionError):
            raw = await self._context.new_page()
        from app.adapters.browser.page import BrowserPage
        return BrowserPage(self, raw)

    async def cookies(self):
        self.touch()
        async with operation(self.manager, BrowserSessionError):
            return await self._context.cookies()

    async def save_state(self):
        self.touch()
        async with operation(self.manager, BrowserStorageError):
            state = await self._context.storage_state(indexed_db=True)
        await self.manager.storage.save(self.account_id, state)

    async def is_authenticated(self, predicate):
        self.touch()
        return bool(await predicate(self))

    def require_user_action(self):
        raise BrowserUserActionRequired()

    async def close(self):
        async with self._close_lock:
            if self.closed:
                return
            self.closed = True
            try:
                async with asyncio.timeout(self.manager.settings.browser_timeout):
                    await self._context.close()
            except (PlaywrightError, TimeoutError):
                raise BrowserSessionError() from None
            finally:
                self.manager.released(self)
