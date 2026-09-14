import asyncio
from contextlib import suppress
from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError
from test_browser_unit import config

from app.adapters.browser import BrowserAdapter, ScreenshotPolicy, Selector
from app.adapters.browser.exceptions import (
    BrowserActionTimeout,
    BrowserClosedError,
    BrowserNavigationTimeout,
    BrowserPageCrashError,
    BrowserSelectorTimeout,
)
from app.tools.browser_site import browser_site

pytestmark = pytest.mark.browser_integration


@pytest.fixture
async def browser(tmp_path):
    adapter = BrowserAdapter(config(tmp_path, browser_max_contexts=2))
    await adapter.start()
    try:
        yield adapter
    finally:
        await adapter.stop()


@pytest.fixture
async def site():
    async with browser_site() as origin:
        yield origin


async def test_real_start_shutdown_idempotent(browser):
    old=browser.manager._browser
    await browser.start()
    assert old is browser.manager._browser
    assert browser.health()=='UP'
    await browser.stop()
    await browser.stop()
    assert browser.health()=='DOWN'


async def test_real_goto_text(browser,site):
    async with await browser.create_session(1) as session:
        page=await session.new_page()
        assert await page.goto(site+'/simple')==200
        assert await page.text('h1')=='Local fixture'


async def test_real_click_role_and_text(browser,site):
    async with await browser.create_session(1) as session:
        page=await session.new_page(); await page.goto(site+'/simple')
        await page.click(Selector('role','button','Go'))
        assert await page.text('#result')=='clicked'
        assert await page.exists(Selector('text','Local fixture'))


async def test_real_fill_submit_once(browser,site):
    async with await browser.create_session(1) as session:
        page=await session.new_page(); await page.goto(site+'/form')
        await page.fill('#field','fixture-value')
        assert await page.evaluate("document.querySelector('#field').value")=='fixture-value'
        await page.click('#submit')
        assert await page.evaluate('window.submissions')==1


async def test_real_wait_exists(browser,site):
    async with await browser.create_session(1) as session:
        page=await session.new_page(); await page.goto(site+'/simple')
        assert not await page.exists('#missing')
        await page.wait_for('#later')
        assert await page.text('#later')=='later'


async def test_real_navigation_timeout(browser,site):
    browser.manager.settings.browser_navigation_timeout=.1
    async with await browser.create_session(1) as session:
        page=await session.new_page()
        with pytest.raises(BrowserNavigationTimeout):
            await page.goto(site+'/delay')


async def test_real_action_and_selector_timeouts(browser,site):
    async with await browser.create_session(1) as session:
        page=await session.new_page(); await page.goto(site+'/simple')
        browser.manager.settings.browser_timeout=.15
        with pytest.raises(BrowserActionTimeout):
            await page.click('#missing')
        with pytest.raises(BrowserSelectorTimeout):
            await page.wait_for('#missing')
        browser.manager.settings.browser_timeout=5


async def test_real_redirect_reload(browser,site):
    async with await browser.create_session(1) as session:
        page=await session.new_page(); await page.goto(site+'/redirect')
        await page.wait_for_url('**/simple')
        await page.reload()
        assert page.url.endswith('/simple')


async def test_real_http_error_is_business_result(browser,site):
    async with await browser.create_session(1) as session:
        page=await session.new_page()
        assert await page.goto(site+'/error')==500


async def test_real_screenshot_policy(browser,site):
    async with await browser.create_session(1,execution_id='run',task_code='TEST') as session:
        page=await session.new_page(); await page.goto(site+'/simple?token=fixture-private')
        assert await page.screenshot() is None
        shot=await page.screenshot(failure=True,safe_selector='#safe')
        path=Path(shot.screenshot_path)
        assert path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
        assert path.stat().st_mode & 0o777==0o600
        assert shot.final_url==site
        session.screenshot_policy=ScreenshotPolicy.DISABLED
        assert await page.screenshot(failure=True,safe_selector='#safe') is None


