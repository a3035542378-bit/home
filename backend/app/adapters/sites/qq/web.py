from contextlib import asynccontextmanager

from pydantic import ValidationError

from app.adapters.browser.exceptions import (
    BrowserClosedError,
    BrowserError,
    BrowserNavigationError,
    BrowserNavigationTimeout,
    BrowserPageCrashError,
    BrowserStartError,
    BrowserStorageError,
)
from app.adapters.browser.schemas import ScreenshotPolicy, safe_origin
from app.adapters.sites.base import SiteAdapter
from app.adapters.sites.qq import selectors as sel
from app.adapters.sites.qq.exceptions import (
    SiteLayoutChanged,
    SiteNavigationFailed,
    SiteNeedUserAction,
    SiteNotAuthenticated,
    SiteNotConfigured,
    SiteParseFailed,
)
from app.adapters.sites.qq.schemas import (
    ActivitySummary,
    ItemStatus,
    LoginState,
    LoginStatus,
    PageKey,
    PageStatus,
    SiteEvidence,
    TaskCenterSummary,
    TaskItem,
)
from app.models.common import utcnow

CAPABILITIES = {"site.qq." + name: True for name in (
    "login_status", "page_status", "task_center.read", "activity.read",
)}


class QQWebSiteAdapter(SiteAdapter):
    def __init__(self, browser, *, fixture_profile=None):
        self.browser, self.profile = browser, fixture_profile
        if fixture_profile is not None and not isinstance(fixture_profile, sel.FixtureProfile):
            raise SiteNotConfigured()

    def capabilities(self):
        return dict(CAPABILITIES)

    @asynccontextmanager
    async def _page(self, key):
        # 尚无真实 QQ 页面核验资料，生产路径封闭；配置 URL 不代表 Selector 已验证。
        if self.profile is None:
            raise SiteNotConfigured()
        try:
            await self.browser.start()
            async with await self.browser.create_session(
                restore_state=True, screenshot_policy=ScreenshotPolicy.DISABLED,
                request_policy=self.profile.permits,
            ) as session:
                if not session.storage_restored:
                    raise SiteNotAuthenticated()
                page = await session.new_page()
                try:
                    status = await page.goto(self.profile.url(key))
                except BrowserError:
                    if session.guard_state["blocked"]:
                        raise SiteNotConfigured() from None
                    raise
                if session.guard_state["blocked"]:
                    raise SiteNotConfigured()
                if status in {401, 403}:
                    raise SiteNotAuthenticated()
                if status == 404:
                    raise SiteLayoutChanged()
                if status is not None and 400 <= status < 500:
                    raise SiteParseFailed()
                if status != 200:
                    raise SiteNavigationFailed()
                yield page
        except BrowserStorageError:
            raise SiteNotAuthenticated() from None
        except (BrowserNavigationError, BrowserNavigationTimeout, BrowserClosedError,
                BrowserPageCrashError, BrowserStartError):
            raise SiteNavigationFailed() from None
        except BrowserError:
            raise SiteParseFailed() from None

    async def _login(self, page):
        rows = await page.read_attributes(sel.LOGIN, ["data-fixture-login", "data-fixture-account"], limit=2)
        if len(rows) != 1:
            raise SiteLayoutChanged()
        try:
            state = LoginState(rows[0]["data-fixture-login"])
        except ValueError:
            state = LoginState.UNKNOWN
        if state != LoginState.AUTHENTICATED:
            raise SiteNeedUserAction(state)
        if rows[0]["data-fixture-account"] != str(page.session.account_id):
            raise SiteNotAuthenticated()
        return state

    async def _evidence(self, page, key, count=0):
        title = await page.title()
        if title != "QQ Web Fixture":
            raise SiteLayoutChanged()
        return SiteEvidence(page_key=key, final_url=safe_origin(page.url), page_title=title,
                            parsed_item_count=count, checked_at=utcnow().isoformat())

    async def check_login_status(self, page_key=PageKey.PROFILE):
        async with self._page(page_key) as page:
            state = await self._login(page)
            return LoginStatus(login_state=state, evidence=await self._evidence(page, page_key))

    async def get_page_status(self, page_key=PageKey.PROFILE):
        login = await self.check_login_status(page_key)
        return PageStatus(**login.model_dump())

    async def _items(self, page, container, selector, attributes):
        containers = await page.read_attributes(container, ["data-empty"], limit=2)
        if len(containers) != 1:
            raise SiteLayoutChanged()
        rows = await page.read_attributes(selector, attributes, limit=101)
        empty = containers[0]["data-empty"]
        if len(rows) > 100 or empty not in {"true", "false"} or (empty == "true") != (len(rows) == 0):
            raise SiteParseFailed()
        return rows

    async def get_task_center_summary(self):
        async with self._page(PageKey.TASK_CENTER) as page:
            await self._login(page)
            rows = await self._items(page, sel.TASK_CONTAINER, sel.TASK_ITEMS, ["data-task-key", "data-status"])
            try:
                items = [TaskItem(task_key=row["data-task-key"], title=sel.TITLES[row["data-task-key"]],
                                  status=ItemStatus(row["data-status"])) for row in rows]
                if len({item.task_key for item in items}) != len(items):
                    raise ValueError()
            except (KeyError, ValueError, ValidationError):
                raise SiteParseFailed() from None
            return TaskCenterSummary(total=len(items),
                completed=sum(item.status == ItemStatus.COMPLETED for item in items),
                pending=sum(item.status == ItemStatus.PENDING for item in items), items=items,
                evidence=await self._evidence(page, PageKey.TASK_CENTER, len(items)))

    async def get_activity_summary(self):
        async with self._page(PageKey.ACTIVITY_CENTER) as page:
            await self._login(page)
            rows = await self._items(page, sel.ACTIVITY_CONTAINER, sel.ACTIVITY_ITEMS, ["data-available"])
            if any(row["data-available"] not in {"true", "false"} for row in rows):
                raise SiteParseFailed()
            return ActivitySummary(activity_count=len(rows),
                available_count=sum(row["data-available"] == "true" for row in rows),
                evidence=await self._evidence(page, PageKey.ACTIVITY_CENTER, len(rows)))
