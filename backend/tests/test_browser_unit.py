import asyncio
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import SecretStr

from app.adapters.browser import BrowserEvidence, ScreenshotPolicy
from app.adapters.browser.exceptions import (
    BrowserActionError,
    BrowserActionTimeout,
    BrowserClosedError,
    BrowserNavigationError,
    BrowserPageCrashError,
    BrowserSessionError,
    BrowserStartError,
    BrowserStorageError,
)
from app.adapters.browser.fake import FakeBrowserAdapter
from app.adapters.browser.manager import BrowserManager
from app.adapters.browser.page import BrowserPage
from app.adapters.browser.storage import EncryptedFileStorage
from app.core.config import Settings
from app.models.common import ExecutionStatus
from app.services.runtime_adapters import ScopedBrowserAdapter
from app.services.system_service import SystemService
from app.tasks.base import AccountContext, BaseTask, TaskContext, TaskResult
from app.tasks.engine import TaskEngine
from app.tasks.registry import TaskRegistry


def config(tmp_path, **kwargs):
    return Settings(_env_file=None, database_url='sqlite+aiosqlite:///:memory:',
        browser_state_dir=str(tmp_path/'state'), browser_screenshot_dir=str(tmp_path/'shots'),
        browser_storage_key=SecretStr(Fernet.generate_key().decode()), **kwargs)


def mocked_manager(tmp_path, **kwargs):
    def context(**options):
        value = Mock()
        value.close = AsyncMock()
        value.new_page = AsyncMock()
        value.storage_state = AsyncMock(return_value={'cookies':[], 'origins':[]})
        return value
    browser = Mock()
    browser.is_connected.return_value = True
    browser.new_context = AsyncMock(side_effect=context)
    browser.close = AsyncMock()
    driver = Mock()
    driver.chromium.launch = AsyncMock(return_value=browser)
    driver.stop = AsyncMock()
    launcher = Mock()
    launcher.start = AsyncMock(return_value=driver)
    settings = config(tmp_path, **kwargs)
    manager = BrowserManager(settings, EncryptedFileStorage(settings.browser_state_dir,settings.browser_storage_key), driver_factory=lambda:launcher)
    return manager, launcher, driver, browser


async def test_idempotent_lifecycle(tmp_path):
    manager, launcher, driver, browser = mocked_manager(tmp_path)
    await asyncio.gather(manager.startup(), manager.startup())
    assert launcher.start.await_count == 1
    await manager.shutdown()
    await manager.shutdown()
    assert browser.close.await_count == driver.stop.await_count == 1


async def test_start_failure_cleanup(tmp_path):
    manager, _, driver, _ = mocked_manager(tmp_path)
    driver.chromium.launch.side_effect = PlaywrightError('password=hidden')
    with pytest.raises(BrowserStartError) as error:
        await manager.startup()
    assert 'hidden' not in str(error.value)
    driver.stop.assert_awaited_once()
    await manager.shutdown()


async def test_sessions_independent_and_close_idempotent(tmp_path):
    manager, _, _, _ = mocked_manager(tmp_path)
    await manager.startup()
    a, b = await manager.create_session(1), await manager.create_session(2)
    assert a._context is not b._context and a.session_id != b.session_id
    await a.close()
    await a.close()
    a._context.close.assert_awaited_once()
    assert len(manager.sessions) == 1
    await manager.shutdown()
    assert b.closed and not manager.sessions


async def test_capacity_wait_and_cancellation(tmp_path):
    manager, _, _, _ = mocked_manager(tmp_path, browser_max_contexts=1)
    await manager.startup()
    first = await manager.create_session(1)
    blocked = asyncio.create_task(manager.create_session(2))
    await asyncio.sleep(.02)
    assert not blocked.done()
    blocked.cancel()
    await asyncio.gather(blocked, return_exceptions=True)
    next_session = asyncio.create_task(manager.create_session(3))
    await first.close()
    assert (await asyncio.wait_for(next_session, 1)).account_id == 3
    await manager.shutdown()


async def test_context_failure_releases_capacity(tmp_path):
    manager, _, _, browser = mocked_manager(tmp_path, browser_max_contexts=1)
    await manager.startup()
    create = browser.new_context.side_effect
    browser.new_context.side_effect = PlaywrightError('Cookie secret')
    with pytest.raises(BrowserSessionError):
        await manager.create_session(1)
    browser.new_context.side_effect = create
    session = await asyncio.wait_for(manager.create_session(2), 1)
    assert session.account_id == 2
    await manager.shutdown()


async def test_closed_browser_reports_failure(tmp_path):
    manager, _, _, browser = mocked_manager(tmp_path)
    await manager.startup()
    browser.is_connected.return_value = False
    with pytest.raises(BrowserClosedError):
        await manager.create_session(1)
    await manager.shutdown()


@pytest.mark.parametrize('account_id', [0,-1,True,'../secret'])
async def test_account_path_validation(tmp_path, account_id):
    settings = config(tmp_path)
    storage = EncryptedFileStorage(settings.browser_state_dir, settings.browser_storage_key)
    with pytest.raises(BrowserSessionError):
        await storage.save(account_id, {})