async def test_real_storage_save_restore_and_isolation(browser,site):
    a,b=await browser.create_session(1),await browser.create_session(2)
    page_a,page_b=await a.new_page(),await b.new_page()
    await asyncio.gather(page_a.goto(site+'/storage'),page_b.goto(site+'/storage'))
    await page_a.evaluate("document.cookie='fixture=A;path=/';localStorage.setItem('fixture','A');sessionStorage.setItem('fixture','A')")
    await page_b.evaluate("document.cookie='fixture=B;path=/';localStorage.setItem('fixture','B');sessionStorage.setItem('fixture','B')")
    assert await page_a.evaluate('document.cookie')=='fixture=A'
    assert await page_b.evaluate('document.cookie')=='fixture=B'
    assert await page_a.evaluate("sessionStorage.getItem('fixture')")=='A'
    assert await page_b.evaluate("localStorage.getItem('fixture')")=='B'
    await a.save_state()
    await a.close(); await b.close()
    async with await browser.create_session(1,restore_state=True) as restored:
        page=await restored.new_page();await page.goto(site+'/storage')
        assert await page.evaluate('document.cookie')=='fixture=A'
        assert await page.evaluate("localStorage.getItem('fixture')")=='A'
        # Playwright storage_state 不持久化 sessionStorage，不能假称恢复。
        assert await page.evaluate("sessionStorage.getItem('fixture')") is None
    async with await browser.create_session(2,restore_state=True) as empty:
        page=await empty.new_page();await page.goto(site+'/storage')
        assert await page.evaluate('document.cookie')==''


async def test_real_concurrency_limit(browser):
    a,b=await browser.create_session(1),await browser.create_session(2)
    pending=asyncio.create_task(browser.create_session(3))
    await asyncio.sleep(.05)
    assert not pending.done()
    await a.close()
    c=await asyncio.wait_for(pending,2)
    assert c.account_id==3
    await b.close();await c.close()


async def test_real_page_close(browser):
    async with await browser.create_session(1) as session:
        page=await session.new_page()
        await page.close();await page.close()
        assert page._page.is_closed()


async def test_real_browser_crash(browser,site):
    session=await browser.create_session(1)
    page=await session.new_page();await page.goto(site+'/simple')
    cdp=await browser.manager._browser.new_browser_cdp_session()
    with suppress(PlaywrightError,TimeoutError):
        await asyncio.wait_for(cdp.send('Browser.crash'),3)
    async with asyncio.timeout(3):
        while browser.manager.is_connected:
            await asyncio.sleep(.02)
    with pytest.raises(BrowserClosedError):
        await page.click('#go')


async def test_real_page_crash(browser,site):
    session=await browser.create_session(1)
    page=await session.new_page();await page.goto(site+'/simple')
    cdp=await session._context.new_cdp_session(page._page)
    with suppress(PlaywrightError,TimeoutError):
        await asyncio.wait_for(cdp.send('Page.crash'),1)
    async with asyncio.timeout(3):
        while not page.crashed:
            await asyncio.sleep(.02)
    with pytest.raises(BrowserPageCrashError):
        await page.text('h1')


async def test_real_shutdown_closes_contexts(browser):
    session=await browser.create_session(1)
    page=await session.new_page()
    await browser.stop()
    assert session.closed and page._page.is_closed()
    assert not browser.manager.sessions


async def test_real_authentication_predicate(browser,site):
    async with await browser.create_session(1) as session:
        page=await session.new_page();await page.goto(site+'/simple')
        async def predicate(current):
            return current.account_id==1 and await page.exists('#go')
        assert await session.is_authenticated(predicate)


async def test_real_worker_drains_task_and_closes_context(browser,site,tmp_path):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from test_browser_unit import FakeTask

    from app.models.common import ExecutionStatus
    from app.services.runtime_adapters import ScopedBrowserAdapter
    from app.tasks.base import AccountContext, TaskContext, TaskResult
    from app.tasks.engine import TaskEngine
    from app.tasks.registry import TaskRegistry
    from app.workers.worker import Worker
    opened,finish=asyncio.Event(),asyncio.Event()
    class Provider:
        def health(self):
            return browser.health()
        @asynccontextmanager
        async def for_context(self, context, required):
            scoped=ScopedBrowserAdapter(browser,context)
            try:
                yield {'browser':scoped}
            finally:
                await scoped.aclose()
    class LocalTask(FakeTask):
        async def execute(self, context):
            session=await context.get_adapter('browser').create_session()
            page=await session.new_page()
            await page.goto(site+'/simple')
            opened.set()
            await finish.wait()
            assert await page.text('h1')=='Local fixture'
            return TaskResult(success=True,status=ExecutionStatus.SUCCESS,message='完成')
    registry=TaskRegistry();registry.register(LocalTask)
    engine=TaskEngine(None,registry,adapter_provider=Provider())
    worker=Worker(AsyncMock(),AsyncMock(),engine,AsyncMock(),config(tmp_path))
    task=asyncio.create_task(engine.run('BROWSER_TEST',TaskContext(AccountContext(1,'web','WEB',''),'worker-run')))
    worker.tasks.add(task)
    await asyncio.wait_for(opened.wait(),5)
    worker.stop.set()
    stopping=asyncio.create_task(worker.run())
    await asyncio.sleep(.02)
    assert not stopping.done()
    finish.set()
    await asyncio.wait_for(stopping,3)
    assert task.result().success and not browser.manager.sessions
