import asyncio
from contextlib import asynccontextmanager

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from app.adapters.browser.exceptions import (
    BrowserActionTimeout,
    BrowserClosedError,
    BrowserPageCrashError,
)


@asynccontextmanager
async def operation(manager, error_type, *, timeout_type=BrowserActionTimeout, timeout=None, page=None):
    if not manager.is_connected:
        raise BrowserClosedError()
    if page is not None and page.crashed:
        raise BrowserPageCrashError()
    try:
        async with asyncio.timeout(timeout or manager.settings.browser_timeout):
            yield
    except (PlaywrightTimeout, TimeoutError):
        raise timeout_type() from None
    except (PlaywrightError, OSError, ValueError, TypeError):
        if page is not None and page.crashed:
            raise BrowserPageCrashError() from None
        if not manager.is_connected:
            raise BrowserClosedError() from None
        raise error_type() from None