async def test_storage_encrypted_bound_atomic_and_delete(tmp_path):
    settings=config(tmp_path)
    storage=EncryptedFileStorage(settings.browser_state_dir, settings.browser_storage_key)
    assert await storage.load(1) is None
    state={'cookies':[{'name':'test','value':'private-value'}], 'origins':[]}
    await storage.save(1,state)
    path=Path(settings.browser_state_dir)/'1.state.enc'
    assert b'private-value' not in path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert await storage.load(1) == state
    (path.parent/'2.state.enc').write_bytes(path.read_bytes())
    with pytest.raises(BrowserStorageError):
        await storage.load(2)
    await storage.delete(1)
    await storage.delete(1)
    assert await storage.load(1) is None


@pytest.mark.parametrize('damage', ['corrupt','wrong-key','missing-key'])
async def test_storage_rejects_corruption(tmp_path, damage):
    settings=config(tmp_path)
    storage=EncryptedFileStorage(settings.browser_state_dir, settings.browser_storage_key)
    await storage.save(1, {'cookies':[], 'origins':[]})
    if damage=='corrupt':
        (Path(settings.browser_state_dir)/'1.state.enc').write_bytes(b'not-encrypted')
    else:
        storage.key = SecretStr('' if damage=='missing-key' else Fernet.generate_key().decode())
    with pytest.raises(BrowserStorageError):
        await storage.load(1)


async def test_storage_refuses_symlink(tmp_path):
    settings=config(tmp_path)
    path=Path(settings.browser_state_dir)
    path.mkdir()
    secret=tmp_path/'unrelated'
    secret.write_text('unchanged')
    (path/'1.state.enc').symlink_to(secret)
    storage=EncryptedFileStorage(path,settings.browser_storage_key)
    with pytest.raises(BrowserStorageError):
        await storage.save(1,{})
    assert secret.read_text() == 'unchanged'


async def test_page_errors_and_no_action_retry(tmp_path):
    manager, _, _, _ = mocked_manager(tmp_path)
    await manager.startup()
    session=await manager.create_session(1)
    raw=Mock()
    locator=Mock()
    locator.click=AsyncMock(side_effect=PlaywrightTimeout('authorization=hidden'))
    raw.locator.return_value=locator
    page=BrowserPage(session,raw)
    with pytest.raises(BrowserActionTimeout) as caught:
        await page.click('#button')
    assert locator.click.await_count == 1
    assert 'hidden' not in str(caught.value)
    locator.click.side_effect=PlaywrightError('secret')
    with pytest.raises(BrowserActionError):
        await page.click('#button')
    page._crash()
    with pytest.raises(BrowserPageCrashError):
        await page.click('#button')
    await manager.shutdown()


@pytest.mark.parametrize('url', ['file:///etc/passwd','javascript:alert(1)','http://user:password@host'])
async def test_navigation_url_validation(tmp_path,url):
    manager, _, _, _ = mocked_manager(tmp_path)
    await manager.startup()
    page=BrowserPage(await manager.create_session(1),Mock())
    with pytest.raises(BrowserNavigationError):
        await page.goto(url)
    await manager.shutdown()


async def test_screenshot_requires_explicit_safe_failure(tmp_path):
    manager, _, _, _ = mocked_manager(tmp_path)
    await manager.startup()
    session=await manager.create_session(1)
    raw=Mock()
    raw.url='https://example.test/path?token=fixture-sensitive-value#secret'
    raw.locator.return_value.screenshot=AsyncMock(return_value=b'png')
    page=BrowserPage(session,raw)
    assert await page.screenshot() is None
    assert await page.screenshot(failure=True) is None
    evidence=await page.screenshot(failure=True,safe_selector='#public')
    assert evidence.final_url=='https://example.test'
    assert 'fixture-sensitive-value' not in evidence.model_dump_json()
    assert raw.locator.return_value.screenshot.call_args.kwargs['mask']
    session.screenshot_policy=ScreenshotPolicy.DISABLED
    assert await page.screenshot(failure=True,safe_selector='#public') is None
    await manager.shutdown()


class FakeTask(BaseTask):
    task_code='BROWSER_TEST'
    required_capabilities: ClassVar[dict[str,set[str]]] = {'browser':{'browser.navigation'}}
    async def execute(self, context):
        session=await context.get_adapter('browser').create_session()
        page=await session.new_page()
        await page.goto('http://local.test')
        context.record_browser_evidence(BrowserEvidence(final_url='https://example.test'))
        return TaskResult(success=True,status=ExecutionStatus.SUCCESS,message='完成')


