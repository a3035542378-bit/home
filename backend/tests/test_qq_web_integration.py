from contextlib import asynccontextmanager

import pytest
from test_browser_unit import config
from test_qq_web_tasks import CODES, run

from app.adapters.browser import BrowserAdapter
from app.adapters.sites.qq.selectors import FixtureProfile
from app.adapters.sites.qq.web import QQWebSiteAdapter
from app.services.runtime_adapters import ScopedBrowserAdapter
from app.tasks.base import AccountContext, TaskContext
from app.tools.browser_site import browser_site
from app.tools.qq_web_fixture import fixture_state

pytestmark = pytest.mark.browser_integration


@asynccontextmanager
async def site_fixture(tmp_path, *, state=True, account_id=1, **profile):
    browser = BrowserAdapter(config(tmp_path))
    requests = []
    async with browser_site(requests) as origin:
        if state:
            await browser.manager.storage.save(1, fixture_state(1))
        scoped = ScopedBrowserAdapter(browser, TaskContext(AccountContext(account_id, "123456", "QQ", "", None), "web-real"))
        site = QQWebSiteAdapter(scoped, fixture_profile=FixtureProfile(origin, **profile))
        try:
            yield site, browser, requests
        finally:
            await scoped.aclose()
            assert not browser.manager.sessions
            await browser.stop()
            assert not list((tmp_path / "shots").glob("*.png"))


@pytest.mark.parametrize("path,status,state", [
    ("/qq/login-authenticated", "SUCCESS", "AUTHENTICATED"),
    ("/qq/login-required", "NEED_USER_ACTION", "NOT_AUTHENTICATED"),
    ("/qq/qr", "NEED_USER_ACTION", "NEED_QR_LOGIN"),
    ("/qq/captcha", "NEED_USER_ACTION", "NEED_CAPTCHA"),
    ("/qq/device-verification", "NEED_USER_ACTION", "NEED_DEVICE_VERIFICATION"),
    ("/qq/unknown", "NEED_USER_ACTION", "UNKNOWN"),
])
async def test_login_states(tmp_path, path, status, state):
    async with site_fixture(tmp_path, profile_path=path) as (site, _browser, requests):
        result = await run(CODES[0], site)
        assert result.status == status and result.data["login_state"] == state
        assert all(method == "GET" and path.startswith("/qq/") for method, path in requests)


@pytest.mark.parametrize("path,total,error", [
    ("/qq/task-center", 3, None), ("/qq/task-center-empty", 0, None),
    ("/qq/task-center-layout-broken", None, "SITE_LAYOUT_CHANGED"),
    ("/qq/task-center-parse-error", None, "SITE_PARSE_FAILED"),
])
async def test_task_summary(tmp_path, path, total, error):
    async with site_fixture(tmp_path, task_path=path) as (site, _browser, requests):
        result = await run(CODES[2], site)
        assert result.error_code == error and not result.retryable
        if not error:
            assert result.data["total"] == total
            if total:
                assert result.data["completed"] == result.data["pending"] == 1
                assert result.data["items"][2]["status"] == "CLAIMABLE"
        assert "private" not in result.model_dump_json() and "<" not in result.model_dump_json()
        assert requests == [("GET", path)]


@pytest.mark.parametrize("path,count,error", [("/qq/activity", 2, None), ("/qq/activity-empty", 0, None),
    ("/qq/activity-parse-error", None, "SITE_PARSE_FAILED")])
async def test_activity(tmp_path, path, count, error):
    async with site_fixture(tmp_path, activity_path=path) as (site, _, _requests):
        result = await run(CODES[3], site)
        assert result.error_code == error
        if not error:
            assert result.data["activity_count"] == count
            assert result.data["available_count"] == (1 if count else 0)


@pytest.mark.parametrize("state,account", [(False, 1), (True, 2)])
async def test_no_state_or_other_account_state(tmp_path, state, account):
    async with site_fixture(tmp_path, state=state, account_id=account) as (site, _, requests):
        result = await run(CODES[0], site)
        assert result.status == "NEED_USER_ACTION" and result.error_code == "SITE_NOT_AUTHENTICATED"
        assert not requests


@pytest.mark.parametrize("path", ["/qq/redirect-blocked", "/qq/subrequest-blocked"])
async def test_network_guard(tmp_path, path):
    async with site_fixture(tmp_path, profile_path=path) as (site, _, requests):
        result = await run(CODES[1], site)
        assert requests == [("GET", path)]
        assert result.error_code == "SITE_NOT_CONFIGURED" and not result.retryable


async def test_state_identity_mismatch(tmp_path):
    async with site_fixture(tmp_path) as (site, browser, _requests):
        await browser.manager.storage.save(1, fixture_state(2))
        result = await run(CODES[0], site)
        assert result.status == "NEED_USER_ACTION" and result.error_code == "SITE_NOT_AUTHENTICATED"


async def test_two_account_contexts_keep_separate_state(tmp_path):
    import asyncio
    browser = BrowserAdapter(config(tmp_path))
    async with browser_site() as origin:
        async def read(account_id):
            await browser.manager.storage.save(account_id, fixture_state(account_id))
            scoped = ScopedBrowserAdapter(browser, TaskContext(
                AccountContext(account_id, str(account_id), "QQ", "", None), "isolated"))
            try:
                site = QQWebSiteAdapter(scoped, fixture_profile=FixtureProfile(origin))
                return await site.check_login_status()
            finally:
                await scoped.aclose()
        try:
            results = await asyncio.gather(read(1), read(2))
            assert all(result.authenticated for result in results)
            assert not browser.manager.sessions
        finally:
            await browser.stop()