@pytest.mark.parametrize('mode,status,code', [
    ('success',ExecutionStatus.SUCCESS,None),('timeout',ExecutionStatus.FAILED,'BROWSER_ACTION_TIMEOUT'),
    ('navigation_error',ExecutionStatus.FAILED,'BROWSER_NAVIGATION_ERROR'),
    ('user_action',ExecutionStatus.NEED_USER_ACTION,'BROWSER_USER_ACTION_REQUIRED'),
])
async def test_engine_scoped_adapter(mode,status,code):
    from contextlib import asynccontextmanager
    fake=FakeBrowserAdapter(mode)
    context=TaskContext(AccountContext(1,'web','WEB',''), 'run')
    class Provider:
        @asynccontextmanager
        async def for_context(self, context, required):
            scoped=ScopedBrowserAdapter(fake,context)
            try:
                yield {'browser':scoped}
            finally:
                await scoped.aclose()
    registry=TaskRegistry(); registry.register(FakeTask)
    result=await TaskEngine(None,registry,adapter_provider=Provider()).run('BROWSER_TEST',context)
    assert (result.status,result.error_code)==(status,code)
    assert all(s.closed for s in fake.sessions)
    if mode=='success':
        assert result.data['browser_evidence'][0]['final_url']=='https://example.test'


async def test_scope_forbids_other_account():
    fake=FakeBrowserAdapter()
    context=TaskContext(AccountContext(1,'web','WEB',''), 'run')
    scoped=ScopedBrowserAdapter(fake,context)
    with pytest.raises(BrowserSessionError):
        await scoped.create_session(2)
    await scoped.aclose()
    with pytest.raises(BrowserSessionError):
        await scoped.create_session(1)


async def test_browser_optional_health():
    workers=AsyncMock()
    workers.list.return_value=[{'status':'ONLINE','browser':'DOWN'}]
    health=await SystemService(AsyncMock(),AsyncMock(),1,worker_status=workers).health()
    assert health.browser=='DOWN' and health.status=='ok'


async def test_task_import_boundary():
    root=Path(__file__).resolve().parents[1]/'app/tasks/builtin'
    assert all('playwright' not in p.read_text() for p in root.glob('*.py'))


async def test_scope_closes_all_when_one_close_fails():
    scoped=ScopedBrowserAdapter(FakeBrowserAdapter(),TaskContext(AccountContext(1,'web','WEB',''),'run'))
    first,second=AsyncMock(),AsyncMock()
    first.close.side_effect=BrowserSessionError()
    scoped._sessions=[first,second]
    with pytest.raises(BrowserSessionError):
        await scoped.aclose()
    second.close.assert_awaited_once()


async def test_worker_graceful_waits_for_browser_task(tmp_path):
    from contextlib import asynccontextmanager

    from app.workers.worker import Worker
    opened,finish=asyncio.Event(),asyncio.Event()
    fake=FakeBrowserAdapter()
    await fake.start()
    class Provider:
        def health(self):
            return fake.health()
        @asynccontextmanager
        async def for_context(self, context, required):
            scoped=ScopedBrowserAdapter(fake,context)
            try:
                yield {'browser':scoped}
            finally:
                await scoped.aclose()
    class WaitingTask(FakeTask):
        async def execute(self, context):
            await context.get_adapter('browser').create_session()
            opened.set()
            await finish.wait()
            return TaskResult(success=True,status=ExecutionStatus.SUCCESS,message='完成')
    registry=TaskRegistry();registry.register(WaitingTask)
    engine=TaskEngine(None,registry,adapter_provider=Provider())
    queue,service,redis=AsyncMock(),AsyncMock(),AsyncMock()
    worker=Worker(queue,service,engine,redis,config(tmp_path))
    task=asyncio.create_task(engine.run('BROWSER_TEST',TaskContext(AccountContext(1,'web','WEB',''),'run')))
    worker.tasks.add(task)
    await opened.wait()
    worker.stop.set()
    shutdown=asyncio.create_task(worker.run())
    await asyncio.sleep(.02)
    assert not shutdown.done()
    finish.set()
    await asyncio.wait_for(shutdown,1)
    assert task.result().success and all(s.closed for s in fake.sessions)
    queue.dequeue.assert_not_awaited()


async def test_session_close_timeout_releases_slot(tmp_path):
    manager,_,_,_=mocked_manager(tmp_path,browser_max_contexts=1,browser_timeout=.03)
    await manager.startup()
    session=await manager.create_session(1)
    async def slow():
        await asyncio.sleep(5)
    session._context.close.side_effect=slow
    with pytest.raises(BrowserSessionError):
        await session.close()
    assert not manager.sessions
    await asyncio.wait_for(manager.create_session(2),1)
    await manager.shutdown()


def test_evidence_redacts_query_and_title():
    from pydantic import ValidationError
    evidence=BrowserEvidence(final_url='https://example.test/account?token=secret#fragment')
    assert evidence.final_url=='https://example.test'
    with pytest.raises(ValidationError):
        BrowserEvidence(page_title='unreviewed page data')


@pytest.mark.parametrize('policy', ['INVALID', None])
async def test_invalid_screenshot_policy_rejected(tmp_path,policy):
    manager,_,_,_=mocked_manager(tmp_path)
    await manager.startup()
    with pytest.raises(BrowserSessionError):
        await manager.create_session(1,screenshot_policy=policy)
    assert not manager.sessions
    await manager.shutdown()
